# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Bonus rule in pricelists',
    'version': '1.2',
    'category': 'Sales/Sales',
    'depends': ['base', 'sale', 'account'],
    'description': """
        This is a custom module to allow bonus rules in pricelists.
    """,
    'data': [
        'views/product_pricelist_views.xml',
        'views/invoice_report.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
