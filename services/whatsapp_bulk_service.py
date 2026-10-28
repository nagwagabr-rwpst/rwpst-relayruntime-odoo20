# -*- coding: utf-8 -*-
# Runtime boundary: bulk orchestration — future extraction candidate for runtime/execution/.
# Odoo layer: campaign UI projection, partner/product linkage, wizard entrypoints.
# Intended for future worker isolation (see runtime/workers/TODO.md).

import json
import time
import traceback

from odoo import _, fields
from odoo.exceptions import ValidationError

from odoo.addons.relayruntime.services.logger import (
    api_logger,
    attachment_logger,
    campaign_logger,
    configure_whatsapp_logging,
    summarize_api_payload,
)
from odoo.addons.relayruntime.services.whatsapp_product_service import WhatsAppProductService
from odoo.addons.relayruntime.services.whatsapp_safety_utils import WhatsAppSafetyValidator
from odoo.addons.relayruntime.constants import EXECUTION_HEARTBEAT_EVERY_N_RECIPIENTS
from odoo.addons.relayruntime.services.whatsapp_service import WhatsAppService


class WhatsAppBulkSender:
    """Sequential bulk sender with observability, safety checks, and performance caches."""

    def __init__(self, env, config, campaign, wizard=None):
        self.env = env
        self.config = config
        self.campaign = campaign
        self.execution = None
        self.wizard = wizard
        configure_whatsapp_logging(env)
        self.service = WhatsAppService(env, config)
        self.safety = WhatsAppSafetyValidator(env, config)
        self.product_service = WhatsAppProductService(env)
        self.log_model = env['whatsapp.message.log']
        self.stats = {
            'total': 0,
            'sent': 0,
            'failed': 0,
            'skipped': 0,
            'cooldown_count': 0,
            'total_attachments_sent': 0,
        }
        self._messages_since_cooldown = 0
        self._product_steps = []
        self._catalog_message = ''
        self._attachment_bytes_cache = {}
        self._partner_phone_map = {}
        self._stopped = False
        self._fatal_error = False

    @staticmethod
    def _coerce_attachment_recordset(env, attachments):
        """Normalize legacy single attachment / id / recordset inputs to ir.attachment recordset."""
        Attachment = env['ir.attachment']
        if not attachments:
            return Attachment
        if isinstance(attachments, int):
            return Attachment.browse(attachments)
        if isinstance(attachments, (list, tuple)):
            ids = [item.id if hasattr(item, 'id') else item for item in attachments]
            return Attachment.browse(ids)
        if hasattr(attachments, '_name'):
            if attachments._name == 'ir.attachment':
                return attachments
            if attachments._name == 'whatsapp.bulk.send.wizard':
                return attachments.attachment_ids
        return Attachment

    def send_to_partners(
        self,
        partners,
        message,
        free_attachments=None,
        attachments=None,
        products=None,
        use_product_images=False,
        include_product_description=False,
    ):
        self.service.validate_configuration()
        products = products or self.env['product.template']
        free_attachments = self._coerce_attachment_recordset(
            self.env,
            free_attachments or attachments,
        )

        self.safety.validate_campaign_payload(
            message,
            free_attachments,
            products,
            use_product_images=use_product_images,
        )
        self.safety.validate_free_attachments(free_attachments)

        if products:
            plan = self.product_service.prepare_send_plan(
                products,
                use_product_images,
                include_product_description=include_product_description,
                res_model='whatsapp.bulk.campaign',
                res_id=self.campaign.id,
            )
            self._catalog_message = plan['message']
            self._product_steps = plan['product_image_steps']
            if not message:
                message = self._catalog_message
            if use_product_images:
                self.safety.validate_product_images_required(products, self._product_steps)
                self.safety.validate_product_image_steps(self._product_steps)
            elif not message:
                message = self._catalog_message

        partners = partners.sorted(key=lambda p: p.id)
        self.safety.validate_unique_recipients(partners)

        partner_data = self._batch_prepare_partners(partners)
        self.stats['total'] = len(partners)
        attachment_label = self._attachment_label(free_attachments, products, use_product_images)
        planned = sum(1 for row in partner_data if row['phone'])
        self.safety.check_daily_limit(planned_sends=planned)

        self.execution = self.campaign._mark_running(self.stats['total'])
        self._commit_progress()

        campaign_logger.info(
            'Campaign %s execution %s START: recipients=%s planned=%s free_attachments=%s product_images=%s products=%s',
            self.campaign.id,
            self.execution.id,
            self.stats['total'],
            planned,
            len(free_attachments),
            len(self._product_steps),
            len(products),
        )

        try:
            for index, row in enumerate(partner_data):
                partner = row['partner']
                if index > 0:
                    delay = self.safety.get_random_delay()
                    campaign_logger.debug(
                        'Campaign %s: inter-recipient delay %.2fs',
                        self.campaign.id,
                        delay,
                    )
                    time.sleep(delay)

                try:
                    self.safety.check_daily_limit_mid_send()
                except ValidationError as exc:
                    campaign_logger.warning(
                        'Campaign %s: daily limit reached at recipient %s — stopping',
                        self.campaign.id,
                        partner.id,
                    )
                    self._stopped = True
                    raise

                self._heartbeat_if_due(index)
                self.execution.update_progress(
                    self.stats,
                    recipient_index=index,
                    partner=partner,
                    phone=row['phone'],
                    step=_('Preparing recipient'),
                )
                self._update_wizard_progress(index, self.stats['total'], partner=partner)
                self._commit_progress()

                self._send_to_partner(
                    partner,
                    row['phone'],
                    message,
                    free_attachments,
                    attachment_label,
                    products,
                    use_product_images,
                    processed_index=index + 1,
                )

        except ValidationError:
            if self.execution:
                self.execution.finish(self.stats, stopped=self._stopped)
            else:
                self.campaign._mark_finished(self.stats, stopped=self._stopped)
            self._commit_progress()
            campaign_logger.warning(
                'Campaign %s stopped after validation boundary with stats=%s',
                self.campaign.id,
                self.stats,
            )
            return dict(self.stats)
        except Exception as exc:
            self._fatal_error = True
            campaign_logger.exception(
                'Campaign %s: fatal error — %s',
                self.campaign.id,
                exc,
            )
            if self.execution:
                self.execution.finish(self.stats, failed=True)
            else:
                self.campaign._mark_finished(self.stats, failed=True)
            self._commit_progress()
            return dict(self.stats)
        else:
            if self.execution:
                self.execution.finish(self.stats, stopped=self._stopped)
            else:
                self.campaign._mark_finished(self.stats, stopped=self._stopped)
            self._commit_progress()

        campaign_logger.info(
            'Campaign %s COMPLETE: sent=%s failed=%s skipped=%s attachments=%s cooldowns=%s',
            self.campaign.id,
            self.stats['sent'],
            self.stats['failed'],
            self.stats['skipped'],
            self.stats['total_attachments_sent'],
            self.stats['cooldown_count'],
        )
        return dict(self.stats)

    def _batch_prepare_partners(self, partners):
        """Batch-read partners and resolve phone numbers once per recipient."""
        if not partners:
            return []
        partners.read(['name', 'display_name'])
        rows = []
        seen_phones = set()
        for partner in partners:
            phone = partner._whatsapp_find_phone_number()
            if phone and phone in seen_phones:
                campaign_logger.warning(
                    'Campaign %s: duplicate phone %s for partner %s — will skip duplicate',
                    self.campaign.id,
                    phone,
                    partner.id,
                )
            elif phone:
                seen_phones.add(phone)
            rows.append({'partner': partner, 'phone': phone})
            self._partner_phone_map[partner.id] = phone
        return rows

    def _send_to_partner(
        self,
        partner,
        normalized,
        message,
        free_attachments,
        attachment_label,
        products,
        use_product_images,
        processed_index=0,
    ):
        start_time = time.monotonic()
        total = self.stats['total']
        idempotency_key = self._recipient_idempotency_key(partner)
        planned_attachment_count = (
            len(free_attachments) + len(self._product_steps)
        )

        existing = self.log_model.search([('idempotency_key', '=', idempotency_key)], limit=1)
        if existing:
            self.stats['skipped'] += 1
            campaign_logger.warning(
                'Campaign %s: duplicate execution prevented for partner %s (log=%s state=%s)',
                self.campaign.id,
                partner.id,
                existing.id,
                existing.delivery_state,
            )
            self._sync_execution_stats(processed_index, partner=partner, phone=normalized)
            return

        if not normalized:
            self.stats['skipped'] += 1
            campaign_logger.info(
                'Campaign %s: SKIP partner %s — no valid phone',
                self.campaign.id,
                partner.id,
            )
            self.log_model.create_log(
                recipient=partner.display_name,
                recipient_number='',
                message=message or '',
                delivery_state='skipped',
                related_model='res.partner',
                related_record_id=partner.id,
                partner_id=partner.id,
                campaign_id=self.campaign.id,
                execution_id=self.execution.id if self.execution else False,
                attachment_info=attachment_label,
                failure_reason=_('No valid phone number on this contact.'),
                retryable=True,
                product_ids=[(6, 0, products.ids)] if products else False,
                idempotency_key=idempotency_key,
                _start_time=start_time,
            )
            self._sync_execution_stats(processed_index)
            return

        campaign_logger.info(
            'Campaign %s: RECIPIENT START partner=%s number=%s (%s/%s)',
            self.campaign.id,
            partner.id,
            normalized,
            processed_index,
            total,
        )

        self.execution.update_progress(
            self.stats,
            recipient_index=processed_index,
            partner=partner,
            phone=normalized,
            step=_('Sending message'),
        )

        log = self.log_model.create_log(
            recipient=partner.display_name,
            recipient_number=normalized,
            message=message or _('(attachments only)'),
            delivery_state='queued',
            related_model='res.partner',
            related_record_id=partner.id,
            partner_id=partner.id,
            campaign_id=self.campaign.id,
            execution_id=self.execution.id if self.execution else False,
            attachment_info=attachment_label,
            attachment_count=planned_attachment_count,
            product_ids=[(6, 0, products.ids)] if products else False,
            idempotency_key=idempotency_key,
        )
        log.commit_outbound_intent()

        recipient_errors = []
        attachments_sent = 0

        try:
            self._deliver_to_partner(
                log,
                partner,
                normalized,
                message,
                free_attachments,
                use_product_images,
                recipient_errors,
                processed_index=processed_index,
                total=total,
            )
            attachments_sent = log.attachment_count
        except Exception as exc:
            self.stats['failed'] += 1
            campaign_logger.exception(
                'Campaign %s: unexpected error for partner %s',
                self.campaign.id,
                partner.id,
            )
            duration = time.monotonic() - start_time
            log.write({
                'delivery_state': 'failed',
                **self._failure_log_vals(str(exc), exc=exc, duration=duration),
            })
            self._sync_execution_stats(processed_index, partner=partner, phone=normalized)
            return

        duration = time.monotonic() - start_time
        if recipient_errors:
            delivery_state = 'failed'
            self.stats['failed'] += 1
            failure = '; '.join(recipient_errors)
            api_body = failure
            campaign_logger.warning(
                'Campaign %s: RECIPIENT FAILED partner=%s errors=%s',
                self.campaign.id,
                partner.id,
                failure,
            )
            log.write({
                'delivery_state': 'failed',
                'failure_reason': failure,
                'error_message': failure,
                'processing_duration': duration,
                'attachment_count': attachments_sent,
                'failed_at': fields.Datetime.now(),
                'retryable': True,
                'api_response_body': api_body,
            })
        else:
            delivery_state = 'sent'
            self.stats['sent'] += 1
            campaign_logger.info(
                'Campaign %s: RECIPIENT SUCCESS partner=%s duration=%.3fs',
                self.campaign.id,
                partner.id,
                duration,
            )
            self._messages_since_cooldown += 1
            before = self.stats['cooldown_count']
            self._messages_since_cooldown, self.stats['cooldown_count'] = (
                self.safety.apply_cooldown_if_needed(
                    self._messages_since_cooldown,
                    self.stats['cooldown_count'],
                    campaign_id=self.campaign.id,
                )
            )
            if self.stats['cooldown_count'] > before:
                campaign_logger.info(
                    'Campaign %s: cooldown completed (total cooldowns=%s)',
                    self.campaign.id,
                    self.stats['cooldown_count'],
                )
            log.write({
                'delivery_state': delivery_state,
                'processing_duration': duration,
                'attachment_count': attachments_sent,
            })
        self._sync_execution_stats(processed_index, partner=partner, phone=normalized)

    def _recipient_idempotency_key(self, partner):
        """Campaign-scoped dedupe; execution UUID scopes replay lineage on logs."""
        return 'campaign:%s:partner:%s' % (self.campaign.id, partner.id)

    def _heartbeat_if_due(self, recipient_index):
        if not self.execution:
            return
        force = recipient_index == 0
        every_n = EXECUTION_HEARTBEAT_EVERY_N_RECIPIENTS
        if force or (recipient_index and recipient_index % every_n == 0):
            self.execution.heartbeat_if_due(recipient_index, force=force)

    def _sync_execution_stats(self, recipient_index, partner=None, phone=None):
        if not self.execution:
            return
        self.execution.update_progress(
            self.stats,
            recipient_index=recipient_index,
            partner=partner,
            phone=phone,
        )
        self._heartbeat_if_due(recipient_index)

    def _deliver_to_partner(
        self,
        log,
        partner,
        normalized,
        message,
        free_attachments,
        use_product_images,
        recipient_errors,
        processed_index=0,
        total=0,
    ):
        attachments_sent = 0
        sent_text = False
        free_attachments = free_attachments or self.env['ir.attachment']
        total_free = len(free_attachments)
        send_catalog_text = message and (
            not use_product_images or message != self._catalog_message or not self._product_steps
        )

        if send_catalog_text and message:
            result = self._send_text(normalized, message)
            if result['success']:
                sent_text = True
                log.api_message_id = (
                    result.get('provider_message_id')
                    or self.log_model._extract_api_message_id(result.get('response'))
                )
            else:
                recipient_errors.append(self._format_api_error(_('Text'), result))

        elif use_product_images and self._catalog_message and self._product_steps:
            result = self._send_text(normalized, self._catalog_message)
            if result['success']:
                sent_text = True
            else:
                recipient_errors.append(self._format_api_error(_('Catalog'), result))

        for att_index, attachment in enumerate(free_attachments):
            if sent_text or att_index > 0:
                time.sleep(self.safety.get_attachment_delay())
            caption = message if (att_index == 0 and not sent_text) else ''
            attachment_logger.info(
                '[MULTI-ATTACHMENT] Campaign %s: uploading attachment %s/%s partner=%s file=%s',
                self.campaign.id,
                att_index + 1,
                total_free,
                partner.id,
                attachment.name,
            )
            if self.execution:
                self.execution.update_progress(
                    self.stats,
                    recipient_index=processed_index,
                    partner=partner,
                    phone=normalized,
                    step=_('Sending attachment %s/%s') % (att_index + 1, total_free),
                    throttle=True,
                )
            result = self._send_attachment(normalized, caption, attachment)
            if result['success']:
                attachments_sent += 1
                self.stats['total_attachments_sent'] += 1
            else:
                recipient_errors.append(
                    self._format_api_error(_('File "%s"') % attachment.name, result)
                )

        if use_product_images and self._product_steps:
            total_product = len(self._product_steps)
            for step_index, step in enumerate(self._product_steps):
                product = step['product']
                attachment = step['attachment']
                if self.execution:
                    self.execution.update_progress(
                        self.stats,
                        recipient_index=processed_index,
                        partner=partner,
                        phone=normalized,
                        product=product,
                        step=_('Sending product image %s/%s') % (step_index + 1, total_product),
                        throttle=True,
                    )
                self._update_wizard_progress(
                    processed_index,
                    total,
                    partner=partner,
                    product=product,
                )
                if sent_text or step_index > 0 or total_free > 0:
                    delay = self.safety.get_attachment_delay()
                    attachment_logger.debug(
                        'Campaign %s: attachment delay %.2fs before product %s',
                        self.campaign.id,
                        delay,
                        product.name,
                    )
                    time.sleep(delay)

                attachment_logger.info(
                    'Campaign %s: product image upload partner=%s product=%s file=%s',
                    self.campaign.id,
                    partner.id,
                    product.id,
                    attachment.name,
                )
                result = self._send_attachment(normalized, step['caption'], attachment)
                if result['success']:
                    attachments_sent += 1
                    self.stats['total_attachments_sent'] += 1
                else:
                    recipient_errors.append(
                        self._format_api_error(_('Product "%s"') % product.name, result)
                    )

        log.attachment_count = attachments_sent

    def _send_text(self, normalized, message):
        api_logger.debug(
            'Campaign %s: API text to %s payload=%s',
            self.campaign.id,
            normalized,
            summarize_api_payload(self.service.prepare_payload(normalized, message)),
        )
        result = self.service.send_text_message(normalized, message)
        api_logger.info(
            'Campaign %s: API text response success=%s',
            self.campaign.id,
            result.get('success'),
        )
        return result

    def _send_attachment(self, normalized, caption, attachment):
        file_bytes = self._get_cached_attachment_bytes(attachment)
        api_logger.debug(
            'Campaign %s: API file to %s file=%s bytes=%s',
            self.campaign.id,
            normalized,
            attachment.name,
            len(file_bytes) if file_bytes else 0,
        )
        result = self.service.send_attachment(
            normalized,
            caption,
            attachment,
            file_bytes=file_bytes,
        )
        api_logger.info(
            'Campaign %s: API file response success=%s file=%s',
            self.campaign.id,
            result.get('success'),
            attachment.name,
        )
        return result

    def _get_cached_attachment_bytes(self, attachment):
        att_id = attachment.id
        if att_id not in self._attachment_bytes_cache:
            self._attachment_bytes_cache[att_id] = self.service.get_attachment_bytes(attachment)
        return self._attachment_bytes_cache[att_id]

    @staticmethod
    def _format_api_error(label, result):
        err = result.get('error') or result.get('response')
        try:
            if isinstance(err, dict):
                err = json.dumps(err, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            pass
        return '%s: %s' % (label, err)

    @staticmethod
    def _failure_log_vals(failure, api_body=None, exc=None, duration=None):
        vals = {
            'failure_reason': failure,
            'error_message': failure,
            'failed_at': fields.Datetime.now(),
            'retryable': True,
            'api_response_body': api_body,
        }
        if duration is not None:
            vals['processing_duration'] = duration
        if exc:
            vals['exception_type'] = type(exc).__name__
            vals['traceback_summary'] = ''.join(
                traceback.format_exception_only(type(exc), exc)
            ).strip()
        return vals

    def _update_wizard_progress(self, current, total, partner=None, product=None):
        if not self.wizard:
            return
        self.wizard.write({
            'progress_percent': (current / total * 100.0) if total else 0.0,
            'current_recipient_name': partner.display_name if partner else False,
            'current_product_name': product.display_name if product else False,
            'processing_state': 'running',
        })

    def _commit_progress(self):
        # Intentionally avoid mid-execution commits to reduce partial durable states.
        return

    @staticmethod
    def _attachment_label(free_attachments, products, use_product_images=False):
        parts = []
        free_names = free_attachments.mapped('name')
        if free_names:
            parts.append(
                'Files (%(count)s): %(names)s'
                % {'count': len(free_names), 'names': ', '.join(free_names)}
            )
        if products:
            product_names = ', '.join(products.mapped('name'))
            if use_product_images:
                parts.append('Product images: %s' % product_names)
            else:
                parts.append('Product Catalog: %s' % product_names)
        return ' | '.join(parts)
