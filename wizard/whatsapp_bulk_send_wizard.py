# -*- coding: utf-8 -*-

import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class WhatsAppBulkSendWizard(models.TransientModel):
    _name = 'whatsapp.bulk.send.wizard'
    _description = 'Send WhatsApp Bulk Wizard'

    recipient_ids = fields.Many2many(
        'res.partner',
        'whatsapp_bulk_send_wizard_partner_rel',
        'wizard_id',
        'partner_id',
        string='Recipients',
        required=True,
    )
    message = fields.Text(string='Message')
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'whatsapp_bulk_send_wizard_attachment_rel',
        'wizard_id',
        'attachment_id',
        string='Attachments',
        bypass_search_access=True,
        help=(
            'Select multiple files. Each file is sent in order with a short delay. '
            'Product catalog images stay on the Products tab and are never mixed with these uploads.'
        ),
    )
    multi_attachment_count = fields.Integer(
        string='Attachment Count',
        compute='_compute_multi_attachment_count',
        store=False,
    )
    product_ids = fields.Many2many(
        'product.template',
        'whatsapp_bulk_send_wizard_product_rel',
        'wizard_id',
        'product_id',
        string='Products',
    )
    use_product_images = fields.Boolean(
        string='Use Product Images',
        help='Send each product image with caption after the catalog message.',
    )
    include_product_description = fields.Boolean(
        string='Include Product Description',
        help='Add sale description under each product line in the catalog text.',
    )
    product_preview = fields.Text(
        string='Product Preview',
        compute='_compute_product_preview',
    )

    campaign_id = fields.Many2one('whatsapp.bulk.campaign', string='Campaign', readonly=True)
    total_count = fields.Integer(string='Total', readonly=True)
    sent_count = fields.Integer(string='Sent', readonly=True)
    failed_count = fields.Integer(string='Failed', readonly=True)
    skipped_count = fields.Integer(string='Skipped', readonly=True)
    cooldown_count = fields.Integer(string='Cooldowns', readonly=True)
    total_attachments_sent = fields.Integer(string='Attachments Sent', readonly=True)

    progress_percent = fields.Float(string='Progress %', readonly=True, digits=(16, 2))
    current_recipient_name = fields.Char(string='Current Recipient', readonly=True)
    current_product_name = fields.Char(string='Current Product', readonly=True)
    processing_state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('running', 'Running'),
            ('done', 'Done'),
        ],
        string='Processing State',
        default='draft',
        readonly=True,
    )
    state = fields.Selection(
        selection=[('draft', 'Draft'), ('done', 'Done')],
        string='Status',
        default='draft',
    )

    @api.depends('attachment_ids')
    def _compute_multi_attachment_count(self):
        for wizard in self:
            wizard.multi_attachment_count = len(wizard.attachment_ids)

    @api.depends('product_ids', 'include_product_description', 'use_product_images')
    def _compute_product_preview(self):
        from odoo.addons.relayruntime.services.whatsapp_product_service import WhatsAppProductService
        product_service = WhatsAppProductService(self.env)
        for wizard in self:
            if wizard.product_ids:
                wizard.product_preview = product_service.build_catalog_message(
                    wizard.product_ids,
                    include_description=wizard.include_product_description,
                )
            else:
                wizard.product_preview = ''

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        if 'recipient_ids' in fields_list:
            active_ids = self.env.context.get('active_ids', [])
            if active_ids and self.env.context.get('active_model') == 'res.partner':
                defaults['recipient_ids'] = [(6, 0, active_ids)]
        return defaults

    @api.onchange('product_ids', 'include_product_description')
    def _onchange_products(self):
        from odoo.addons.relayruntime.services.whatsapp_product_service import WhatsAppProductService
        if self.product_ids and not self.message:
            self.message = WhatsAppProductService(self.env).build_catalog_message(
                self.product_ids,
                include_description=self.include_product_description,
            )

    def _validate_before_send(self, config):
        from odoo.addons.relayruntime.services.whatsapp_product_service import WhatsAppProductService
        from odoo.addons.relayruntime.services.whatsapp_safety_utils import WhatsAppSafetyValidator
        safety = WhatsAppSafetyValidator(self.env, config)
        if not self.recipient_ids:
            raise UserError(_('Please select at least one contact.'))
        if not self.message and not self.attachment_ids and not self.product_ids:
            raise UserError(_('Enter a message, attach files, or select products.'))

        safety.validate_free_attachments(self.attachment_ids)
        if self.product_ids and self.use_product_images:
            plan = WhatsAppProductService(self.env).prepare_send_plan(
                self.product_ids,
                True,
                include_product_description=self.include_product_description,
            )
            safety.validate_product_image_steps(plan['product_image_steps'])

        planned = safety.count_recipients_with_phone(self.recipient_ids)
        if planned == 0:
            raise ValidationError(_('None of the selected contacts have a valid phone number.'))
        safety.check_daily_limit(planned_sends=planned)

    def action_send(self):
        from odoo.addons.relayruntime.services.whatsapp_bulk_service import WhatsAppBulkSender
        from odoo.addons.relayruntime.services.whatsapp_product_service import WhatsAppProductService
        from odoo.addons.relayruntime.services.whatsapp_safety_utils import WhatsAppSafetyValidator
        self.ensure_one()
        self.env['whatsapp.bulk.execution']._reconcile_stale_executions()
        self.env['whatsapp.bulk.campaign']._reconcile_stale_running_campaigns()
        config = self.env['whatsapp.config'].get_active_config()
        self._validate_before_send(config)

        if self.product_ids:
            WhatsAppProductService(self.env).validate_products(self.product_ids)
            if not self.message:
                self.message = WhatsAppProductService(self.env).build_catalog_message(
                    self.product_ids,
                    include_description=self.include_product_description,
                )

        attachment_label = self._format_attachment_info()
        campaign = self.env['whatsapp.bulk.campaign'].create({
            'name': _('Bulk %s') % fields.Datetime.to_string(fields.Datetime.now()),
            'message': self.message,
            'attachment_info': attachment_label,
            'attachment_ids': [(6, 0, self.attachment_ids.ids)],
            'partner_ids': [(6, 0, self.recipient_ids.ids)],
            'product_ids': [(6, 0, self.product_ids.ids)],
            'use_product_images': self.use_product_images,
            'include_product_description': self.include_product_description,
            'user_id': self.env.uid,
            'company_id': self.env.company.id,
            'state': 'draft',
        })

        self.write({'processing_state': 'running', 'progress_percent': 0.0})

        sender = WhatsAppBulkSender(self.env, config, campaign, wizard=self)
        try:
            stats = sender.send_to_partners(
                self.recipient_ids,
                self.message,
                self.attachment_ids,
                products=self.product_ids,
                use_product_images=self.use_product_images,
                include_product_description=self.include_product_description,
            )
        except ValidationError:
            self.write({'processing_state': 'draft', 'campaign_id': campaign.id})
            raise

        self.write({
            'campaign_id': campaign.id,
            'total_count': stats['total'],
            'sent_count': stats['sent'],
            'failed_count': stats['failed'],
            'skipped_count': stats['skipped'],
            'cooldown_count': stats.get('cooldown_count', 0),
            'total_attachments_sent': stats.get('total_attachments_sent', 0),
            'progress_percent': 100.0,
            'processing_state': 'done',
            'state': 'done',
        })

        return self._action_send_finished_notification(stats)

    def _action_send_finished_notification(self, stats):
        """Return a valid Odoo 19 client notification action (closes wizard after toast)."""
        summary = _(
            'Bulk send finished: %(total)s total, %(sent)s sent, %(failed)s failed, '
            '%(skipped)s skipped, %(cooldowns)s cooldown(s), %(attachments)s attachment(s) sent.'
        ) % {
            'total': stats['total'],
            'sent': stats['sent'],
            'failed': stats['failed'],
            'skipped': stats['skipped'],
            'cooldowns': stats.get('cooldown_count', 0),
            'attachments': stats.get('total_attachments_sent', 0),
        }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('WhatsApp'),
                'message': summary,
                'type': 'success' if not stats.get('failed') else 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _format_attachment_info(self):
        """Human-readable attachment summary for logs and campaigns."""
        self.ensure_one()
        parts = []
        free_names = self.attachment_ids.mapped('name')
        if free_names:
            parts.append(
                _('Files (%(count)s): %(names)s')
                % {'count': len(free_names), 'names': ', '.join(free_names)}
            )
        if self.product_ids:
            product_names = ', '.join(self.product_ids.mapped('name'))
            if self.use_product_images:
                parts.append(_('Product images: %s') % product_names)
            else:
                parts.append(_('Product Catalog: %s') % product_names)
        return ' | '.join(parts)

    def action_view_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Message Logs'),
            'res_model': 'whatsapp.message.log',
            'view_mode': 'list,form,graph,pivot',
            'domain': [('campaign_id', '=', self.campaign_id.id)],
            'context': {'create': False},
        }

    def action_cancel(self):
        return {'type': 'ir.actions.act_window_close'}
