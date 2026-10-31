# -*- coding: utf-8 -*-

import logging

from odoo.exceptions import UserError
from odoo.tools.translate import _

from odoo.addons.relayruntime.services.logger import configure_whatsapp_logging
from odoo.addons.relayruntime.services.providers.provider_registry import ProviderRegistry
from odoo.addons.relayruntime.services.providers.response import WhatsAppMedia

_logger = logging.getLogger(__name__)


class WhatsAppService:
    """
    Provider-agnostic facade for WhatsApp operations.

    Business services use this class only — never provider adapters directly.
    """

    def __init__(self, env, config):
        self.env = env
        self.config = config
        configure_whatsapp_logging(env)
        self.provider = ProviderRegistry.get_provider(config, env=env)

    @property
    def provider_type(self):
        return self.provider.provider_type

    @staticmethod
    def normalize_phone_number(number):
        from odoo.addons.relayruntime.services.whatsapp_phone_utils import normalize_phone_number
        return normalize_phone_number(number)

    @staticmethod
    def get_attachment_bytes(attachment):
        if not attachment:
            return b''
        raw = attachment.raw
        if not raw:
            return b''
        try:
            return raw.content
        except (ValueError, TypeError, OSError):
            return b''

    def prepare_payload(self, recipient_number, message, attachment_name=None, attachment_b64=None):
        """Debug helper — delegates chat id formatting to active provider."""
        payload = {
            'chatId': self.provider.prepare_chat_id(recipient_number),
            'message': message or '',
        }
        if attachment_b64:
            payload['file'] = attachment_b64
            payload['fileName'] = attachment_name or 'attachment'
        return payload

    def supports_feature(self, feature_name):
        return self.provider.supports_feature(feature_name)

    def get_capabilities(self):
        return self.provider.get_capability_dict()

    def send_text_message(self, recipient_number, message):
        self._ensure_active()
        response = self.provider.send_text_message(recipient_number, message)
        return response.to_dict()

    def send_attachment(self, recipient_number, message, attachment, file_bytes=None):
        self._ensure_active()
        content = file_bytes if file_bytes is not None else self.get_attachment_bytes(attachment)
        media = WhatsAppMedia(
            filename=attachment.name or 'attachment',
            content=content,
            mimetype=attachment.mimetype or 'application/octet-stream',
            caption=message or '',
        )
        response = self.provider.send_media_message(recipient_number, message, media)
        return response.to_dict()

    def send_media_message(self, recipient_number, message, media: WhatsAppMedia):
        self._ensure_active()
        response = self.provider.send_media_message(recipient_number, message, media)
        return response.to_dict()

    def test_connection(self):
        self._ensure_active()
        result = self.provider.test_connection()
        if not result.success:
            raise UserError(
                _('Connection test failed: %s') % (result.error_message or _('Unknown error'))
            )
        return result.raw_response

    def test_connection_with_health(self):
        """Test connection and return full result for health monitoring."""
        self._ensure_active()
        return self.provider.test_connection()

    def validate_configuration(self):
        self.provider.validate_configuration()

    def _ensure_active(self):
        if not self.config.active:
            raise UserError(_('WhatsApp integration is disabled. Enable it in Settings.'))
