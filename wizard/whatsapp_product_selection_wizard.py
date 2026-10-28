# -*- coding: utf-8 -*-

import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WhatsAppProductSelectionLine(models.TransientModel):
    _name = 'whatsapp.product.selection.line'
    _description = 'WhatsApp Product Selection Line'

    wizard_id = fields.Many2one(
        'whatsapp.product.selection.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(string='#', default=10)
    product_id = fields.Many2one(
        'product.template',
        string='Product',
        required=True,
    )
    quantity = fields.Float(string='Quantity', default=1.0, required=True)
    notes = fields.Char(string='Notes')


class WhatsAppProductSelectionWizard(models.TransientModel):
    _name = 'whatsapp.product.selection.wizard'
    _description = 'WhatsApp Product Selection Wizard'

    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=True,
    )
    campaign_id = fields.Many2one('whatsapp.bulk.campaign', string='Campaign')
    log_id = fields.Many2one('whatsapp.message.log', string='Message Log')
    line_ids = fields.One2many(
        'whatsapp.product.selection.line',
        'wizard_id',
        string='Selected Products',
    )
    notes = fields.Text(string='Notes')
    sale_order_id = fields.Many2one('sale.order', string='Sale Order', readonly=True)

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        if 'line_ids' not in fields_list:
            return defaults
        product_ids = self.env.context.get('default_product_ids')
        if isinstance(product_ids, list) and product_ids and product_ids[0][0] == 6:
            pids = product_ids[0][2]
        elif self.env.context.get('default_campaign_id'):
            campaign = self.env['whatsapp.bulk.campaign'].browse(
                self.env.context['default_campaign_id']
            )
            pids = campaign.product_ids.ids
        else:
            pids = []
        if pids:
            defaults['line_ids'] = [
                (0, 0, {'sequence': (i + 1) * 10, 'product_id': pid, 'quantity': 1.0})
                for i, pid in enumerate(pids)
            ]
        return defaults

    def action_create_sale_order(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Add at least one product line.'))
        if not self.partner_id:
            raise UserError(_('Please select a customer.'))

        order_vals = {
            'partner_id': self.partner_id.id,
            'origin': _('WhatsApp Campaign %s') % (self.campaign_id.name or ''),
            'note': self.notes or '',
            'whatsapp_campaign_id': self.campaign_id.id,
            'whatsapp_log_id': self.log_id.id,
        }
        order = self.env['sale.order'].create(order_vals)

        for line in self.line_ids.sorted(key=lambda l: l.sequence):
            product = line.product_id
            variant = product.product_variant_id or product.product_variant_ids[:1]
            if not variant:
                continue
            self.env['sale.order.line'].create({
                'order_id': order.id,
                'product_id': variant.id,
                'product_uom_qty': line.quantity,
                'name': line.notes or product.name,
            })

        self.sale_order_id = order.id
        _logger.info(
            'Created sale order %s from WhatsApp selection (campaign=%s, partner=%s)',
            order.id,
            self.campaign_id.id,
            self.partner_id.id,
        )

        return {
            'type': 'ir.actions.act_window',
            'name': _('Sale Order'),
            'res_model': 'sale.order',
            'res_id': order.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_cancel(self):
        return {'type': 'ir.actions.act_window_close'}
