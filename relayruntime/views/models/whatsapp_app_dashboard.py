# -*- coding: utf-8 -*-

from odoo import api, fields, models, _

from odoo.addons.relayruntime.constants import PROVIDER_STATUS_SELECTION


class WhatsAppDashboardActivityLine(models.TransientModel):
    _name = 'whatsapp.dashboard.activity.line'
    _description = 'WhatsApp Dashboard Activity Line'
    _order = 'activity_at desc, id desc'

    dashboard_id = fields.Many2one(
        'whatsapp.app.dashboard',
        string='Dashboard',
        required=True,
        ondelete='cascade',
    )
    activity_type = fields.Selection(
        selection=[
            ('message', 'Message'),
            ('campaign', 'Campaign'),
        ],
        string='Type',
        required=True,
    )
    name = fields.Char(string='Title', required=True)
    detail = fields.Char(string='Detail')
    status_label = fields.Char(string='Status')
    status_code = fields.Char(string='Status Code')
    activity_at = fields.Datetime(string='When', required=True)
    res_model = fields.Char(string='Resource Model')
    res_id = fields.Integer(string='Resource ID')

    def action_open_record(self):
        self.ensure_one()
        if not self.res_model or not self.res_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.res_model,
            'res_id': self.res_id,
            'view_mode': 'form',
            'target': 'current',
        }


class WhatsAppDashboardRunningLine(models.TransientModel):
    _name = 'whatsapp.dashboard.running.line'
    _description = 'WhatsApp Dashboard Running Campaign Line'
    _order = 'progress_percentage desc, id desc'

    dashboard_id = fields.Many2one(
        'whatsapp.app.dashboard',
        string='Dashboard',
        required=True,
        ondelete='cascade',
    )
    campaign_id = fields.Many2one('whatsapp.bulk.campaign', string='Campaign', readonly=True)
    name = fields.Char(string='Campaign', required=True)
    state = fields.Char(string='State')
    state_label = fields.Char(string='State Label')
    progress_percentage = fields.Float(string='Progress %', digits=(16, 2))
    sent_count = fields.Integer(string='Sent')
    failed_count = fields.Integer(string='Failed')
    total_recipients = fields.Integer(string='Total')
    current_step = fields.Char(string='Current Step')

    def action_open_campaign(self):
        self.ensure_one()
        if not self.campaign_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'whatsapp.bulk.campaign',
            'res_id': self.campaign_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_monitor(self):
        return self.env['whatsapp.app.dashboard'].action_quick_campaign_monitor()


