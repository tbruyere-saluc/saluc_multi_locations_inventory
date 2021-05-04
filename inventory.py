# This file is part of saluc_party module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from itertools import groupby

from trytond.model import Workflow, Model, ModelView, ModelSQL, fields, Check
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, Bool
from trytond import backend
from trytond.transaction import Transaction

__all__ = ['MultiLocationsInventory', 'MultiLocationsInventoryLine',
           'Inventory']

STATES = {
    'readonly': Eval('state') != 'draft',
}
DEPENDS = ['state']
INVENTORY_STATES = [
    ('draft', 'Draft'),
    ('done', 'Done'),
    ('cancel', 'Canceled'),
    ]


class MultiLocationsInventory(Workflow, ModelSQL, ModelView):
    'Multi Locations Inventory'
    __name__ = 'multi.locations.inventory'
    _rec_name = 'number'
    number = fields.Char('Number', readonly=True)
    location = fields.Many2One(
        'stock.location', 'Location', required=True,
        domain=[('type', '=', 'storage')], states={
            'readonly': (Eval('state') != 'draft') | Eval('lines', [0]),
            },
        depends=['state'])
    date = fields.Date('Date', required=True, states={
            'readonly': (Eval('state') != 'draft') | Eval('lines', [0]),
            },
        depends=['state'])
    lost_found = fields.Many2One(
        'stock.location', 'Lost and Found', required=True,
        domain=[('type', '=', 'lost_found')], states=STATES, depends=DEPENDS)
    lines = fields.One2Many(
        'multi.locations.inventory.line', 'multilocationsinventory', 'Lines',
        states=STATES, depends=DEPENDS)
    empty_quantity = fields.Selection([
            (None, ""),
            ('keep', "Keep"),
            ('empty', "Empty"),
            ], "Empty Quantity", states=STATES, depends=DEPENDS,
        help="How lines without quantity are handled.")
    company = fields.Many2One('company.company', 'Company', required=True,
        states={
            'readonly': (Eval('state') != 'draft') | Eval('lines', [0]),
            },
        depends=['state'])
    state = fields.Selection(
        INVENTORY_STATES, 'State', readonly=True, select=True)

    @classmethod
    def __setup__(cls):
        super(MultiLocationsInventory, cls).__setup__()
        cls._order.insert(0, ('date', 'DESC'))
        cls._error_messages.update({
                'delete_cancel': ('Inventory "%s" must be cancelled before '
                    'deletion.'),
                'unique_line': ('Line "%s" is not unique '
                    'on Inventory "%s".'),
                })
        cls._transitions |= set((
                ('draft', 'done'),
                ('draft', 'cancel'),
                ))
        cls._buttons.update({
                'confirm': {
                    'invisible': (Eval('state').in_(['done', 'cancel'])
                        | ~Eval('lines', [])),
                    },
                'cancel': {
                    'invisible': Eval('state').in_(['cancel', 'done']),
                    },
                'complete_lines': {
                    'readonly': Eval('state') != 'draft',
                    },
                })

    @staticmethod
    def default_state():
        return 'draft'

    @staticmethod
    def default_date():
        Date = Pool().get('ir.date')
        return Date.today()

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @classmethod
    def default_lost_found(cls):
        Location = Pool().get('stock.location')
        locations = Location.search(cls.lost_found.domain)
        if len(locations) == 1:
            return locations[0].id

    @classmethod
    @ModelView.button
    @Workflow.transition('done')
    def confirm(cls, mlinventories):
        pool = Pool()
        Line = pool.get('multi.locations.inventory.line')
        Inventory = pool.get('stock.inventory')
        InventoryLine = pool.get('stock.inventory.line')
        inventories = []
        lines = []
        mllines = []

        for mlinventory in mlinventories:
            sorted_lines = sorted(mlinventory.lines, key=lambda l: l.location)
            for location, grouped_lines in groupby(sorted_lines,
                    lambda l: l.location):
                keys = set()
                inventory = Inventory()
                inventory.location = location.id
                inventory.lost_found = mlinventory.lost_found
                inventory.date = mlinventory.date
                inventory.empty_quantity = mlinventory.empty_quantity
                inventory.company = mlinventory.company
                inventories.append(inventory)
                for line in grouped_lines:
                    key = line.unique_key
                    if key in keys:
                        cls.raise_user_error('unique_line',
                            (line.rec_name, mlinventory.rec_name))
                    keys.add(key)
                    inventory_line = InventoryLine()
                    inventory_line.product = line.product.id
                    inventory_line.lot = line.lot
                    inventory_line.expected_quantity = line.expected_quantity
                    inventory_line.quantity = line.quantity
                    inventory_line.inventory = inventory
                    line.inventory = inventory
                    lines.append(inventory_line)
                    mllines.append(line)
        if inventories:
            Inventory.save(inventories)
            InventoryLine.save(lines)
            Line.save(mllines)
            Inventory.confirm(inventories)

    @classmethod
    @ModelView.button
    @Workflow.transition('cancel')
    def cancel(cls, inventories):
        pass

    @staticmethod
    def grouping():
        return ('product', 'lot', )

    @classmethod
    @ModelView.button
    def complete_lines(cls, inventories, fill=True):
        '''
        Complete or update the inventories
        '''
        pool = Pool()
        Line = pool.get('multi.locations.inventory.line')
        Product = pool.get('product.product')

        grouping = cls.grouping()
        to_create, to_write = [], []
        for inventory in inventories:
            # Once done computation is wrong because include created moves
            if inventory.state == 'done':
                continue
            # Compute product quantities
            if fill:
                product_ids = None
            else:
                product_ids = [l.product.id for l in inventory.lines]
            for location in inventory.location.childs:
                with Transaction().set_context(stock_date_end=inventory.date):
                    pbl = Product.products_by_location(
                        [location.id],
                        grouping=grouping,
                        grouping_filter=(product_ids,))
                # Index some data
                product2type = {}
                product2consumable = {}
                for product in Product.browse([line[1] for line in pbl]):
                    product2type[product.id] = product.type
                    product2consumable[product.id] = product.consumable

                # Update existing lines
                for line in inventory.lines:
                    if line.location == location:
                        if not (line.product.active and
                                line.product.type == 'goods'
                                and not line.product.consumable):
                            Line.delete([line])
                            continue

                        key = (location.id,) + line.unique_key
                        if key in pbl:
                            quantity = pbl.pop(key)
                        else:
                            quantity = 0.0
                        values = line.update_values4complete(quantity)
                        if values:
                            to_write.extend(([line], values))

                if not fill:
                    continue
                # Create lines if needed
                for key, quantity in pbl.iteritems():
                    product_id = key[grouping.index('product') + 1]
                    if (product2type[product_id] != 'goods'
                            or product2consumable[product_id]):
                        continue
                    if not quantity:
                        continue

                    values = Line.create_values4complete(
                        inventory, location, quantity)
                    for i, fname in enumerate(grouping, 1):
                        values[fname] = key[i]
                    to_create.append(values)
        if to_create:
            Line.create(to_create)
        if to_write:
            Line.write(*to_write)


