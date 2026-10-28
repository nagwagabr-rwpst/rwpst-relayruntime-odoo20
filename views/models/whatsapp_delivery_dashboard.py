# -*- coding: utf-8 -*-

import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class WhatsAppDeliveryDashboard(models.TransientModel):
    _name = 'whatsapp.delivery.dashboard'
    _description = 'Delivery Dashboard'

    total_sent = fields.Integer(string='Total Sent', readonly=True)
    total_failed = fields.Integer(string='Total Failed', readonly=True)
    total_skipped = fields.Integer(string='Total Skipped', readonly=True)
    total_processed = fields.Integer(string='Total Processed', readonly=True)
    success_rate = fields.Float(string='Success Rate %', readonly=True, digits=(16, 2))

    @api.model
    def action_open_dashboard(self):
        stats = self.env['whatsapp.message.log'].get_dashboard_stats()
        dashboard = self.create(stats)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Delivery Dashboard'),
            'res_model': 'whatsapp.delivery.dashboard',
            'res_id': dashboard.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_sent_logs(self):
        return self._open_logs([('delivery_state', 'in', ['sent', 'delivered'])])

    def action_open_failed_logs(self):
        return self._open_logs([('delivery_state', '=', 'failed')])

    def action_open_skipped_logs(self):
        return self._open_logs([('delivery_state', '=', 'skipped')])

    def action_open_all_logs(self):
        return self._open_logs([])

    def _open_logs(self, domain):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Message Logs'),
            'res_model': 'whatsapp.message.log',
            'view_mode': 'list,form,graph,pivot',
            'domain': domain,
            'context': {'create': False},
        }
