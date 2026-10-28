# -*- coding: utf-8 -*-

import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import List, Optional

from odoo.tools.translate import _

from odoo.addons.relayruntime.services.exceptions.provider_errors import (
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderError,
    ProviderNotImplementedError,
    ProviderRateLimitError,
    ProviderTemporaryFailure,
    ProviderValidationError,
)
from odoo.addons.relayruntime.services.logger import (
    log_provider_failure,
    log_provider_request,
    provider_api_logger,
)
from odoo.addons.relayruntime.services.providers.response import (
    WhatsAppConnectionResult,
    WhatsAppMedia,
    WhatsAppProviderCapabilities,
    WhatsAppProviderResponse,
)
from odoo.addons.relayruntime.services.whatsapp_phone_utils import (
    format_chat_id,
    normalize_phone_number,
)

_logger = logging.getLogger(__name__)


class BaseWhatsAppProvider(ABC):
    """
    Abstract contract for WhatsApp API providers.

    All provider-specific HTTP/API logic must live in subclasses only.
    """

    provider_type: str = 'base'
    provider_version: str = '1.0.0'
    is_implemented: bool = False
    capabilities: WhatsAppProviderCapabilities = WhatsAppProviderCapabilities()

    def __init__(self, config, env=None):
        self.config = config
        self.env = env

    # -------------------------------------------------------------------------
    # Identity & capabilities
    # -------------------------------------------------------------------------

    def get_provider_name(self):
        return self.provider_type.replace('_', ' ').title()

    def get_capabilities(self):
        return self.capabilities

    def supports_feature(self, feature_name):
        return bool(getattr(self.capabilities, feature_name, False))

    def get_capability_dict(self):
        return self.capabilities.to_dict()

    # -------------------------------------------------------------------------
    # Phone helpers (shared defaults)
    # -------------------------------------------------------------------------

    def normalize_phone(self, number):
        return normalize_phone_number(number)

    def prepare_chat_id(self, recipient_number):
        chat_id = format_chat_id(recipient_number)
        if not chat_id:
            raise ProviderValidationError(
                _('Recipient phone number is invalid or malformed.')
            )
        return chat_id

    # -------------------------------------------------------------------------
    # Required abstract API
    # -------------------------------------------------------------------------

    @abstractmethod
    def validate_configuration(self):
        """Raise ProviderValidationError if config is incomplete for this provider."""

    @abstractmethod
    def test_connection(self) -> WhatsAppConnectionResult:
        """Verify credentials and connectivity."""

    @abstractmethod
    def send_text_message(self, recipient_number, message) -> WhatsAppProviderResponse:
        """Send a plain text message."""

    @abstractmethod
    def send_media_message(
        self,
        recipient_number,
        message,
        media: WhatsAppMedia,
    ) -> WhatsAppProviderResponse:
        """Send a single media attachment."""

    # -------------------------------------------------------------------------
    # Default implementations
    # -------------------------------------------------------------------------

    def send_multiple_media(
        self,
        recipient_number,
        media_list: List[WhatsAppMedia],
    ) -> List[WhatsAppProviderResponse]:
        """Send media sequentially; subclasses may override for batch APIs."""
        results = []
        for index, media in enumerate(media_list):
            caption = media.caption if index == 0 else media.caption
            results.append(
                self.send_media_message(recipient_number, caption, media)
            )
        return results

    def send_template(self, recipient_number, template_name, variables=None):
        raise ProviderNotImplementedError(
            'Templates are not supported by provider %s.' % self.provider_type
        )

    def get_delivery_status(self, provider_message_id):
        raise ProviderNotImplementedError(
            'Delivery status is not supported by provider %s.' % self.provider_type
        )

    def upload_media(self, media: WhatsAppMedia):
        raise ProviderNotImplementedError(
            'Media upload is not supported by provider %s.' % self.provider_type
        )

    def receive_webhook(self, payload, headers=None):
        raise ProviderNotImplementedError(
            'Webhooks are not supported by provider %s.' % self.provider_type
        )

    # -------------------------------------------------------------------------
    # Response / error normalization
    # -------------------------------------------------------------------------

    def parse_response(self, http_response) -> WhatsAppProviderResponse:
        """Default HTTP response parser; override for provider-specific shapes."""
        try:
            data = http_response.json()
        except ValueError:
            data = {'raw': http_response.text}

        success = http_response.ok
        message_id = self._extract_message_id(data) if success else None
        return WhatsAppProviderResponse(
            success=success,
            provider_message_id=message_id,
            delivery_state='sent' if success else 'failed',
            raw_response=data,
            error_message=None if success else http_response.text,
            retryable=not success and http_response.status_code >= 500,
            status_code=http_response.status_code,
            provider_type=self.provider_type,
        )

    def parse_error(self, exc, status_code=None, raw_response=None) -> WhatsAppProviderResponse:
        mapped = self.map_exception(exc, status_code=status_code, raw_response=raw_response)
        if isinstance(mapped, ProviderError):
            return WhatsAppProviderResponse.from_exception(mapped, self.provider_type)
        return WhatsAppProviderResponse(
            success=False,
            delivery_state='failed',
            error_message=str(exc),
            raw_response=raw_response,
            status_code=status_code,
            retryable=False,
            provider_type=self.provider_type,
        )

    def map_exception(self, exc, status_code=None, raw_response=None):
        """Map provider-specific errors to standardized exceptions."""
        if isinstance(exc, ProviderError):
            return exc
        message = str(exc)
        lower = message.lower()
        if status_code in (401, 403):
            return ProviderAuthenticationError(message, raw_response, status_code)
        if status_code == 429 or 'rate limit' in lower:
            return ProviderRateLimitError(message, raw_response, status_code)
        if status_code and status_code >= 500:
            return ProviderTemporaryFailure(message, raw_response, status_code)
        if 'timeout' in lower or 'connection' in lower:
            return ProviderConnectionError(message, raw_response, status_code)
        return ProviderError(message, raw_response, status_code)

    @staticmethod
    def _extract_message_id(data):
        if not isinstance(data, dict):
            return None
        messages = data.get('messages')
        first_msg_id = None
        if isinstance(messages, list) and messages:
            first_msg_id = messages[0].get('id')
        return (
            data.get('idMessage')
            or data.get('messageId')
            or first_msg_id
            or data.get('id')
        )

    # -------------------------------------------------------------------------
    # Logging helpers
    # -------------------------------------------------------------------------

    def _new_request_id(self):
        return str(uuid.uuid4())[:12]

    def _log_request(self, operation, request_id, **extra):
        log_provider_request(
            self.provider_type,
            operation,
            request_id,
            **extra,
        )

    def _log_failure(self, operation, request_id, error, **extra):
        log_provider_failure(
            self.provider_type,
            operation,
            request_id,
            error,
            **extra,
        )

    def _timed_request(self, operation, func):
        """Execute HTTP call with timing and standardized error handling."""
        request_id = self._new_request_id()
        self._log_request(operation, request_id)
        start = time.monotonic()
        try:
            result = func()
            latency_ms = (time.monotonic() - start) * 1000
            provider_api_logger.info(
                'provider=%s op=%s request_id=%s latency_ms=%.0f success=%s',
                self.provider_type,
                operation,
                request_id,
                latency_ms,
                getattr(result, 'success', True),
            )
            if isinstance(result, WhatsAppProviderResponse):
                result.provider_request_id = request_id
                result.provider_type = self.provider_type
            elif isinstance(result, WhatsAppConnectionResult):
                result.provider_request_id = request_id
                result.latency_ms = latency_ms
            return result
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            self._log_failure(operation, request_id, exc, latency_ms=latency_ms)
            raise

    def capabilities_json(self):
        return json.dumps(self.get_capability_dict())
