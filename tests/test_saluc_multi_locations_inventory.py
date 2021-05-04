# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

import unittest

import doctest

from trytond.tests.test_tryton import ModuleTestCase
from trytond.tests.test_tryton import suite as test_suite
from trytond.tests.test_tryton import doctest_teardown
from trytond.tests.test_tryton import doctest_checker


class SalucMultiLocationsInventoryTestCase(ModuleTestCase):
    'Test Saluc Multi Locations Inventory module'
    module = 'saluc_multi_locations_inventory'


def suite():
    suite = test_suite()
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(
            SalucMultiLocationsInventoryTestCase))
    suite.addTests(doctest.DocFileSuite(
            'scenario_saluc_multi_locations_inventory.rst',
            tearDown=doctest_teardown, encoding='utf-8',
            checker=doctest_checker,
            optionflags=doctest.REPORT_ONLY_FIRST_FAILURE))
    return suite
