# -*- coding: utf-8 -*-

import json
import logging
import time

from psycopg2 import IntegrityError

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

DELIVERY_STATE_SELECTION = [
    ('queued', 'Queued'),
    ('sending', 'Sending'),
    ('sent', 'Sent'),
    ('delivered', 'Delivered'),
    ('failed', 'Failed'),
    ('skipped', 'Skipped'),
]

_LEGACY_STATUS_MAP = {
    'queued': 'pending',
    'sending': 'pending',
    'sent': 'sent',
    'delivered': 'sent',
    'failed': 'failed',
    'skipped': 'skipped',
}


class WhatsAppMessageLog(models.Model):
    _name = 'whatsapp.message.log'
    _description = 'WhatsApp Message Log'
    _order = 'sent_at desc, id desc'

    recipient = fields.Char(string='Recipient', required=True, index=True)
    recipient_number = fields.Char(string='Recipient Number', index=True)
    message = fields.Text(string='Message', required=True)
    message_preview = fields.Char(string='Preview', compute='_compute_message_preview', store=True)
    delivery_state = fields.Selection(
        selection=DELIVERY_STATE_SELECTION,
        string='Delivery State',
        required=True,
        default='queued',
        index=True,
    )
    status = fields.Selection(
        selection=[
            ('sent', 'Sent'),
            ('failed', 'Failed'),
            ('pending', 'Pending'),
            ('skipped', 'Skipped'),
        ],
        string='Status',
        compute='_compute_status',
        store=True,
        index=True,
    )
    related_model = fields.Char(string='Related Model', index=True)
    related_record_id = fields.Integer(string='Related Record ID', index=True)
    partner_id = fields.Many2one('res.partner', string='Contact', index=True, ondelete='set null')
    campaign_id = fields.Many2one(
        'whatsapp.bulk.campaign',
        string='Bulk Campaign',
        index=True,
        ondelete='set null',
    )
    execution_id = fields.Many2one(
        'whatsapp.bulk.execution',
        string='Execution Attempt',
        index=True,
        ondelete='set null',
        readonly=True,
    )
    outbound_intent_at = fields.Datetime(
        string='Outbound Intent At',
        readonly=True,
        index=True,
        help='When delivery was committed in DB before calling the provider.',
    )
    attachment_info = fields.Char(string='Attachments')
    attachment_count = fields.Integer(string='Attachment Count', default=0)
    failure_reason = fields.Text(string='Failure Reason')
    error_message = fields.Text(string='Error Message')
    exception_type = fields.Char(string='Exception Type', index=True)
    traceback_summary = fields.Text(string='Traceback Summary')
    api_response = fields.Text(string='API Response')
    api_response_body = fields.Text(string='API Response Body')
    failed_at = fields.Datetime(string='Failed At', index=True)
    retryable = fields.Boolean(string='Retryable', default=True)
    api_message_id = fields.Char(string='API Message ID', index=True)
    idempotency_key = fields.Char(string='Idempotency Key', index=True, copy=False)
    processing_duration = fields.Float(string='Processing Duration (s)', digits=(16, 3))
    sent_by = fields.Many2one(
        'res.users',
        string='Sent By',
        default=lambda self: self.env.user,
        readonly=True,
    )
    sent_at = fields.Datetime(
        string='Sent At',
        default=fields.Datetime.now,
        readonly=True,
        index=True,
    )
    sent_date = fields.Datetime(
        string='Sent Date',
        related='sent_at',
        store=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        index=True,
    )
    product_ids = fields.Many2many(
        'product.template',
        string='Products',
        readonly=True,
    )

    _whatsapp_message_log_idempotency_key_unique = models.Constraint(
        'unique(idempotency_key)',
        'Duplicate message log idempotency key.',
    )

    @api.depends('message')
    def _compute_message_preview(self):
        for log in self:
            text = (log.message or '').replace('\n', ' ')
            log.message_preview = text[:120] + ('…' if len(text) > 120 else '')

    @api.depends('delivery_state')
    def _compute_status(self):
        for log in self:
            log.status = _LEGACY_STATUS_MAP.get(log.delivery_state, 'pending')

    @api.model
    def _extract_api_message_id(self, api_response):
        if isinstance(api_response, dict):
            return (
                api_response.get('provider_message_id')
                or api_response.get('idMessage')
                or api_response.get('messageId')
                or api_response.get('id')
            )
        return False

    @api.model
    def get_dashboard_stats(self, domain=None):
        domain = domain or []
        Log = self.search(domain)
        sent = len(Log.filtered(lambda l: l.delivery_state in ('sent', 'delivered')))
        failed = len(Log.filtered(lambda l: l.delivery_state == 'failed'))
        skipped = len(Log.filtered(lambda l: l.delivery_state == 'skipped'))
        total = sent + failed + skipped
        success_rate = (sent / total * 100.0) if total else 0.0
        return {
            'total_sent': sent,
            'total_failed': failed,
            'total_skipped': skipped,
            'total_processed': total,
            'success_rate': round(success_rate, 2),
        }

    @api.model
    def create_log(self, **kwargs):
        """Create a delivery log entry. Accepts legacy ``status`` or ``delivery_state``."""
        start_time = kwargs.pop('_start_time', None)
        delivery_state = kwargs.pop('delivery_state', None)
        status = kwargs.pop('status', None)
        if delivery_state:
            pass
        elif status:
            reverse = {v: k for k, v in _LEGACY_STATUS_MAP.items()}
            delivery_state = reverse.get(status, 'failed' if status == 'failed' else 'sent')
        else:
            delivery_state = 'queued'

        recipient = kwargs.get('recipient', '')
        recipient_number = kwargs.get('recipient_number') or recipient
        message = kwargs.get('message', '')
        api_response = kwargs.get('api_response')
        if api_response and not isinstance(api_response, str):
            try:
                api_response = json.dumps(api_response, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                api_response = str(api_response)

        api_message_id = kwargs.get('api_message_id')
        if not api_message_id and isinstance(kwargs.get('api_response'), dict):
            api_message_id = self._extract_api_message_id(kwargs['api_response'])
        elif not api_message_id and api_response:
            try:
                api_message_id = self._extract_api_message_id(json.loads(api_response))
            except (ValueError, TypeError):
                pass

        failure_reason = kwargs.get('failure_reason') or kwargs.get('error_message')
        delivery_state_val = delivery_state
        failed_at = kwargs.get('failed_at')
        if delivery_state_val in ('failed', 'skipped') and not failed_at:
            failed_at = fields.Datetime.now()

        api_response_body = kwargs.get('api_response_body')
        if not api_response_body and api_response and delivery_state_val == 'failed':
            api_response_body = api_response

        duration = kwargs.get('processing_duration')
        if start_time and duration is None:
            duration = time.monotonic() - start_time

        vals = {
            'recipient': recipient,
            'recipient_number': recipient_number,
            'message': message,
            'delivery_state': delivery_state,
            'related_model': kwargs.get('related_model'),
            'related_record_id': kwargs.get('related_record_id') or 0,
            'partner_id': kwargs.get('partner_id'),
            'campaign_id': kwargs.get('campaign_id'),
            'execution_id': kwargs.get('execution_id'),
            'outbound_intent_at': kwargs.get('outbound_intent_at'),
            'attachment_info': kwargs.get('attachment_info'),
            'attachment_count': kwargs.get('attachment_count', 0),
            'failure_reason': failure_reason,
            'error_message': kwargs.get('error_message') or failure_reason,
            'exception_type': kwargs.get('exception_type'),
            'traceback_summary': kwargs.get('traceback_summary'),
            'api_response': api_response,
            'api_response_body': api_response_body,
            'failed_at': failed_at,
            'retryable': kwargs.get('retryable', delivery_state_val in ('failed', 'skipped')),
            'api_message_id': api_message_id,
            'idempotency_key': kwargs.get('idempotency_key'),
            'processing_duration': duration,
            'product_ids': kwargs.get('product_ids'),
        }
        idem_key = vals.get('idempotency_key')
        if idem_key:
            existing = self.search([('idempotency_key', '=', idem_key)], limit=1)
            if existing:
                return existing
        try:
            log = self.create(vals)
        except IntegrityError:
            if not idem_key:
                raise
            log = self.search([('idempotency_key', '=', idem_key)], limit=1)
            if not log:
                raise
        _logger.debug(
            'Message log %s: state=%s partner=%s campaign=%s duration=%.3fs',
            log.id,
            delivery_state,
            log.partner_id.id,
            log.campaign_id.id,
            duration or 0,
        )
        return log

    def commit_outbound_intent(self):
        """Persist queued/sending intent and flush before irreversible provider I/O."""
        self.ensure_one()
        now = fields.Datetime.now()
        vals = {'outbound_intent_at': now}
        if self.delivery_state == 'queued':
            vals['delivery_state'] = 'sending'
        self.write(vals)
        self.flush_recordset(['delivery_state', 'outbound_intent_at', 'execution_id', 'idempotency_key'])
        return True

    def action_open_product_selection(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('WhatsApp Product Selection'),
            'res_model': 'whatsapp.product.selection.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': self.partner_id.id,
                'default_campaign_id': self.campaign_id.id,
                'default_log_id': self.id,
            },
        }
