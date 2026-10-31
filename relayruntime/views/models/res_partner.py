# -*- coding: utf-8 -*-

import logging

from odoo import api, models, _
from odoo.exceptions import UserError, ValidationError

from odoo.addons.relayruntime.services.whatsapp_phone_utils import normalize_phone_number

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model
    def _whatsapp_phone_field_names(self):
        field_names = []
        partner_model = self.env['res.partner']
        if 'mobile' in partner_model._fields:
            field_names.append('mobile')
        if 'phone' in partner_model._fields:
            field_names.append('phone')
        return field_names

    @api.model
    def _whatsapp_normalize_phone(self, number):
        return normalize_phone_number(number)

    def _whatsapp_find_phone_number(self):
        self.ensure_one()
        for field_name in self._whatsapp_phone_field_names():
            number = self[field_name]
            if number:
                raw = number.strip() if isinstance(number, str) else number
                normalized = self._whatsapp_normalize_phone(raw)
                if normalized:
                    return normalized
        return ''

    def _whatsapp_get_phone_number(self):
        self.ensure_one()
        field_names = self._whatsapp_phone_field_names()
        if not field_names:
            raise ValidationError(
                _('No phone fields are available on contacts. Cannot send WhatsApp messages.')
            )
        number = self._whatsapp_find_phone_number()
        if not number:
            labels = []
            if 'mobile' in field_names:
                labels.append(_('mobile'))
            if 'phone' in field_names:
                labels.append(_('phone'))
            raise ValidationError(
                _('No valid phone number is available on this contact. Please set a %s number.')
                % ' / '.join(labels)
            )
        return number

    def action_whatsapp_bulk_send_list(self):
        """Open bulk wizard from list view header (selected contacts)."""
        if not self:
            raise UserError(_('Select at least one contact to send WhatsApp messages.'))
        _logger.info('Opening bulk WhatsApp wizard for %s partner(s)', len(self))
        return {
            'type': 'ir.actions.act_window',
            'name': _('WhatsApp Bulk Send'),
            'res_model': 'whatsapp.bulk.send.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_recipient_ids': self.ids,
            },
        }

    def action_send_whatsapp(self):
        self.ensure_one()
        number = self._whatsapp_get_phone_number()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send WhatsApp'),
            'res_model': 'whatsapp.send.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_recipient_number': number,
                'default_res_model': 'res.partner',
                'default_res_id': self.id,
            },
        }
