# -*- coding: utf-8 -*-

import base64
import logging
import random
import time
from datetime import datetime, time as time_cls

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)

ALLOWED_ATTACHMENT_MIMETYPES = frozenset({
    'image/jpeg',
    'image/jpg',
    'image/png',
    'image/gif',
    'image/webp',
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'video/mp4',
    'audio/mpeg',
    'audio/ogg',
})


class WhatsAppSafetyValidator:
    """Reusable safety checks driven by whatsapp.config."""

    def __init__(self, env, config):
        self.env = env
        self.config = config
        self.log_model = env['whatsapp.message.log']

    # -------------------------------------------------------------------------
    # Configuration helpers
    # -------------------------------------------------------------------------

    def get_random_delay(self):
        min_delay = self.config.min_delay_seconds or 1.0
        max_delay = self.config.max_delay_seconds or 3.0
        if max_delay < min_delay:
            max_delay = min_delay
        delay = random.uniform(min_delay, max_delay)
        _logger.debug(
            'Random inter-recipient delay: %.2fs (range %.2f-%.2f)',
            delay,
            min_delay,
            max_delay,
        )
        return delay

    def get_attachment_delay(self):
        """Short pause between attachments for the same recipient."""
        return random.uniform(0.3, 0.8)

    # -------------------------------------------------------------------------
    # Daily limit
    # -------------------------------------------------------------------------

    def get_daily_sent_count(self):
        """Count successfully sent messages today for the config company."""
        if self.config.daily_send_limit <= 0:
            return 0
        today = fields.Date.context_today(self.log_model)
        today_start = fields.Datetime.to_string(datetime.combine(today, time_cls.min))
        domain = [
            ('status', '=', 'sent'),
            ('sent_date', '>=', today_start),
            ('company_id', 'in', [False, self.config.company_id.id]),
        ]
        count = self.log_model.search_count(domain)
        _logger.debug('Daily sent count for company %s: %s', self.config.company_id.id, count)
        return count

    def check_daily_limit(self, planned_sends=1):
        limit = self.config.daily_send_limit or 0
        if limit <= 0:
            return
        sent_today = self.get_daily_sent_count()
        if sent_today + planned_sends > limit:
            _logger.warning(
                'Daily WhatsApp limit reached: %s sent, %s planned, limit %s',
                sent_today,
                planned_sends,
                limit,
            )
            raise ValidationError(
                _('Daily WhatsApp send limit reached (%(limit)s). '
                  'Already sent today: %(sent)s. '
                  'Reduce recipients or increase the limit in WhatsApp Settings.')
                % {'limit': limit, 'sent': sent_today}
            )

    def check_daily_limit_mid_send(self):
        """Re-check limit before each recipient during bulk runs."""
        self.check_daily_limit(planned_sends=1)

    # -------------------------------------------------------------------------
    # Attachments
    # -------------------------------------------------------------------------

    def validate_campaign_payload(self, message, attachments, products, use_product_images=False):
        """Ensure a bulk campaign has content before sending."""
        attachments = attachments or self.env['ir.attachment']
        products = products or self.env['product.template']
        if not (message and message.strip()) and not attachments and not products:
            raise ValidationError(
                _('Cannot start an empty campaign. Add a message, attachments, or products.')
            )
        if products and use_product_images:
            without_image = products.filtered(lambda p: not p.image_1920)
            if without_image == products:
                raise ValidationError(
                    _('Selected products have no images. Disable "Use Product Images" or add images.')
                )

    def validate_unique_recipients(self, partners):
        """Reject duplicate normalized phone numbers in the same campaign."""
        seen = {}
        duplicates = []
        for partner in partners:
            phone = partner._whatsapp_find_phone_number()
            if not phone:
                continue
            if phone in seen:
                duplicates.append((partner.display_name, seen[phone]))
            else:
                seen[phone] = partner.display_name
        if duplicates:
            names = ', '.join('%s / %s' % pair for pair in duplicates[:5])
            raise ValidationError(
                _('Duplicate phone numbers in recipient list: %s') % names
            )

    def validate_product_images_required(self, products, product_steps):
        """When use_product_images is on, at least one product must have an image step."""
        if products and not product_steps:
            raise ValidationError(
                _('No product images available to send. Add images or turn off "Use Product Images".')
            )

    def validate_attachments(self, attachments):
        """Backward-compatible alias — validates user free attachments only."""
        self.validate_free_attachments(attachments)

    def validate_free_attachments(self, attachments):
        """Validate user-uploaded files (not product catalog images)."""
        attachments = attachments or self.env['ir.attachment']
        if not attachments:
            return

        max_count = self.config.max_attachments_per_message or 3
        if len(attachments) > max_count:
            raise ValidationError(
                _('Too many free attachments (%(count)s). Maximum allowed: %(max)s.')
                % {'count': len(attachments), 'max': max_count}
            )

        max_bytes = int((self.config.max_attachment_size_mb or 16) * 1024 * 1024)
        total_size = 0
        for attachment in attachments:
            mimetype = (attachment.mimetype or '').lower()
            if mimetype and mimetype not in ALLOWED_ATTACHMENT_MIMETYPES:
                raise ValidationError(
                    _('Attachment "%(name)s" has unsupported type "%(mime)s".')
                    % {'name': attachment.name, 'mime': mimetype}
                )
            size = self._attachment_size_bytes(attachment)
            total_size += size
            _logger.debug(
                '[MULTI-ATTACHMENT] validate free file=%s size=%s bytes (per-file max %s)',
                attachment.name,
                size,
                max_bytes,
            )
            if size > max_bytes:
                raise ValidationError(
                    _('Attachment "%(name)s" is too large (%(size).2f MB). '
                      'Maximum allowed: %(max)s MB.')
                    % {
                        'name': attachment.name,
                        'size': size / (1024 * 1024),
                        'max': self.config.max_attachment_size_mb,
                    }
                )

        if total_size > max_bytes:
            raise ValidationError(
                _('Total size of free attachments (%.2f MB) exceeds the maximum allowed: %s MB.')
                % (total_size / (1024 * 1024), self.config.max_attachment_size_mb)
            )

    def validate_product_image_steps(self, product_steps):
        """Validate product catalog images separately from free attachments."""
        if not product_steps:
            return
        max_bytes = int((self.config.max_attachment_size_mb or 16) * 1024 * 1024)
        for step in product_steps:
            attachment = step.get('attachment')
            if not attachment:
                continue
            size = self._attachment_size_bytes(attachment)
            if size > max_bytes:
                product = step.get('product')
                name = product.display_name if product else attachment.name
                raise ValidationError(
                    _('Product image "%(name)s" is too large (%(size).2f MB). '
                      'Maximum allowed: %(max)s MB.')
                    % {
                        'name': name,
                        'size': size / (1024 * 1024),
                        'max': self.config.max_attachment_size_mb,
                    }
                )

    @staticmethod
    def _attachment_size_bytes(attachment):
        if not attachment:
            return 0
        if attachment.file_size:
            return attachment.file_size
        raw = attachment.raw
        if not raw:
            return 0
        try:
            return raw.size
        except (ValueError, TypeError, OSError):
            return 0

    def validate_single_binary_attachment(self, datas, filename=None):
        """Validate a binary field upload from the single-send wizard."""
        if not datas:
            return
        fake_name = filename or 'attachment'
        try:
            if hasattr(datas, 'size'):
                size = datas.size
            elif isinstance(datas, str):
                size = len(base64.b64decode(datas))
            else:
                size = len(bytes(datas))
        except (ValueError, TypeError, OSError) as exc:
            raise ValidationError(_('Invalid attachment data.')) from exc
        max_count = 1
        max_bytes = int((self.config.max_attachment_size_mb or 16) * 1024 * 1024)
        if size > max_bytes:
            raise ValidationError(
                _('Attachment "%(name)s" is too large (%(size).2f MB). '
                  'Maximum allowed: %(max)s MB.')
                % {
                    'name': fake_name,
                    'size': size / (1024 * 1024),
                    'max': self.config.max_attachment_size_mb,
                }
            )
        if max_count < 1:
            raise ValidationError(_('Attachments are not allowed.'))

    # -------------------------------------------------------------------------
    # Cooldown
    # -------------------------------------------------------------------------

    def apply_cooldown_if_needed(self, messages_since_cooldown, cooldown_count, campaign_id=None):
        """
        Pause when threshold reached. Returns updated (messages_since_cooldown, cooldown_count).
        """
        every = self.config.cooldown_every_messages or 0
        duration = self.config.cooldown_duration_seconds or 0
        if every <= 0 or duration <= 0:
            return messages_since_cooldown, cooldown_count

        if messages_since_cooldown >= every:
            _logger.debug(
                'Cooldown triggered after %s messages; sleeping %.1fs (campaign=%s)',
                messages_since_cooldown,
                duration,
                campaign_id,
            )
            from odoo.addons.relayruntime.services.logger import campaign_logger
            campaign_logger.info(
                'Campaign %s: COOLDOWN START %.1fs after %s messages',
                campaign_id,
                duration,
                messages_since_cooldown,
            )
            time.sleep(duration)
            campaign_logger.info('Campaign %s: COOLDOWN END', campaign_id)
            cooldown_count += 1
            return 0, cooldown_count
        return messages_since_cooldown, cooldown_count

    def count_recipients_with_phone(self, partners):
        return len(partners.filtered(lambda p: p._whatsapp_find_phone_number()))
