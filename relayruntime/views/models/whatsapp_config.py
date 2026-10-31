# -*- coding: utf-8 -*-

import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from odoo.addons.relayruntime.constants import (
    PROVIDER_SELECTION_LABELS,
    PROVIDER_STATUS_SELECTION,
)

_logger = logging.getLogger(__name__)


def _provider_registry():
    """Lazy import to keep model registry init independent of provider adapters."""
    from odoo.addons.relayruntime.services.providers.provider_registry import ProviderRegistry
    return ProviderRegistry


def _whatsapp_service():
    from odoo.addons.relayruntime.services.whatsapp_service import WhatsAppService
    return WhatsAppService


def _default_if_unset_float(value, default):
    """Apply a default only when a Float is unset (None/False), not when it is 0.0."""
    if value is None or value is False:
        return default
    return value


class WhatsAppConfig(models.Model):
    _name = 'whatsapp.config'
    _description = 'WhatsApp Configuration'
    _order = 'id desc'

    name = fields.Char(
        string='Name',
        required=True,
        default='WhatsApp Configuration',
    )
    active = fields.Boolean(string='Active', default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
    )

    # Provider identity
    provider_type = fields.Selection(
        selection=PROVIDER_SELECTION_LABELS,
        string='Provider Type',
        required=True,
        default='green_api',
        index=True,
    )
    provider_name = fields.Char(
        string='Provider Name',
        compute='_compute_provider_meta',
        store=True,
    )
    provider_version = fields.Char(
        string='Provider Version',
        compute='_compute_provider_meta',
        store=True,
    )
    provider_capabilities_json = fields.Text(
        string='Capabilities (JSON)',
        compute='_compute_provider_meta',
        store=True,
    )
    provider_implemented = fields.Boolean(
        string='Provider Implemented',
        compute='_compute_provider_implemented',
    )
    provider_debug_info = fields.Text(
        string='Provider Debug Info',
        compute='_compute_provider_debug_info',
    )
    is_test_mode = fields.Boolean(
        string='Test Mode',
        compute='_compute_is_test_mode',
        store=True,
    )
    test_mode_alert_title = fields.Char(
        compute='_compute_test_mode_display_labels',
        string='Test Mode Alert Title',
    )
    test_mode_alert_body = fields.Char(
        compute='_compute_test_mode_display_labels',
        string='Test Mode Alert Body',
    )

    # Mock provider simulation (provider_type == mock_provider)
    simulate_success_rate = fields.Float(
        string='Success Rate %',
        default=85.0,
        help='Random outcome weight for successful sends (0–100).',
    )
    simulate_failure_rate = fields.Float(
        string='Failure Rate %',
        default=5.0,
        help='Random outcome weight for generic API failures.',
    )
    simulate_timeout_rate = fields.Float(
        string='Timeout Rate %',
        default=3.0,
        help='Random outcome weight for simulated timeouts.',
    )
    simulate_rate_limit_rate = fields.Float(
        string='Rate Limit Rate %',
        default=2.0,
        help='Random outcome weight for simulated rate limits.',
    )
    simulate_attachment_failure_rate = fields.Float(
        string='Attachment Failure Rate %',
        default=5.0,
        help='Extra failure chance on media sends only (0–100).',
    )
    simulated_latency_ms = fields.Float(
        string='Simulated Latency (ms)',
        default=50.0,
        help='Pause before each simulated API call (stress-test delays).',
    )
    mock_force_auth_failure = fields.Boolean(
        string='Force Auth Failure on Test',
        help='Connection test always fails with authentication error.',
    )
    mock_force_disconnect = fields.Boolean(
        string='Force Disconnect on Test',
        help='Connection test always fails with disconnect error.',
    )

    # Generic credentials
    api_url = fields.Char(
        string='API URL',
        help='Base URL of your WhatsApp API provider.',
    )
    access_token = fields.Char(
        string='Access Token',
        groups='relayruntime.group_whatsapp_manager',
    )

    # Provider-specific optional fields
    instance_id = fields.Char(string='Instance ID', help='Green API instance id.')
    phone_number_id = fields.Char(string='Phone Number ID', help='Meta Cloud phone number id.')
    business_account_id = fields.Char(string='Business Account ID', help='Meta / business WABA id.')
    webhook_secret = fields.Char(
        string='Webhook Secret',
        groups='relayruntime.group_whatsapp_manager',
        help='Secret for webhook signature verification.',
    )
    api_version = fields.Char(
        string='API Version',
        default='v1',
        help='Provider API version (e.g. v18.0 for Meta).',
    )

    # Future multi-provider / failover (architecture only)
    fallback_config_id = fields.Many2one(
        'whatsapp.config',
        string='Fallback Provider Config',
        help='Reserved for future failover support. Not active yet.',
    )

    # Provider health
    provider_status = fields.Selection(
        selection=PROVIDER_STATUS_SELECTION,
        string='Provider Status',
        default='disconnected',
        readonly=True,
    )
    last_successful_connection = fields.Datetime(string='Last Successful Connection', readonly=True)
    last_failed_connection = fields.Datetime(string='Last Failed Connection', readonly=True)
    last_error = fields.Text(string='Last Error', readonly=True)
    provider_latency_ms = fields.Float(string='Last Latency (ms)', readonly=True, digits=(16, 2))

    # Safety / anti-spam
    min_delay_seconds = fields.Float(string='Min Delay (seconds)', default=1.0)
    max_delay_seconds = fields.Float(string='Max Delay (seconds)', default=3.0)
    cooldown_every_messages = fields.Integer(string='Cooldown Every N Messages', default=10)
    cooldown_duration_seconds = fields.Float(string='Cooldown Duration (seconds)', default=30.0)
    daily_send_limit = fields.Integer(string='Daily Send Limit', default=200)
    max_attachments_per_message = fields.Integer(string='Max Attachments per Message', default=3)
    max_attachment_size_mb = fields.Float(string='Max Attachment Size (MB)', default=16.0)

    file_log_enabled = fields.Boolean(string='Dedicated WhatsApp Log File', default=False)
    file_log_path = fields.Char(
        string='Log File Path',
        default=r'C:\Odoo19.0c\logs\whatsapp.log',
    )

    @api.depends('provider_type')
    def _compute_provider_meta(self):
        for record in self:
            try:
                provider = _provider_registry().get_provider_for_test(record, record.env)
                record.provider_name = provider.get_provider_name()
                record.provider_version = provider.provider_version
                record.provider_capabilities_json = json.dumps(
                    provider.get_capability_dict(),
                    indent=2,
                )
            except Exception as exc:
                record.provider_name = record.provider_type or ''
                record.provider_version = ''
                record.provider_capabilities_json = '{}'
                _logger.debug('Provider meta compute failed: %s', exc)

    @api.depends('provider_type')
    def _compute_is_test_mode(self):
        for record in self:
            record.is_test_mode = record.provider_type == 'mock_provider'

    @api.depends('is_test_mode')
    def _compute_test_mode_display_labels(self):
        alert_title = _('Mock Provider active.')
        alert_body = _(
            'No real WhatsApp messages are sent. Use for QA, demos, and stress tests only.'
        )
        for record in self:
            if record.is_test_mode:
                record.test_mode_alert_title = alert_title
                record.test_mode_alert_body = alert_body
            else:
                record.test_mode_alert_title = False
                record.test_mode_alert_body = False

    @api.depends('provider_type')
    def _compute_provider_implemented(self):
        for record in self:
            provider_cls = _provider_registry().get_provider_class(record.provider_type or 'green_api')
            record.provider_implemented = bool(
                provider_cls and getattr(provider_cls, 'is_implemented', False)
            )

    @api.depends('provider_type', 'provider_status', 'provider_implemented', 'provider_version')
    def _compute_provider_debug_info(self):
        for record in self:
            caps = record.provider_capabilities_json or '{}'
            record.provider_debug_info = '\n'.join([
                'type: %s' % (record.provider_type or '-'),
                'implemented: %s' % record.provider_implemented,
                'version: %s' % (record.provider_version or '-'),
                'status: %s' % (record.provider_status or '-'),
                'capabilities:\n%s' % caps,
            ])

    @api.onchange('provider_type')
    def _onchange_provider_type(self):
        if self.provider_type == 'green_api' and not self.api_url:
            self.api_url = 'https://api.green-api.com'
        if self.provider_type == 'mock_provider':
            self.simulate_success_rate = _default_if_unset_float(
                self.simulate_success_rate, 85.0,
            )
            self.simulate_failure_rate = _default_if_unset_float(
                self.simulate_failure_rate, 5.0,
            )
            self.simulate_timeout_rate = _default_if_unset_float(
                self.simulate_timeout_rate, 3.0,
            )
            self.simulate_rate_limit_rate = _default_if_unset_float(
                self.simulate_rate_limit_rate, 2.0,
            )
            self.simulate_attachment_failure_rate = _default_if_unset_float(
                self.simulate_attachment_failure_rate, 5.0,
            )
            self.simulated_latency_ms = _default_if_unset_float(
                self.simulated_latency_ms, 50.0,
            )

    @api.constrains('provider_type')
    def _check_provider_type(self):
        for record in self:
            _provider_registry().validate_provider_type(record.provider_type or 'green_api')

    @api.constrains('provider_type', 'api_url', 'access_token', 'instance_id')
    def _check_provider_configuration(self):
        for record in self:
            if not record.active:
                continue
            if not _provider_registry().is_implemented(record.provider_type):
                continue
            try:
                _provider_registry().get_provider(record, record.env).validate_configuration()
            except Exception as exc:
                raise ValidationError(
                    _('Invalid WhatsApp provider configuration: %s') % exc
                ) from exc

    @api.constrains('active')
    def _check_single_active(self):
        for record in self.filtered('active'):
            domain = [('active', '=', True), ('id', '!=', record.id)]
            if record.company_id:
                domain.append(('company_id', '=', record.company_id.id))
            if self.search_count(domain):
                raise ValidationError(
                    _('Only one active WhatsApp configuration is allowed per company.')
                )

    @api.constrains('min_delay_seconds', 'max_delay_seconds')
    def _check_delay_range(self):
        for record in self:
            if record.min_delay_seconds < 0 or record.max_delay_seconds < 0:
                raise ValidationError(_('Delay values cannot be negative.'))
            if record.max_delay_seconds < record.min_delay_seconds:
                raise ValidationError(_('Max delay must be greater than or equal to min delay.'))

    @api.constrains(
        'simulate_success_rate',
        'simulate_failure_rate',
        'simulate_timeout_rate',
        'simulate_rate_limit_rate',
        'simulate_attachment_failure_rate',
        'simulated_latency_ms',
    )
    def _check_mock_simulation_rates(self):
        rate_fields = (
            'simulate_success_rate',
            'simulate_failure_rate',
            'simulate_timeout_rate',
            'simulate_rate_limit_rate',
            'simulate_attachment_failure_rate',
        )
        for record in self.filtered(lambda r: r.provider_type == 'mock_provider'):
            for field_name in rate_fields:
                value = getattr(record, field_name)
                if value < 0 or value > 100:
                    field_label = record._fields[field_name].string or field_name
                    raise ValidationError(
                        _('%(field)s must be between 0 and 100.') % {'field': field_label}
                    )
            if record.simulated_latency_ms < 0:
                raise ValidationError(_('Simulated latency cannot be negative.'))

    @api.constrains(
        'cooldown_every_messages',
        'cooldown_duration_seconds',
        'daily_send_limit',
        'max_attachments_per_message',
        'max_attachment_size_mb',
    )
    def _check_safety_values(self):
        for record in self:
            if record.cooldown_every_messages < 0:
                raise ValidationError(_('Cooldown message count cannot be negative.'))
            if record.cooldown_duration_seconds < 0:
                raise ValidationError(_('Cooldown duration cannot be negative.'))
            if record.daily_send_limit < 0:
                raise ValidationError(_('Daily send limit cannot be negative.'))
            if record.max_attachments_per_message < 0:
                raise ValidationError(_('Max attachments cannot be negative.'))
            if record.max_attachment_size_mb <= 0:
                raise ValidationError(_('Max attachment size must be greater than zero.'))

    @api.model
    def get_active_config(self, company=None):
        company = company or self.env.company
        config = self.search([
            ('active', '=', True),
            ('company_id', 'in', [False, company.id]),
        ], limit=1)
        if not config:
            raise UserError(
                _('No active WhatsApp configuration found. Please configure WhatsApp in Settings.')
            )
        return config

    def _update_health_success(self, latency_ms=0.0):
        self.write({
            'provider_status': 'healthy',
            'last_successful_connection': fields.Datetime.now(),
            'provider_latency_ms': latency_ms,
            'last_error': False,
        })

    def _update_health_failure(self, error_message):
        self.write({
            'provider_status': 'degraded' if self.last_successful_connection else 'disconnected',
            'last_failed_connection': fields.Datetime.now(),
            'last_error': error_message,
        })

    def action_test_connection(self):
        self.ensure_one()
        if not _provider_registry().is_implemented(self.provider_type):
            raise UserError(
                _('Provider "%s" is not implemented yet.') % self.provider_type
            )
        service = _whatsapp_service()(self.env, self)
        try:
            result = service.test_connection_with_health()
            state_label = result.state_label or str(result.raw_response)
            self._update_health_success(latency_ms=result.latency_ms)
        except Exception as exc:
            self._update_health_failure(str(exc))
            raise

        _logger.info(
            'WhatsApp connection test OK config=%s provider=%s: %s',
            self.id,
            self.provider_type,
            state_label,
        )
        notif_type = 'success'
        title = _('Connection Successful')
        message = _('Provider %(provider)s is working. State: %(state)s') % {
            'provider': self.provider_name,
            'state': state_label,
        }
        if self.provider_type == 'mock_provider':
            title = _('Mock Provider Ready')
            message = _(
                'TEST MODE — no real WhatsApp messages will be sent. State: %(state)s'
            ) % {'state': state_label}

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notif_type,
                'sticky': self.provider_type == 'mock_provider',
            },
        }

    def action_provider_self_test(self):
        """Run provider validation and connection test."""
        self.ensure_one()
        self.action_test_connection()
        return True
