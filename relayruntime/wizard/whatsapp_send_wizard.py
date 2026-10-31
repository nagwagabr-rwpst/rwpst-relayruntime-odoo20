# -*- coding: utf-8 -*-

import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from odoo.addons.relayruntime.services.whatsapp_safety_utils import WhatsAppSafetyValidator
from odoo.addons.relayruntime.services.whatsapp_service import WhatsAppService

_logger = logging.getLogger(__name__)


class WhatsAppSendWizard(models.TransientModel):
    _name = 'whatsapp.send.wizard'
    _description = 'Send WhatsApp Message Wizard'

    recipient_number = fields.Char(
        string='Recipient Number',
        required=True,
        help='International format recommended, e.g. +20 10 1234 5678',
    )
    message = fields.Text(
        string='Message',
        required=True,
    )
    attachment = fields.Binary(string='Attachment')
    attachment_filename = fields.Char(string='Attachment Filename')
    res_model = fields.Char(string='Related Model')
    res_id = fields.Integer(string='Related Record ID')

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        if defaults.get('recipient_number'):
            return defaults
        if 'recipient_number' not in fields_list:
            return defaults

        res_model = defaults.get('res_model') or self.env.context.get('default_res_model')
        res_id = defaults.get('res_id') or self.env.context.get('default_res_id')
        if res_model == 'res.partner' and res_id:
            partner = self.env['res.partner'].browse(res_id).exists()
            if partner:
                number = partner._whatsapp_find_phone_number()
                if number:
                    defaults['recipient_number'] = number
        elif res_model == 'sale.order' and res_id:
            order = self.env['sale.order'].browse(res_id).exists()
            if order.partner_id:
                number = order.partner_id._whatsapp_find_phone_number()
                if number:
                    defaults['recipient_number'] = number
        return defaults

    def action_send(self):
        self.ensure_one()
        if not self.recipient_number:
            raise UserError(_('Recipient phone number is required.'))
        if not self.message and not self.attachment:
            raise UserError(_('Please enter a message or attach a file.'))

        recipient = WhatsAppService.normalize_phone_number(self.recipient_number)
        if not recipient:
            raise UserError(_('Recipient phone number is invalid.'))

        config = self.env['whatsapp.config'].get_active_config()
        safety = WhatsAppSafetyValidator(self.env, config)
        safety.check_daily_limit(planned_sends=1)
        if self.attachment:
            safety.validate_single_binary_attachment(self.attachment, self.attachment_filename)

        service = WhatsAppService(self.env, config)

        if self.attachment:
            attachment = self.env['ir.attachment'].create({
                'name': self.attachment_filename or 'attachment',
                'raw': self.attachment,
                'res_model': self._name,
                'res_id': self.id,
            })
            safety.validate_attachments(attachment)
            result = service.send_attachment(
                recipient,
                self.message,
                attachment,
            )
        else:
            result = service.send_text_message(recipient, self.message)

        partner = self.env['res.partner']
        recipient_label = recipient
        if self.res_model == 'res.partner' and self.res_id:
            partner = self.env['res.partner'].browse(self.res_id).exists()
            if partner:
                recipient_label = partner.display_name

        delivery_state = 'sent' if result['success'] else 'failed'
        self.env['whatsapp.message.log'].create_log(
            recipient=recipient_label,
            recipient_number=recipient,
            message=self.message or _('(attachment)'),
            delivery_state=delivery_state,
            related_model=self.res_model,
            related_record_id=self.res_id or 0,
            partner_id=partner.id if partner else False,
            api_response=result.get('response'),
            api_message_id=result.get('provider_message_id'),
            failure_reason=result.get('error') if not result['success'] else False,
            retryable=result.get('retryable', not result['success']),
            attachment_count=1 if self.attachment else 0,
        )

        if not result['success']:
            raise UserError(
                _('Failed to send WhatsApp message. %s')
                % (result.get('error') or json.dumps(result.get('response', {})))
            )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Message Sent'),
                'message': _('WhatsApp message was sent successfully.'),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_cancel(self):
        return {'type': 'ir.actions.act_window_close'}
