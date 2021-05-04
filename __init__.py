# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

from trytond.pool import Pool
from . import inventory

__all__ = ['register']


def register():
    Pool.register(
        inventory.MultiLocationsInventory,
        inventory.MultiLocationsInventoryLine,
        inventory.Inventory,
        module='saluc_multi_locations_inventory', type_='model')
