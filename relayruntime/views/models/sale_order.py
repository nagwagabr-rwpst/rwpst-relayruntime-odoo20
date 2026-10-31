# -*- coding: utf-8 -*-

import logging

from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    whatsapp_campaign_id = fields.Many2one(
        'whatsapp.bulk.campaign',
        string='WhatsApp Campaign',
        ondelete='set null',
        copy=False,
    )
    whatsapp_log_id = fields.Many2one(
        'whatsapp.message.log',
        string='WhatsApp Log',
        ondelete='set null',
        copy=False,
    )

    def action_send_whatsapp(self):
        """Open the WhatsApp send wizard for the sales order customer."""
        self.ensure_one()
        partner = self.partner_id
        if not partner:
            raise UserError(_('Please set a customer on this sales order before sending WhatsApp.'))

        from odoo.exceptions import ValidationError
        try:
            number = partner._whatsapp_get_phone_number()
        except ValidationError as err:
            raise UserError(str(err)) from err

        _logger.info('Opening WhatsApp wizard for sale order %s', self.id)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send WhatsApp'),
            'res_model': 'whatsapp.send.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_recipient_number': number,
                'default_res_model': 'sale.order',
                'default_res_id': self.id,
            },
        }
