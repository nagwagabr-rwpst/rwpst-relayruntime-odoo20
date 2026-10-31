# -*- coding: utf-8 -*-
# Runtime boundary: execution-attempt authority — future extraction candidate for runtime/execution/.
# This model is the current runtime truth until core is moved out of the Odoo addon.

import uuid
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from odoo.addons.relayruntime.constants import (
    EXECUTION_HEARTBEAT_EVERY_N_RECIPIENTS,
    EXECUTION_HEARTBEAT_MIN_INTERVAL_SECONDS,
    EXECUTION_LEASE_MINUTES,
    EXECUTION_STALE_MINUTES,
)
from odoo.addons.relayruntime.services.logger import campaign_logger

EXECUTION_STATE_SELECTION = [
    ('pending', 'Pending'),
    ('running', 'Running'),
    ('completed', 'Completed'),
    ('completed_with_errors', 'Completed with Errors'),
    ('stopped', 'Stopped'),
    ('failed', 'Failed'),
    ('reconciled', 'Reconciled'),
]

ATTEMPT_KIND_SELECTION = [
    ('initial', 'Initial'),
    ('retry', 'Retry'),
]


class WhatsAppBulkExecution(models.Model):
    _name = 'whatsapp.bulk.execution'
    _description = 'WhatsApp Bulk Execution Attempt'
    _order = 'id desc'

    name = fields.Char(string='Reference', required=True, index=True, readonly=True)
    execution_uuid = fields.Char(
        string='Execution UUID',
        required=True,
        readonly=True,
        index=True,
        copy=False,
        default=lambda self: str(uuid.uuid4()),
    )
    campaign_id = fields.Many2one(
        'whatsapp.bulk.campaign',
        string='Campaign',
        required=True,
        ondelete='cascade',
        index=True,
        readonly=True,
    )
    parent_execution_id = fields.Many2one(
        'whatsapp.bulk.execution',
        string='Parent Execution',
        readonly=True,
        ondelete='set null',
        index=True,
        help='Previous execution this retry attempt continues from.',
    )
    parent_campaign_id = fields.Many2one(
        related='campaign_id.parent_campaign_id',
        store=True,
        readonly=True,
    )
    attempt_kind = fields.Selection(
        selection=ATTEMPT_KIND_SELECTION,
        string='Attempt Kind',
        required=True,
        default='initial',
        readonly=True,
        index=True,
    )
    retry_fingerprint = fields.Char(
        string='Retry Fingerprint',
        readonly=True,
        index=True,
        copy=False,
    )
    state = fields.Selection(
        selection=EXECUTION_STATE_SELECTION,
        string='State',
        default='pending',
        required=True,
        readonly=True,
        index=True,
    )
    total_count = fields.Integer(string='Total Recipients', readonly=True)
    sent_count = fields.Integer(string='Sent', readonly=True)
    failed_count = fields.Integer(string='Failed', readonly=True)
    skipped_count = fields.Integer(string='Skipped', readonly=True)
    processed_count = fields.Integer(string='Processed', readonly=True)
    remaining_count = fields.Integer(string='Remaining', readonly=True)
    progress_percent = fields.Float(string='Progress %', readonly=True, digits=(16, 2))
    cooldown_count = fields.Integer(string='Cooldowns', readonly=True)
    total_attachments_sent = fields.Integer(string='Attachments Sent', readonly=True)

    executor_uid = fields.Many2one(
        'res.users',
        string='Executor',
        readonly=True,
        index=True,
    )
    lease_token = fields.Char(string='Lease Token', readonly=True, index=True, copy=False)
    lease_expires_at = fields.Datetime(string='Lease Expires', readonly=True, index=True)
    heartbeat_at = fields.Datetime(string='Last Heartbeat', readonly=True, index=True)
    started_at = fields.Datetime(string='Started At', readonly=True, index=True)
    finished_at = fields.Datetime(string='Finished At', readonly=True)
    last_recipient_index = fields.Integer(string='Last Recipient Index', readonly=True)

    company_id = fields.Many2one(
        related='campaign_id.company_id',
        store=True,
        readonly=True,
    )
    log_ids = fields.One2many(
        'whatsapp.message.log',
        'execution_id',
        string='Message Logs',
        readonly=True,
    )
    log_count = fields.Integer(compute='_compute_log_count')

    _whatsapp_bulk_execution_uuid_unique = models.Constraint(
        'unique(execution_uuid)',
        'Execution UUID must be unique.',
    )

    @api.depends('log_ids')
    def _compute_log_count(self):
        for execution in self:
            execution.log_count = len(execution.log_ids)

    @api.model
    def _lease_duration(self):
        return timedelta(minutes=EXECUTION_LEASE_MINUTES)

    @api.model
    def _stale_cutoff(self, stale_minutes=None):
        minutes = stale_minutes if stale_minutes is not None else EXECUTION_STALE_MINUTES
        return fields.Datetime.now() - timedelta(minutes=minutes)

    @api.model
    def _resolve_parent_execution(self, campaign):
        """Canonical retry lineage: latest execution on parent campaign."""
        if not campaign.parent_campaign_id:
            return self.browse()
        return self.search(
            [('campaign_id', '=', campaign.parent_campaign_id.id)],
            order='id desc',
            limit=1,
        )

    @api.model
    def begin_campaign_execution(self, campaign, total, attempt_kind=None):
        """Create attempt, acquire lease, and block concurrent live executions."""
        self._reconcile_stale_executions()
        campaign._lock_for_execution()
        self._assert_no_active_lease(campaign)

        if attempt_kind is None:
            attempt_kind = 'retry' if campaign.parent_campaign_id else 'initial'

        parent_execution = self._resolve_parent_execution(campaign)
        now = fields.Datetime.now()
        lease_token = str(uuid.uuid4())
        execution_uuid = str(uuid.uuid4())

        attempt = self.create({
            'name': _('Exec %(campaign)s #%(n)s') % {
                'campaign': campaign.name,
                'n': len(campaign.execution_ids) + 1,
            },
            'execution_uuid': execution_uuid,
            'campaign_id': campaign.id,
            'parent_execution_id': parent_execution.id if parent_execution else False,
            'attempt_kind': attempt_kind,
            'retry_fingerprint': campaign.retry_fingerprint or False,
            'state': 'running',
            'total_count': total,
            'processed_count': 0,
            'remaining_count': total,
            'progress_percent': 0.0,
            'executor_uid': self.env.uid,
            'lease_token': lease_token,
            'lease_expires_at': now + self._lease_duration(),
            'heartbeat_at': now,
            'started_at': now,
            'last_recipient_index': 0,
        })
        campaign._project_running_from_execution(attempt, total)
        campaign_logger.info(
            'Execution %s started for campaign %s (uuid=%s kind=%s parent_exec=%s)',
            attempt.id,
            campaign.id,
            execution_uuid,
            attempt_kind,
            parent_execution.id if parent_execution else '-',
        )
        return attempt

    @api.model
    def _assert_no_active_lease(self, campaign):
        now = fields.Datetime.now()
        blocking = self.search([
            ('campaign_id', '=', campaign.id),
            ('state', '=', 'running'),
            ('lease_expires_at', '>', now),
        ], limit=1)
        if blocking:
            raise UserError(_(
                'Campaign "%(name)s" already has an active execution (attempt %(attempt)s). '
                'Wait for it to finish or reconcile stale runs before starting again.'
            ) % {
                'name': campaign.name,
                'attempt': blocking.name,
            })

    def _extend_lease(self):
        self.ensure_one()
        now = fields.Datetime.now()
        self.write({
            'lease_expires_at': now + self._lease_duration(),
            'heartbeat_at': now,
        })

    def heartbeat_if_due(self, recipient_index, force=False):
        """Lightweight liveness refresh; throttled by recipient count and time."""
        self.ensure_one()
        if self.state != 'running':
            return False
        now = fields.Datetime.now()
        if not force:
            every_n = EXECUTION_HEARTBEAT_EVERY_N_RECIPIENTS
            if recipient_index and recipient_index % every_n != 0:
                last_hb = self.heartbeat_at
                if last_hb:
                    elapsed = (now - last_hb).total_seconds()
                    if elapsed < EXECUTION_HEARTBEAT_MIN_INTERVAL_SECONDS:
                        return False
        vals = {
            'heartbeat_at': now,
            'lease_expires_at': now + self._lease_duration(),
            'last_recipient_index': recipient_index or self.last_recipient_index,
        }
        self.write(vals)
        self.campaign_id._touch_execution_liveness(self, recipient_index)
        return True

    def update_progress(
        self,
        stats,
        recipient_index=0,
        partner=None,
        phone=None,
        product=None,
        step=None,
        throttle=False,
    ):
        """Update attempt counters; campaign UI projection is throttled separately."""
        self.ensure_one()
        total = stats.get('total', self.total_count)
        sent = stats.get('sent', 0)
        failed = stats.get('failed', 0)
        skipped = stats.get('skipped', 0)
        processed = min(sent + failed + skipped, total)
        remaining = max(total - processed, 0)
        percent = (processed / total * 100.0) if total else 0.0
        self.write({
            'sent_count': sent,
            'failed_count': failed,
            'skipped_count': skipped,
            'processed_count': processed,
            'remaining_count': remaining,
            'progress_percent': percent,
            'cooldown_count': stats.get('cooldown_count', 0),
            'total_attachments_sent': stats.get('total_attachments_sent', 0),
            'last_recipient_index': recipient_index,
        })
        if not throttle:
            self.campaign_id._project_progress_from_execution(
                self,
                partner=partner,
                phone=phone,
                product=product,
                step=step,
                throttle=False,
            )

    def finish(self, stats, stopped=False, failed=False):
        """Terminalize attempt and project outcome onto campaign aggregate."""
        self.ensure_one()
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
            'state': state,
            'sent_count': sent,
            'failed_count': failed_count,
            'skipped_count': skipped,
            'cooldown_count': stats.get('cooldown_count', 0),
            'total_attachments_sent': stats.get('total_attachments_sent', 0),
            'total_count': total,
            'processed_count': processed,
            'remaining_count': remaining,
            'progress_percent': progress,
            'finished_at': now,
            'lease_expires_at': False,
            'lease_token': False,
            'heartbeat_at': now,
        })
        self.campaign_id._project_finished_from_execution(self, stats, stopped=stopped, failed=failed)
        campaign_logger.info(
            'Execution %s finished: state=%s sent=%s failed=%s skipped=%s',
            self.id,
            state,
            sent,
            failed_count,
            skipped,
        )

    @api.model
    def _reconcile_stale_executions(self, stale_minutes=None):
        """Mark abandoned running attempts failed/reconciled using heartbeat."""
        cutoff = self._stale_cutoff(stale_minutes)
        stale = self.search([
            ('state', '=', 'running'),
            '|',
            ('heartbeat_at', '<=', cutoff),
            '&',
            ('heartbeat_at', '=', False),
            ('started_at', '<=', cutoff),
        ])
        if not stale:
            return self.browse()
        now = fields.Datetime.now()
        for attempt in stale:
            sent = attempt.sent_count
            failed = attempt.failed_count
            skipped = attempt.skipped_count
            total = attempt.total_count or (sent + failed + skipped)
            processed = min(sent + failed + skipped, total)
            remaining = max(total - processed, 0)
            progress = (processed / total * 100.0) if total else 0.0
            attempt.write({
                'state': 'reconciled',
                'finished_at': now,
                'lease_expires_at': False,
                'lease_token': False,
                'processed_count': processed,
                'remaining_count': remaining,
                'progress_percent': progress,
                'heartbeat_at': now,
            })
            attempt.campaign_id._project_reconciled_from_execution(attempt)
            campaign_logger.warning(
                'Reconciled stale execution %s for campaign %s',
                attempt.id,
                attempt.campaign_id.id,
            )
        return stale
