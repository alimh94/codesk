# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from itertools import chain

from odoo import api, fields, models, tools, _
from itertools import groupby
from odoo.exceptions import AccessError, UserError, ValidationError


class PricelistItem(models.Model):
    _inherit = "product.pricelist.item"

    compute_price = fields.Selection([
        ('fixed', 'Fixed Price'),
        ('percentage', 'Percentage (discount)'),
        ('formula', 'Formula'),
        ('bonus', 'Bonus')], index=True, default='fixed', required=True)

    ordered_quantity = fields.Float('Ordered Quantity', digits='Product Unit of Measure', default=0)
    bonus_quantity = fields.Float('Bonus Quantity', digits='Product Unit of Measure', default=0)


class CustomSaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    active = fields.Boolean(default=True, readonly=True)
    ordered_quantity = fields.Float('Ordered Quantity', digits='Product Unit of Measure', readonly=True, default=0)
    bonus_quantity = fields.Float('Bonus Quantity', digits='Product Unit of Measure', readonly=True, default=0)

    @api.model
    def create(self, vals):
        lines = super(CustomSaleOrderLine, self).create(vals)
        PricelistItem = self.env['product.pricelist.item']
        for line in lines:
            product_context = dict(line.env.context, partner_id=line.order_id.partner_id.id, date=line.order_id.date_order,
                                   uom=line.product_uom.id)
            final_price, rule_id = line.order_id.pricelist_id.with_context(product_context).get_product_price_rule(line.product_id, line.product_uom_qty or 1.0, line.order_id.partner_id)
            if rule_id:
                pricelist_item = PricelistItem.browse(rule_id)
                if pricelist_item.compute_price == 'bonus':
                    if line.product_uom_qty >= pricelist_item.ordered_quantity:
                        line.bonus_quantity = pricelist_item.bonus_quantity
                        sol = self.env['sale.order.line'].create({
                            'name': line.product_id.name,
                            'product_id': line.product_id.id,
                            'product_uom_qty': pricelist_item.bonus_quantity,
                            'product_uom': line.product_id.uom_id.id,
                            'price_unit': 0,
                            'active': False,
                            'order_id': line.order_id.id,
                        })
        return lines

    def _prepare_invoice_line(self, **optional_values):
        """
        Prepare the dict of values to create the new invoice line for a sales order line.

        :param qty: float quantity to invoice
        :param optional_values: any parameter that should be added to the returned invoice line
        """
        self.ensure_one()
        res = {
            'display_type': self.display_type,
            'sequence': self.sequence,
            'name': self.name,
            'product_id': self.product_id.id,
            'product_uom_id': self.product_uom.id,
            'quantity': self.qty_to_invoice,
            'bonus_quantity': self.bonus_quantity,
            'discount': self.discount,
            'price_unit': self.price_unit,
            'tax_ids': [(6, 0, self.tax_id.ids)],
            'analytic_account_id': self.order_id.analytic_account_id.id,
            'analytic_tag_ids': [(6, 0, self.analytic_tag_ids.ids)],
            'sale_line_ids': [(4, self.id)],
        }
        if optional_values:
            res.update(optional_values)
        if self.display_type:
            res['account_id'] = False
        return res


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    ordered_quantity = fields.Float('Ordered Quantity', digits='Product Unit of Measure', readonly=True, default=0)
    bonus_quantity = fields.Float('Bonus Quantity', digits='Product Unit of Measure', readonly=True,default=0)

    tax_amount_line = fields.Monetary(string='Tax Amount', store=True, readonly=True, compute='_tax_amount_line')
    price_total_line = fields.Monetary(string='Line Total', store=True, readonly=True,
                                     currency_field='currency_id', compute='_price_total_line')

    @api.depends('tax_ids', 'price_unit', 'quantity')
    def _tax_amount_line(self):
        for rec in self:
            if rec.tax_ids:
                tax_amount_line = 0
                for tax in rec.tax_ids:
                    tax_amount_line += rec.quantity * ((rec.price_unit * tax.amount) / 100)
                rec.tax_amount_line = tax_amount_line
            else:
                rec.tax_amount_line = 0

    @api.depends('price_subtotal', 'tax_amount_line')
    def _price_total_line(self):
        for rec in self:
            rec.price_total_line = rec.price_subtotal + rec.tax_amount_line