class WhatsAppAppDashboard(models.TransientModel):
    _name = 'whatsapp.app.dashboard'
    _description = 'WhatsApp Application Dashboard'

    # Configuration status
    config_id = fields.Many2one('whatsapp.config', string='Configuration', readonly=True)
    config_status = fields.Selection(
        selection=[
            ('configured', 'Configured'),
            ('missing', 'Not Configured'),
        ],
        string='Configuration Status',
        readonly=True,
    )
    config_provider_label = fields.Char(string='Provider', readonly=True)
    config_active = fields.Boolean(string='Active', readonly=True)
    config_is_test_mode = fields.Boolean(string='Test Mode', readonly=True)

    # Provider health
    provider_status = fields.Selection(
        selection=PROVIDER_STATUS_SELECTION,
        string='Provider Status',
        readonly=True,
    )
    provider_name = fields.Char(string='Provider Name', readonly=True)
    provider_last_success = fields.Datetime(string='Last Success', readonly=True)
    provider_last_error = fields.Text(string='Last Error', readonly=True)
    provider_latency_ms = fields.Float(string='Latency (ms)', readonly=True, digits=(16, 2))

    # Campaign & delivery KPIs
    total_campaigns = fields.Integer(string='Total Campaigns', readonly=True)
    active_campaigns = fields.Integer(string='Active Campaigns', readonly=True)
    running_campaign_count = fields.Integer(string='Running Now', readonly=True)
    pending_messages = fields.Integer(string='Pending Messages', readonly=True)
    total_sent = fields.Integer(string='Sent Messages', readonly=True)
    total_failed = fields.Integer(string='Failed Messages', readonly=True)
    delivery_rate = fields.Float(string='Delivery Rate %', readonly=True, digits=(16, 2))
    alert_count = fields.Integer(string='Alerts', readonly=True)

    running_campaign_ids = fields.One2many(
        'whatsapp.dashboard.running.line',
        'dashboard_id',
        string='Running Campaigns',
        readonly=True,
    )
    recent_activity_ids = fields.One2many(
        'whatsapp.dashboard.activity.line',
        'dashboard_id',
        string='Recent Activity',
        readonly=True,
    )

    @api.model
    def _get_active_config(self):
        Config = self.env['whatsapp.config']
        return Config.search([
            ('active', '=', True),
            ('company_id', 'in', [False, self.env.company.id]),
        ], limit=1)

    @api.model
    def _count_pending_messages(self):
        return self.env['whatsapp.message.log'].search_count([
            ('delivery_state', 'in', ['queued', 'sending']),
        ])

    @api.model
    def _compute_alert_count(self, config, total_failed, provider_status):
        alerts = 0
        if not config:
            alerts += 1
        elif provider_status in ('disconnected', 'degraded'):
            alerts += 1
        if total_failed:
            alerts += 1
        return alerts

    @api.model
    def _running_campaign_domain(self):
        """Lineage B: campaign.state is projection; live work also has active_execution_id."""
        return [
            '|',
            ('state', '=', 'running'),
            ('active_execution_id', '!=', False),
        ]

    @api.model
    def _prepare_running_campaign_commands(self):
        Campaign = self.env['whatsapp.bulk.campaign']
        commands = []
        for campaign in Campaign.search(
            self._running_campaign_domain(),
            order='execution_started_at desc, id desc',
        ):
            state_label = dict(
                campaign._fields['state']._description_selection(campaign.env)
            ).get(campaign.state, campaign.state)
            execution = campaign.active_execution_id
            if execution and execution.state == 'running':
                state_label = _('Running (leased)')
            commands.append((0, 0, {
                'campaign_id': campaign.id,
                'name': campaign.name,
                'state': campaign.state,
                'state_label': state_label,
                'progress_percentage': campaign.progress_percentage,
                'sent_count': campaign.sent_count,
                'failed_count': campaign.failed_count,
                'total_recipients': campaign.total_recipients,
                'current_step': campaign.current_step,
            }))
        return commands

    @api.model
    def _prepare_dashboard_values(self):
        config = self._get_active_config()
        Campaign = self.env['whatsapp.bulk.campaign']
        stats = self.env['whatsapp.message.log'].get_dashboard_stats()
        provider_status = config.provider_status if config else 'disconnected'
        total_failed = stats.get('total_failed', 0)
        running_count = Campaign.search_count(self._running_campaign_domain())

        values = {
            'config_id': config.id if config else False,
            'config_status': 'configured' if config else 'missing',
            'config_provider_label': dict(
                config._fields['provider_type']._description_selection(config.env)
            ).get(config.provider_type, config.provider_type) if config else _('Not configured'),
            'config_active': bool(config and config.active),
            'config_is_test_mode': bool(config and config.is_test_mode),
            'provider_status': provider_status,
            'provider_name': config.provider_name if config else _('No provider'),
            'provider_last_success': config.last_successful_connection if config else False,
            'provider_last_error': config.last_error if config else False,
            'provider_latency_ms': config.provider_latency_ms if config else 0.0,
            'total_campaigns': Campaign.search_count([]),
            'active_campaigns': Campaign.search_count([
                '|',
                ('state', 'in', ['draft', 'running']),
                ('active_execution_id', '!=', False),
            ]),
            'running_campaign_count': running_count,
            'pending_messages': self._count_pending_messages(),
            'total_sent': stats.get('total_sent', 0),
            'total_failed': total_failed,
            'delivery_rate': stats.get('success_rate', 0.0),
            'alert_count': self._compute_alert_count(config, total_failed, provider_status),
        }
        return values

    @api.model
    def _prepare_recent_activity_commands(self):
        commands = []
        Log = self.env['whatsapp.message.log']
        Campaign = self.env['whatsapp.bulk.campaign']

        for log in Log.search([], limit=8, order='sent_at desc, id desc'):
            state_label = dict(
                log._fields['delivery_state']._description_selection(log.env)
            ).get(log.delivery_state, log.delivery_state)
            commands.append((0, 0, {
                'activity_type': 'message',
                'name': log.recipient_number or log.recipient or _('Message'),
                'detail': log.message_preview or (log.message or '')[:80],
                'status_label': state_label,
                'status_code': log.delivery_state or '',
                'activity_at': log.sent_at or fields.Datetime.now(),
                'res_model': 'whatsapp.message.log',
                'res_id': log.id,
            }))

        for campaign in Campaign.search([], limit=5, order='create_date desc, id desc'):
            state_label = dict(
                campaign._fields['state']._description_selection(campaign.env)
            ).get(campaign.state, campaign.state)
            commands.append((0, 0, {
                'activity_type': 'campaign',
                'name': campaign.name,
                'detail': _('%s recipients · %s sent · %s failed') % (
                    campaign.total_count,
                    campaign.sent_count,
                    campaign.failed_count,
                ),
                'status_label': state_label,
                'status_code': campaign.state or '',
                'activity_at': campaign.execution_started_at or campaign.create_date,
                'res_model': 'whatsapp.bulk.campaign',
                'res_id': campaign.id,
            }))

        commands.sort(key=lambda cmd: cmd[2]['activity_at'], reverse=True)
        return commands[:12]

    @api.model
    def action_open_dashboard(self):
        values = self._prepare_dashboard_values()
        values['recent_activity_ids'] = self._prepare_recent_activity_commands()
        values['running_campaign_ids'] = self._prepare_running_campaign_commands()
        dashboard = self.create(values)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Command Center'),
            'res_model': 'whatsapp.app.dashboard',
            'res_id': dashboard.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _action_ref(self, xml_id):
        action = self.env.ref(xml_id, raise_if_not_found=False)
        if not action:
            return False
        result = action.read()[0]
        return result

    def action_refresh_dashboard(self):
        return self.env['whatsapp.app.dashboard'].action_open_dashboard()

    def action_tile_command_center(self):
        return self.action_refresh_dashboard()

    def action_tile_campaigns(self):
        return self._action_ref('relayruntime.action_whatsapp_bulk_campaign')

    def action_tile_bulk_send(self):
        return self._action_ref('relayruntime.action_whatsapp_new_bulk_send')

    def action_tile_contacts(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Contacts & Lists'),
            'res_model': 'res.partner',
            'view_mode': 'list,form',
            'domain': ['|', ('mobile', '!=', False), ('phone', '!=', False)],
            'context': {'create': False},
        }

    def action_tile_delivery_logs(self):
        return self._action_ref('relayruntime.action_whatsapp_message_log')

    def action_tile_live_monitor(self):
        return self._action_ref('relayruntime.action_whatsapp_campaign_monitor')

    def action_tile_runtime_settings(self):
        return self.action_open_configuration()

    def action_lifecycle_contacts(self):
        return self.action_tile_contacts()

    def action_lifecycle_campaign(self):
        return self.action_tile_campaigns()

    def action_lifecycle_send(self):
        return self.action_tile_bulk_send()

    def action_lifecycle_delivery(self):
        return self.action_open_delivery_dashboard()

    def action_lifecycle_monitor(self):
        return self.action_tile_live_monitor()

    def action_lifecycle_analytics(self):
        action = self._action_ref('relayruntime.action_whatsapp_message_log')
        if action:
            action['view_mode'] = 'graph,pivot,list,form'
        return action

    def action_open_configuration(self):
        self.ensure_one()
        if self.config_id:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Runtime & Settings'),
                'res_model': 'whatsapp.config',
                'res_id': self.config_id.id,
                'view_mode': 'form',
                'target': 'current',
            }
        return self._action_ref('relayruntime.action_whatsapp_config')

    def action_open_campaigns(self):
        return self._action_ref('relayruntime.action_whatsapp_bulk_campaign')

    def action_open_active_campaigns(self):
        action = self._action_ref('relayruntime.action_whatsapp_bulk_campaign')
        if action:
            action['domain'] = [
                '|',
                ('state', 'in', ['draft', 'running']),
                ('active_execution_id', '!=', False),
            ]
        return action

    def action_open_sent_logs(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sent Messages'),
            'res_model': 'whatsapp.message.log',
            'view_mode': 'list,form,graph,pivot',
            'domain': [('delivery_state', 'in', ['sent', 'delivered'])],
            'context': {'create': False},
        }

    def action_open_failed_logs(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Failed Messages'),
            'res_model': 'whatsapp.message.log',
            'view_mode': 'list,form,graph,pivot',
            'domain': [('delivery_state', '=', 'failed')],
            'context': {'create': False},
        }

    def action_open_pending_logs(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pending Messages'),
            'res_model': 'whatsapp.message.log',
            'view_mode': 'list,form',
            'domain': [('delivery_state', 'in', ['queued', 'sending'])],
            'context': {'create': False, 'search_default_filter_pending': 1},
        }

    def action_open_delivery_dashboard(self):
        return self.env['whatsapp.delivery.dashboard'].action_open_dashboard()

    def action_quick_new_campaign(self):
        return self._action_ref('relayruntime.action_whatsapp_new_bulk_send')

    def action_quick_send_message(self):
        return self._action_ref('relayruntime.action_whatsapp_send_message')

    def action_quick_message_logs(self):
        return self._action_ref('relayruntime.action_whatsapp_message_log')

    def action_quick_campaign_monitor(self):
        return self._action_ref('relayruntime.action_whatsapp_campaign_monitor')

    def action_quick_delivery_dashboard(self):
        return self.action_open_delivery_dashboard()

    def action_quick_settings(self):
        return self._action_ref('relayruntime.action_whatsapp_config')
