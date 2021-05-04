# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

try:
    from trytond.modules.saluc_multi_locations_inventory.tests.test_saluc_multi_locations_inventory import suite
except ImportError:
    from .test_saluc_multi_locations_inventory import suite

__all__ = ['suite']
