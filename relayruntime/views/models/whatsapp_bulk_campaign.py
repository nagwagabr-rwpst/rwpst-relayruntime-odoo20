# -*- coding: utf-8 -*-

import hashlib
import uuid
from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from odoo.addons.relayruntime.services.logger import campaign_logger

CAMPAIGN_STATE_SELECTION = [
    ('draft', 'Draft'),
    ('running', 'Running'),
    ('completed', 'Completed'),
    ('completed_with_errors', 'Completed with Errors'),
    ('stopped', 'Stopped'),
    ('failed', 'Failed'),
]

# Legacy processing_state values mapped for backward-compatible views/code
_PROCESSING_STATE_MAP = {
    'draft': 'draft',
    'running': 'running',
    'completed': 'done',
    'completed_with_errors': 'done',
    'stopped': 'cancelled',
    'failed': 'cancelled',
}


class WhatsAppBulkCampaign(models.Model):
    _name = 'whatsapp.bulk.campaign'
    _description = 'WhatsApp Bulk Campaign'
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Reference', required=True, index=True)
    message = fields.Text(string='Message')
    attachment_info = fields.Text()
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'whatsapp_campaign_attachment_rel',
        'campaign_id',
        'attachment_id',
        string='Attachments',
        readonly=True,
        bypass_search_access=True,
        help='User-uploaded files for this campaign (not product catalog images).',
    )
    attachment_count = fields.Integer(
        string='Attachment Count',
        compute='_compute_attachment_count',
        store=True,
    )
    product_ids = fields.Many2many(
        'product.template',
        'whatsapp_campaign_product_rel',
        'campaign_id',
        'product_id',
        string='Products',
        readonly=True,
    )
    partner_ids = fields.Many2many(
        'res.partner',
        'whatsapp_campaign_partner_rel',
        'campaign_id',
        'partner_id',
        string='Recipients',
        readonly=True,
    )
    use_product_images = fields.Boolean(string='Used Product Images', readonly=True)
    include_product_description = fields.Boolean(string='Included Descriptions', readonly=True)

    total_count = fields.Integer(string='Total', readonly=True)
    total_recipients = fields.Integer(string='Total Recipients', related='total_count', store=True)
    sent_count = fields.Integer(string='Sent', readonly=True)
    total_success = fields.Integer(related='sent_count', store=True)
    failed_count = fields.Integer(string='Failed', readonly=True)
    total_failures = fields.Integer(related='failed_count', store=True)
    skipped_count = fields.Integer(string='Skipped', readonly=True)
    total_skipped = fields.Integer(string='Total Skipped', related='skipped_count', store=True)
    cooldown_count = fields.Integer(string='Cooldowns', readonly=True)
    total_attachments_sent = fields.Integer(string='Attachments Sent', readonly=True)
    total_attachments = fields.Integer(
        string='Total Attachments',
        related='total_attachments_sent',
        store=True,
    )

    success_rate = fields.Float(
        string='Success Rate %',
        compute='_compute_success_rate',
        store=True,
        digits=(16, 2),
    )

    started_at = fields.Datetime(string='Started At', readonly=True, index=True)
    finished_at = fields.Datetime(string='Finished At', readonly=True)
    execution_started_at = fields.Datetime(
        string='Execution Started',
        readonly=True,
        index=True,
        help='When the bulk sender started processing recipients.',
    )
    execution_finished_at = fields.Datetime(
        string='Execution Finished',
        readonly=True,
        help='When the bulk sender finished or was interrupted.',
    )
    duration_seconds = fields.Float(
        string='Duration (seconds)',
        compute='_compute_duration',
        store=True,
        digits=(16, 2),
    )
    running_duration_seconds = fields.Float(
        string='Running Duration (s)',
        compute='_compute_running_duration',
        digits=(16, 2),
    )

    progress_percent = fields.Float(string='Progress %', readonly=True, digits=(16, 2))
    progress_percentage = fields.Float(
        string='Progress',
        related='progress_percent',
        readonly=True,
    )
    processed_count = fields.Integer(string='Processed', readonly=True)
    remaining_count = fields.Integer(string='Remaining', readonly=True)
    current_step = fields.Char(string='Current Step', readonly=True)

    # Kanban / monitor display strings (Phase 2 — exported via Python _(), not hardcoded QWeb).
    monitor_elapsed_suffix = fields.Char(
        compute='_compute_kanban_display_labels',
        string='Elapsed',
    )
    monitor_progress_summary = fields.Char(
        compute='_compute_kanban_display_labels',
        string='Progress Summary',
    )
    monitor_success_rate_text = fields.Char(
        compute='_compute_kanban_display_labels',
        string='Success Rate',
    )
    kanban_label_sent = fields.Char(compute='_compute_kanban_display_labels')
    kanban_label_failed = fields.Char(compute='_compute_kanban_display_labels')
    kanban_label_skipped = fields.Char(compute='_compute_kanban_display_labels')
    kanban_label_current_recipient = fields.Char(compute='_compute_kanban_display_labels')
    kanban_label_current_product = fields.Char(compute='_compute_kanban_display_labels')

    state = fields.Selection(
        selection=CAMPAIGN_STATE_SELECTION,
        string='Status',
        default='draft',
        readonly=True,
        index=True,
    )
    processing_state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('running', 'Running'),
            ('done', 'Done'),
            ('cancelled', 'Cancelled'),
        ],
        compute='_compute_processing_state',
        store=True,
        readonly=True,
    )

    current_partner_id = fields.Many2one(
        'res.partner',
        string='Current Contact',
        readonly=True,
        help='Deprecated alias; use current_recipient_id.',
    )
    current_recipient_id = fields.Many2one(
        'res.partner',
        string='Current Recipient',
        readonly=True,
    )
    current_recipient_number = fields.Char(string='Current Number', readonly=True)
    current_product_id = fields.Many2one('product.template', string='Current Product', readonly=True)
    last_activity_at = fields.Datetime(string='Last Activity', readonly=True, index=True)
    execution_token = fields.Char(string='Execution Token', readonly=True, index=True)
    execution_lock_expires_at = fields.Datetime(string='Execution Lock Expires', readonly=True, index=True)
    active_execution_id = fields.Many2one(
        'whatsapp.bulk.execution',
        string='Active Execution',
        readonly=True,
        copy=False,
    )
    execution_ids = fields.One2many(
        'whatsapp.bulk.execution',
        'campaign_id',
        string='Execution Attempts',
        readonly=True,
    )
    execution_count = fields.Integer(compute='_compute_execution_count')

    parent_campaign_id = fields.Many2one(
        'whatsapp.bulk.campaign',
        string='Parent Campaign',
        readonly=True,
        ondelete='set null',
    )
    retry_fingerprint = fields.Char(string='Retry Fingerprint', readonly=True, index=True, copy=False)
    retry_campaign_ids = fields.One2many(
        'whatsapp.bulk.campaign',
        'parent_campaign_id',
        string='Retry Campaigns',
        readonly=True,
    )
    retry_count = fields.Integer(compute='_compute_retry_count')

    user_id = fields.Many2one(
        'res.users',
        string='Sent By',
        default=lambda self: self.env.user,
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        readonly=True,
        index=True,
    )
    log_ids = fields.One2many(
        'whatsapp.message.log',
        'campaign_id',
        string='Message Logs',
        readonly=True,
    )
    sale_order_ids = fields.One2many(
        'sale.order',
        'whatsapp_campaign_id',
        string='Sales Orders',
        readonly=True,
    )
    sale_order_count = fields.Integer(compute='_compute_sale_order_count')

    _whatsapp_retry_fingerprint_unique = models.Constraint(
        'unique(parent_campaign_id, retry_fingerprint)',
        'A retry campaign for the same parent and recipient set already exists.',
    )

    @api.depends(
        'processed_count',
        'remaining_count',
        'total_recipients',
        'success_rate',
    )
    def _compute_kanban_display_labels(self):
        # translator: suffix after running duration on campaign monitor kanban
        elapsed_suffix = _('elapsed')
        label_sent = _('Sent')
        label_failed = _('Failed')
        label_skipped = _('Skipped')
        label_current_recipient = _('Current Recipient')
        label_current_product = _('Current Product')
        for campaign in self:
            campaign.monitor_elapsed_suffix = elapsed_suffix
            campaign.kanban_label_sent = label_sent
            campaign.kanban_label_failed = label_failed
            campaign.kanban_label_skipped = label_skipped
            campaign.kanban_label_current_recipient = label_current_recipient
            campaign.kanban_label_current_product = label_current_product
            campaign.monitor_progress_summary = _(
                '%(processed)s / %(total)s processed · %(remaining)s remaining'
            ) % {
                'processed': campaign.processed_count,
                'total': campaign.total_recipients,
                'remaining': campaign.remaining_count,
            }
            # translator: success rate line on campaign kanban cards; %% renders a literal %
            campaign.monitor_success_rate_text = _('Success: %(rate)s%%') % {
                'rate': campaign.success_rate,
            }

    @api.depends('attachment_ids')
    def _compute_attachment_count(self):
        for campaign in self:
            campaign.attachment_count = len(campaign.attachment_ids)

    @api.depends('sent_count', 'failed_count', 'skipped_count')
    def _compute_success_rate(self):
        for campaign in self:
            total = campaign.sent_count + campaign.failed_count + campaign.skipped_count
            campaign.success_rate = (campaign.sent_count / total * 100.0) if total else 0.0

    @api.depends('started_at', 'finished_at', 'execution_started_at', 'execution_finished_at')
    def _compute_duration(self):
        for campaign in self:
            start = campaign.execution_started_at or campaign.started_at
            end = campaign.execution_finished_at or campaign.finished_at
            if start and end:
                campaign.duration_seconds = (end - start).total_seconds()
            else:
                campaign.duration_seconds = 0.0

    @api.depends('state', 'execution_started_at', 'last_activity_at', 'execution_finished_at')
    def _compute_running_duration(self):
        now = fields.Datetime.now()
        for campaign in self:
            start = campaign.execution_started_at or campaign.started_at
            if not start:
                campaign.running_duration_seconds = 0.0
                continue
            if campaign.state == 'running':
                anchor = campaign.last_activity_at or now
                campaign.running_duration_seconds = (anchor - start).total_seconds()
            elif campaign.execution_finished_at:
                campaign.running_duration_seconds = (
                    campaign.execution_finished_at - start
                ).total_seconds()
            elif campaign.finished_at:
                campaign.running_duration_seconds = (campaign.finished_at - start).total_seconds()
            else:
                campaign.running_duration_seconds = 0.0

    @api.depends('state')
    def _compute_processing_state(self):
        for campaign in self:
            campaign.processing_state = _PROCESSING_STATE_MAP.get(campaign.state, 'draft')

    def _compute_sale_order_count(self):
        for campaign in self:
            campaign.sale_order_count = len(campaign.sale_order_ids)

    def _compute_retry_count(self):
        for campaign in self:
            campaign.retry_count = len(campaign.retry_campaign_ids)

    @api.depends('execution_ids')
    def _compute_execution_count(self):
        for campaign in self:
            campaign.execution_count = len(campaign.execution_ids)

    def _lock_for_execution(self):
        """Row lock campaign to serialize concurrent execution starts."""
        self.ensure_one()
        self.env.cr.execute(
            'SELECT id FROM whatsapp_bulk_campaign WHERE id = %s FOR UPDATE',
            (self.id,),
        )

    def _project_running_from_execution(self, execution, total):
        now = fields.Datetime.now()
        self.write({
            'state': 'running',
            'active_execution_id': execution.id,
            'started_at': now,
            'execution_started_at': now,
            'total_count': total,
            'processed_count': 0,
            'remaining_count': total,
            'progress_percent': 0.0,
            'current_step': _('Starting campaign'),
            'last_activity_at': now,
            'execution_token': execution.execution_uuid,
            'execution_lock_expires_at': execution.lease_expires_at,
        })

    def _touch_execution_liveness(self, execution, recipient_index=0):
        """Minimal campaign mirror on heartbeat (no full progress recompute)."""
        self.ensure_one()
        self.write({
            'active_execution_id': execution.id,
            'last_activity_at': execution.heartbeat_at or fields.Datetime.now(),
            'execution_lock_expires_at': execution.lease_expires_at,
            'execution_token': execution.execution_uuid,
        })

    def _project_progress_from_execution(
        self,
        execution,
        partner=None,
        phone=None,
        product=None,
        step=None,
        throttle=False,
    ):
        if throttle:
            return
        self.ensure_one()
        now = fields.Datetime.now()
        self.write({
            'active_execution_id': execution.id,
            'progress_percent': execution.progress_percent,
            'processed_count': execution.processed_count,
            'remaining_count': execution.remaining_count,
            'sent_count': execution.sent_count,
            'failed_count': execution.failed_count,
            'skipped_count': execution.skipped_count,
            'current_recipient_id': partner.id if partner else False,
            'current_partner_id': partner.id if partner else False,
            'current_recipient_number': phone or '',
            'current_product_id': product.id if product else False,
            'current_step': step or '',
            'last_activity_at': now,
            'execution_lock_expires_at': execution.lease_expires_at,
        })

    def _project_finished_from_execution(self, execution, stats, stopped=False, failed=False):
        self._mark_finished(stats, stopped=stopped, failed=failed)
        self.write({
            'active_execution_id': False,
            'execution_token': False,
            'execution_lock_expires_at': False,
        })

    def _project_reconciled_from_execution(self, execution):
        self.ensure_one()
        if self.active_execution_id.id == execution.id:
            self.write({
                'state': 'failed',
                'finished_at': fields.Datetime.now(),
                'execution_finished_at': fields.Datetime.now(),
                'active_execution_id': False,
                'execution_token': False,
                'execution_lock_expires_at': False,
                'current_step': _('Recovered after interrupted execution'),
                'progress_percent': execution.progress_percent,
                'processed_count': execution.processed_count,
                'remaining_count': execution.remaining_count,
                'sent_count': execution.sent_count,
                'failed_count': execution.failed_count,
                'skipped_count': execution.skipped_count,
            })

    def action_open_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Message Logs'),
            'res_model': 'whatsapp.message.log',
            'view_mode': 'list,form,graph,pivot',
            'domain': [('campaign_id', '=', self.id)],
        }

    def action_open_sale_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sales Orders'),
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [('whatsapp_campaign_id', '=', self.id)],
        }

    def action_create_product_selection(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Sale Order from Selection'),
            'res_model': 'whatsapp.product.selection.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_campaign_id': self.id,
                'default_product_ids': [(6, 0, self.product_ids.ids)],
            },
        }

    def action_retry_failed_recipients(self):
        """Create a linked retry campaign and resend failed/skipped recipients only."""
        self.ensure_one()
        self.env['whatsapp.bulk.execution']._reconcile_stale_executions()
        self._reconcile_stale_running_campaigns()
        if self.state == 'running':
            active = self.active_execution_id
            if active and active.lease_expires_at and active.lease_expires_at > fields.Datetime.now():
                raise UserError(_('Cannot retry while the campaign is still running.'))

        failed_logs = self.log_ids.filtered(
            lambda log: log.delivery_state in ('failed', 'skipped') and log.partner_id
        )
        partners = failed_logs.mapped('partner_id')
        if not partners:
            raise UserError(_('No failed or skipped recipients to retry for this campaign.'))

        config = self.env['whatsapp.config'].get_active_config(self.company_id)
        retry_fingerprint = self._build_retry_fingerprint(partners)
        existing_retry = self.search([
            ('parent_campaign_id', '=', self.id),
            ('retry_fingerprint', '=', retry_fingerprint),
        ], limit=1)
        if existing_retry:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Retry Campaign'),
                'res_model': 'whatsapp.bulk.campaign',
                'res_id': existing_retry.id,
                'view_mode': 'form',
                'target': 'current',
            }

        vals = {
            'name': _('Retry: %s') % self.name,
            'message': self.message,
            'attachment_info': self.attachment_info,
            'attachment_ids': [(6, 0, self.attachment_ids.ids)],
            'product_ids': [(6, 0, self.product_ids.ids)],
            'partner_ids': [(6, 0, partners.ids)],
            'use_product_images': self.use_product_images,
            'include_product_description': self.include_product_description,
            'user_id': self.env.uid,
            'company_id': self.company_id.id,
            'parent_campaign_id': self.id,
            'retry_fingerprint': retry_fingerprint,
            'state': 'draft',
        }
        try:
            with self.env.cr.savepoint():
                retry_campaign = self.create(vals)
        except IntegrityError:
            retry_campaign = self.search([
                ('parent_campaign_id', '=', self.id),
                ('retry_fingerprint', '=', retry_fingerprint),
            ], limit=1)
            if not retry_campaign:
                raise

        from odoo.addons.relayruntime.services.whatsapp_bulk_service import WhatsAppBulkSender

        campaign_logger.info(
            'Retry campaign %s created from parent %s (%s recipients)',
            retry_campaign.id,
            self.id,
            len(partners),
        )

        sender = WhatsAppBulkSender(self.env, config, retry_campaign)
        sender.send_to_partners(
            partners,
            self.message,
            self.attachment_ids,
            products=self.product_ids,
            use_product_images=self.use_product_images,
            include_product_description=self.include_product_description,
        )

        return {
            'type': 'ir.actions.act_window',
            'name': _('Retry Campaign'),
            'res_model': 'whatsapp.bulk.campaign',
            'res_id': retry_campaign.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_monitor(self):
        self.ensure_one()
        return self.env.ref('relayruntime.action_whatsapp_campaign_monitor').read()[0]

    def _update_execution_progress(
        self,
        processed,
        total,
        partner=None,
        product=None,
        phone=None,
        step=None,
        commit=False,
    ):
        """Update live execution fields for UI and monitor views."""
        now = fields.Datetime.now()
        remaining = max(total - processed, 0)
        percent = (processed / total * 100.0) if total else 0.0
        vals = {
            'progress_percent': percent,
            'processed_count': processed,
            'remaining_count': remaining,
            'current_recipient_id': partner.id if partner else False,
            'current_partner_id': partner.id if partner else False,
            'current_recipient_number': phone or '',
            'current_product_id': product.id if product else False,
            'current_step': step or '',
            'last_activity_at': now,
        }
        self.write(vals)
        campaign_logger.debug(
            'Campaign %s: %.1f%% (%s/%s) step=%s recipient=%s product=%s',
            self.id,
            percent,
            processed,
            total,
            step or '-',
            partner.display_name if partner else '-',
            product.display_name if product else '-',
        )
        if commit:
            # Do not fragment transactions inside progress updates.
            self.flush()

    def _mark_running(self, total):
        """Deprecated entry point; bulk sender uses execution.begin_campaign_execution."""
        return self.env['whatsapp.bulk.execution'].begin_campaign_execution(self, total)

    def _mark_finished(self, stats, stopped=False, failed=False):
        now = fields.Datetime.now()
        sent = stats.get('sent', 0)
        failed_count = stats.get('failed', 0)
        skipped = stats.get('skipped', 0)
        total = stats.get('total', self.total_count)
        processed = min(sent + failed_count + skipped, total)
        remaining = max(total - processed, 0)
        progress = (processed / total * 100.0) if total else 0.0

        if failed:
            state = 'failed'
        elif stopped or remaining > 0:
            state = 'stopped'
        elif failed_count:
            state = 'completed_with_errors'
        else:
            state = 'completed'

        self.write({
            'total_count': total,
            'sent_count': sent,
            'failed_count': failed_count,
            'skipped_count': skipped,
            'cooldown_count': stats.get('cooldown_count', 0),
            'total_attachments_sent': stats.get('total_attachments_sent', 0),
            'finished_at': now,
            'execution_finished_at': now,
            'progress_percent': progress,
            'processed_count': processed,
            'remaining_count': remaining,
            'state': state,
            'current_recipient_id': False,
            'current_partner_id': False,
            'current_recipient_number': False,
            'current_product_id': False,
            'current_step': _('Finished'),
            'last_activity_at': now,
            'execution_lock_expires_at': False,
        })
        campaign_logger.info(
            'Campaign %s finished: state=%s sent=%s failed=%s skipped=%s',
            self.id,
            state,
            sent,
            failed_count,
            skipped,
        )

    # Backward-compatible alias used by bulk sender
    def _update_progress(self, index, total, partner=None, product=None, state='running'):
        phone = partner._whatsapp_find_phone_number() if partner else ''
        self._update_execution_progress(
            index,
            total,
            partner=partner,
            product=product,
            phone=phone,
            step=_('Sending to recipient'),
        )

    def _build_retry_fingerprint(self, partners):
        payload = '|'.join([
            str(self.id),
            self.message or '',
            ','.join(str(pid) for pid in sorted(self.attachment_ids.ids)),
            ','.join(str(pid) for pid in sorted(self.product_ids.ids)),
            ','.join(str(pid) for pid in sorted(partners.ids)),
        ])
        return hashlib.sha1(payload.encode('utf-8')).hexdigest()

    @api.model
    def _reconcile_stale_running_campaigns(self, stale_minutes=30):
        """Fallback for campaigns stuck running without a live execution lease."""
        Execution = self.env['whatsapp.bulk.execution']
        Execution._reconcile_stale_executions(stale_minutes=stale_minutes)
        cutoff = fields.Datetime.now() - timedelta(minutes=stale_minutes)
        stale = self.search([
            ('state', '=', 'running'),
            ('last_activity_at', '<=', cutoff),
        ])
        if not stale:
            return
        for campaign in stale:
            live = Execution.search([
                ('campaign_id', '=', campaign.id),
                ('state', '=', 'running'),
                ('lease_expires_at', '>', fields.Datetime.now()),
            ], limit=1)
            if live:
                continue
            sent = campaign.sent_count
            failed = campaign.failed_count
            skipped = campaign.skipped_count
            total = campaign.total_count or (sent + failed + skipped)
            processed = min(sent + failed + skipped, total)
            remaining = max(total - processed, 0)
            progress = (processed / total * 100.0) if total else 0.0
            campaign.write({
                'state': 'failed',
                'finished_at': fields.Datetime.now(),
                'execution_finished_at': fields.Datetime.now(),
                'active_execution_id': False,
                'current_step': _('Recovered after interrupted execution'),
                'progress_percent': progress,
                'processed_count': processed,
                'remaining_count': remaining,
                'execution_lock_expires_at': False,
                'execution_token': False,
            })