class MultiLocationsInventoryLine(ModelSQL, ModelView):
    'Multi Locations Inventory Line'
    __name__ = 'multi.locations.inventory.line'
    _states = {
        'readonly': Eval('multilocationsinventory_state') != 'draft',
        }
    _depends = ['multilocationsinventory_state']

    location = fields.Many2One(
        'stock.location', 'Location', required=True,
        domain=[('type', '=', 'storage'),
                ('parent', '=',
                    Eval('_parent_multilocationsinventory',
                         {}).get('location', -1)),
            ],
        states=_states, depends=_depends)
    product = fields.Many2One('product.product', 'Product', required=True,
        domain=[
            ('type', '=', 'goods'),
            ('consumable', '=', False),
            ], states=_states, depends=_depends)
    lot = fields.Many2One('stock.lot', 'Lot',
        domain=[
            ('product', '=', Eval('product')),
            ],
        states=_states,
        depends=['product', 'inventory_state'])
    uom = fields.Function(fields.Many2One('product.uom', 'UOM'), 'get_uom')
    unit_digits = fields.Function(fields.Integer('Unit Digits'),
            'get_unit_digits')
    expected_quantity = fields.Float('Expected Quantity', required=True,
            digits=(16, Eval('unit_digits', 2)), readonly=True,
            depends=['unit_digits'])
    quantity = fields.Float('Quantity',
        digits=(16, Eval('unit_digits', 2)),
        states=_states, depends=['unit_digits'] + _depends)
    multilocationsinventory = fields.Many2One('multi.locations.inventory',
        'Multi Locations Inventory', required=True,
        ondelete='CASCADE',
        states={
            'readonly': _states['readonly']
            & Bool(Eval('multilocationsinventory')),
            },
        depends=_depends)
    multilocationsinventory_state = fields.Function(
        fields.Selection(INVENTORY_STATES, 'Multi Locations Inventory State'),
        'on_change_with_multilocationsinventory_state')
    inventory = fields.Many2One('stock.inventory', 'Inventory',
        ondelete='CASCADE')

    @classmethod
    def __setup__(cls):
        super(MultiLocationsInventoryLine, cls).__setup__()
        t = cls.__table__()
        cls._sql_constraints += [
            ('check_line_qty_pos', Check(t, t.quantity >= 0),
                'Line quantity must be positive.'),
            ]
        cls._order.insert(0, ('product', 'ASC'))

    @classmethod
    def __register__(cls, module_name):
        TableHandler = backend.get('TableHandler')

        super(MultiLocationsInventoryLine, cls).__register__(module_name)

        table = TableHandler(cls, module_name)
        # Migration from 4.6: drop required on quantity
        table.not_null_action('quantity', action='remove')

    @staticmethod
    def default_unit_digits():
        return 2

    @staticmethod
    def default_expected_quantity():
        return 0.

    @fields.depends('product')
    def on_change_product(self):
        self.unit_digits = 2
        if self.product:
            self.uom = self.product.default_uom
            self.unit_digits = self.product.default_uom.digits

    @fields.depends('multilocationsinventory',
        '_parent_multilocationsinventory.state')
    def on_change_with_multilocationsinventory_state(self, name=None):
        if self.multilocationsinventory:
            return self.multilocationsinventory.state
        return 'draft'

    def get_rec_name(self, name):
        rec_name = '%s - %s' % (self.location.rec_name, self.product.rec_name)
        if self.lot:
            rec_name += ' - %s' % self.lot.rec_name
        return rec_name

    @classmethod
    def search_rec_name(cls, name, clause):
        if clause[1].startswith('!') or clause[1].startswith('not '):
            bool_op = 'AND'
        else:
            bool_op = 'OR'
        return [bool_op,
                [('location.rec_name',) + tuple(clause[1:])],
                [('product.rec_name',) + tuple(clause[1:])],
                ]

    def get_uom(self, name):
        return self.product.default_uom.id

    def get_unit_digits(self, name):
        return self.product.default_uom.digits

    @property
    def unique_key(self):
        key = []
        for fname in self.multilocationsinventory.grouping():
            value = getattr(self, fname)
            if isinstance(value, Model):
                value = value.id
            key.append(value)
        return tuple(key)

    def update_values4complete(self, quantity):
        '''
        Return update values to complete inventory
        '''
        values = {}
        # if nothing changed, no update
        if self.quantity == self.expected_quantity == quantity:
            return values
        values['expected_quantity'] = quantity
        return values

    @classmethod
    def create_values4complete(cls, inventory, location, quantity):
        '''
        Return create values to complete inventory
        '''
        return {
            'multilocationsinventory': inventory.id,
            'location': location.id,
            'expected_quantity': quantity,
        }


class Inventory:
    __name__ = 'stock.inventory'
    __metaclass__ = PoolMeta

    multilocationsinventory = fields.One2Many('multi.locations.inventory.line',
        'inventory', 'Multi Locations Inventory', readonly=True,
        states={
            'invisible': ~Eval('multilocationsinventory'),
            })
