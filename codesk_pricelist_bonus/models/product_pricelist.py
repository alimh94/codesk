# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from itertools import chain

from odoo import api, fields, models, tools, _
import math
from itertools import groupby
from odoo.exceptions import AccessError, UserError, ValidationError


class ProductTemplate(models.Model):
    _inherit = "product.template"

    has_bonus = fields.Boolean(string="Has Bonus Rules", default=False)
    ordered_quantity = fields.Float('Ordered Quantity', default=0)
    bonus_quantity = fields.Float('Bonus Quantity', default=0)


class ProductCategory(models.Model):
    _inherit = "product.category"

    has_bonus = fields.Boolean(string="Has Bonus Rules", default=False)
    ordered_quantity = fields.Float('Ordered Quantity',  default=0)
    bonus_quantity = fields.Float('Bonus Quantity', default=0)


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    is_bonus = fields.Boolean(default=False, readonly=True)
    bonus_quantity = fields.Float('Bonus Quantity', digits='Product Unit of Measure', default=0)

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

    @api.model_create_multi
    def create(self, vals_list):
        # OVERRIDE
        ACCOUNTING_FIELDS = ('debit', 'credit', 'amount_currency')
        BUSINESS_FIELDS = ('price_unit', 'quantity', 'discount', 'tax_ids')

        for vals in vals_list:
            move = self.env['account.move'].browse(vals['move_id'])
            vals.setdefault('company_currency_id', move.company_id.currency_id.id) # important to bypass the ORM limitation where monetary fields are not rounded; more info in the commit message

            # Ensure balance == amount_currency in case of missing currency or same currency as the one from the
            # company.
            currency_id = vals.get('currency_id') or move.company_id.currency_id.id
            if currency_id == move.company_id.currency_id.id:
                balance = vals.get('debit', 0.0) - vals.get('credit', 0.0)
                vals.update({
                    'currency_id': currency_id,
                    'amount_currency': balance,
                })
            else:
                vals['amount_currency'] = vals.get('amount_currency', 0.0)

            if move.is_invoice(include_receipts=True):
                currency = move.currency_id
                partner = self.env['res.partner'].browse(vals.get('partner_id'))
                taxes = self.new({'tax_ids': vals.get('tax_ids', [])}).tax_ids
                tax_ids = set(taxes.ids)
                taxes = self.env['account.tax'].browse(tax_ids)

                # Ensure consistency between accounting & business fields.
                # As we can't express such synchronization as computed fields without cycling, we need to do it both
                # in onchange and in create/write. So, if something changed in accounting [resp. business] fields,
                # business [resp. accounting] fields are recomputed.
                if any(vals.get(field) for field in ACCOUNTING_FIELDS):
                    price_subtotal = self._get_price_total_and_subtotal_model(
                        vals.get('price_unit', 0.0),
                        vals.get('quantity', 0.0),
                        vals.get('discount', 0.0),
                        currency,
                        self.env['product.product'].browse(vals.get('product_id')),
                        partner,
                        taxes,
                        move.move_type,
                    ).get('price_subtotal', 0.0)
                    vals.update(self._get_fields_onchange_balance_model(
                        vals.get('quantity', 0.0),
                        vals.get('discount', 0.0),
                        vals['amount_currency'],
                        move.move_type,
                        currency,
                        taxes,
                        price_subtotal
                    ))
                    vals.update(self._get_price_total_and_subtotal_model(
                        vals.get('price_unit', 0.0),
                        vals.get('quantity', 0.0),
                        vals.get('discount', 0.0),
                        currency,
                        self.env['product.product'].browse(vals.get('product_id')),
                        partner,
                        taxes,
                        move.move_type,
                    ))
                elif any(vals.get(field) for field in BUSINESS_FIELDS):
                    vals.update(self._get_price_total_and_subtotal_model(
                        vals.get('price_unit', 0.0),
                        vals.get('quantity', 0.0),
                        vals.get('discount', 0.0),
                        currency,
                        self.env['product.product'].browse(vals.get('product_id')),
                        partner,
                        taxes,
                        move.move_type,
                    ))
                    vals.update(self._get_fields_onchange_subtotal_model(
                        vals['price_subtotal'],
                        move.move_type,
                        currency,
                        move.company_id,
                        move.date,
                    ))

        lines = super(AccountMoveLine, self).create(vals_list)
        product_template = self.env['product.template']
        product_category = self.env['product.category']
        bonus_quantity = 0
        for line in lines:
            if not line.is_bonus:
                product = product_template.browse(line.product_id.product_tmpl_id.id)
                category = product_category.browse(line.product_id.product_tmpl_id.categ_id.id)
                if line.bonus_quantity > 0:
                    bonus_quantity = line.bonus_quantity
                elif product.has_bonus:
                    if line.quantity >= product.ordered_quantity:
                        bonus_quantity = product.bonus_quantity * (math.floor(line.quantity/product.ordered_quantity))
                elif category.has_bonus:
                    if line.quantity >= category.ordered_quantity:
                        bonus_quantity = category.bonus_quantity * (math.floor(line.quantity/category.ordered_quantity))
                if bonus_quantity > 0:
                    line.bonus_quantity = bonus_quantity
                    self.env['account.move.line'].create({
                        'name': line.product_id.name,
                        'product_id': line.product_id.id,
                        'quantity': bonus_quantity,
                        'price_unit': 0,
                        'is_bonus': True,
                        'move_id': line.move_id.id,
                        'account_id': line.account_id.id,
                        'tax_ids': [],
                    })
        moves = lines.mapped('move_id')
        if self._context.get('check_move_validity', True):
            moves._check_balanced()
        moves._check_fiscalyear_lock_date()
        lines._check_tax_lock_date()
        moves._synchronize_business_models({'line_ids'})

        return lines
