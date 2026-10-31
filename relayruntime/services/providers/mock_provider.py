# -*- coding: utf-8 -*-
"""
Internal testing provider — simulates WhatsApp API without network calls.

Magic recipient numbers (normalized, digits only) force specific outcomes:
  201000000000  invalid number
  201111111111  authentication failure
  201222222222  provider disconnect
  201333333333  timeout
  201444444444  rate limit
  201555555555  malformed API response
  201666666666  attachment upload failure (media sends only)
"""

import logging
import random
import time
import uuid

from odoo.tools.translate import _

from odoo.addons.relayruntime.services.exceptions.provider_errors import (
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderValidationError,
)
from odoo.addons.relayruntime.services.logger import provider_api_logger
from odoo.addons.relayruntime.services.providers.base_provider import BaseWhatsAppProvider
from odoo.addons.relayruntime.services.providers.response import (
    WhatsAppConnectionResult,
    WhatsAppMedia,
    WhatsAppProviderCapabilities,
    WhatsAppProviderResponse,
)

_logger = logging.getLogger(__name__)

# Deterministic test numbers (after normalization — Egyptian-style examples)
MAGIC_INVALID = '201000000000'
MAGIC_AUTH_FAIL = '201111111111'
MAGIC_DISCONNECT = '201222222222'
MAGIC_TIMEOUT = '201333333333'
MAGIC_RATE_LIMIT = '201444444444'
MAGIC_MALFORMED = '201555555555'
MAGIC_ATTACHMENT_FAIL = '201666666666'

SIMULATION_OUTCOMES = (
    'success',
    'failure',
    'timeout',
    'rate_limit',
)

_DEFAULT_SUCCESS_RATE = 85.0
_DEFAULT_FAILURE_RATE = 5.0
_DEFAULT_TIMEOUT_RATE = 3.0
_DEFAULT_RATE_LIMIT_RATE = 2.0


def _coalesce_simulation_rate(value, default):
    """Preserve configured 0.0; use default only when the field is unset (None/False)."""
    if value is None or value is False:
        return float(default)
    return float(value)


class MockProvider(BaseWhatsAppProvider):
    """Fully simulated provider for QA, demos, and stress tests — no real messages sent."""

    provider_type = 'mock_provider'
    provider_version = '1.0.0'
    is_implemented = True
    capabilities = WhatsAppProviderCapabilities(
        supports_media=True,
        supports_templates=True,
        supports_delivery_tracking=True,
        supports_webhooks=True,
        supports_bulk=True,
        supports_catalogs=True,
    )

    def get_provider_name(self):
        return 'Mock Provider (Test Mode)'

    def validate_configuration(self):
        rates = self._get_rate_map()
        for name, value in rates.items():
            if value < 0 or value > 100:
                field_label = name
                if self.env and name in self.config._fields:
                    field_label = self.config._fields[name].string or name
                raise ProviderValidationError(
                    _('Mock simulation rate "%(field)s" must be between 0 and 100.')
                    % {'field': field_label}
                )
        if self.config.simulated_latency_ms < 0:
            raise ProviderValidationError(_('Simulated latency cannot be negative.'))
        if self.config.simulate_attachment_failure_rate < 0:
            raise ProviderValidationError(_('Attachment failure rate cannot be negative.'))

    def test_connection(self) -> WhatsAppConnectionResult:
        self.validate_configuration()

        def _call():
            self._simulate_latency()
            if self.config.mock_force_disconnect:
                raise ProviderConnectionError(
                    _('Simulated provider disconnect (config flag).')
                )
            if self.config.mock_force_auth_failure:
                raise ProviderAuthenticationError(
                    _('Simulated authentication failure (config flag).')
                )
            latency = float(self.config.simulated_latency_ms or 0)
            raw = {
                'state': 'authorized',
                'mode': 'mock',
                'provider': self.provider_type,
                'message': 'Mock provider ready — no real messages will be sent.',
            }
            provider_api_logger.info(
                '[MOCK] test_connection success latency_ms=%.0f',
                latency,
            )
            return WhatsAppConnectionResult(
                success=True,
                state_label='mock_authorized',
                raw_response=raw,
                latency_ms=latency,
            )

        return self._timed_request('test_connection', _call)

    def send_text_message(self, recipient_number, message) -> WhatsAppProviderResponse:
        self.validate_configuration()
        return self._simulate_operation(
            recipient_number,
            operation='send_text',
            message=message,
        )

    def send_media_message(
        self,
        recipient_number,
        message,
        media: WhatsAppMedia,
    ) -> WhatsAppProviderResponse:
        self.validate_configuration()
        return self._simulate_operation(
            recipient_number,
            operation='send_media',
            message=message,
            media=media,
        )

    def send_multiple_media(
        self,
        recipient_number,
        media_list,
    ):
        results = []
        for index, media in enumerate(media_list):
            caption = media.caption if index == 0 else media.caption
            results.append(
                self.send_media_message(recipient_number, caption, media)
            )
        return results

    # -------------------------------------------------------------------------
    # Simulation engine
    # -------------------------------------------------------------------------

    def _get_rate_map(self):
        return {
            'success': _coalesce_simulation_rate(
                self.config.simulate_success_rate, _DEFAULT_SUCCESS_RATE,
            ),
            'failure': _coalesce_simulation_rate(
                self.config.simulate_failure_rate, _DEFAULT_FAILURE_RATE,
            ),
            'timeout': _coalesce_simulation_rate(
                self.config.simulate_timeout_rate, _DEFAULT_TIMEOUT_RATE,
            ),
            'rate_limit': _coalesce_simulation_rate(
                self.config.simulate_rate_limit_rate, _DEFAULT_RATE_LIMIT_RATE,
            ),
        }

    def _simulate_latency(self):
        ms = float(self.config.simulated_latency_ms or 0)
        if ms > 0:
            time.sleep(ms / 1000.0)

    def _normalize_digits(self, recipient_number):
        return ''.join(c for c in (recipient_number or '') if c.isdigit())

    def _resolve_magic_outcome(self, digits, operation, media=None):
        """Deterministic outcomes for known test numbers."""
        if digits == MAGIC_INVALID:
            raise ProviderValidationError('Simulated invalid phone number.')
        if digits == MAGIC_AUTH_FAIL:
            return self._build_response(
                'auth_failure',
                operation,
                digits,
                media=media,
            )
        if digits == MAGIC_DISCONNECT:
            return self._build_response(
                'disconnect',
                operation,
                digits,
                media=media,
            )
        if digits == MAGIC_TIMEOUT:
            return self._build_response(
                'timeout',
                operation,
                digits,
                media=media,
            )
        if digits == MAGIC_RATE_LIMIT:
            return self._build_response(
                'rate_limit',
                operation,
                digits,
                media=media,
            )
        if digits == MAGIC_MALFORMED:
            return self._build_response(
                'malformed',
                operation,
                digits,
                media=media,
            )
        if operation == 'send_media' and digits == MAGIC_ATTACHMENT_FAIL:
            return self._build_response(
                'attachment_failure',
                operation,
                digits,
                media=media,
            )
        return None

    def _pick_random_outcome(self, operation, media=None):
        rates = self._get_rate_map()
        if operation == 'send_media':
            att_rate = _coalesce_simulation_rate(
                self.config.simulate_attachment_failure_rate, 0.0,
            )
            if att_rate > 0 and random.uniform(0, 100) < att_rate:
                return 'attachment_failure'

        if (
            rates['failure'] == 0.0
            and rates['timeout'] == 0.0
            and rates['rate_limit'] == 0.0
        ):
            return 'success'

        total = sum(rates.values())
        if total <= 0:
            return 'success'

        roll = random.uniform(0, total)
        cumulative = 0.0
        for outcome in SIMULATION_OUTCOMES:
            cumulative += rates[outcome]
            if roll <= cumulative:
                return outcome
        return 'success'

    def _simulate_operation(
        self,
        recipient_number,
        operation='send_text',
        message=None,
        media=None,
    ):
        request_id = self._new_request_id()
        digits = self._normalize_digits(recipient_number)

        try:
            chat_id = self.prepare_chat_id(recipient_number)
        except ProviderValidationError:
            provider_api_logger.warning(
                '[MOCK] %s request_id=%s invalid_number=%s',
                operation,
                request_id,
                recipient_number,
            )
            raise

        self._log_request(operation, request_id, chat_id=chat_id, mock=True)
        self._simulate_latency()

        try:
            outcome = self._resolve_magic_outcome(digits, operation, media=media)
            if outcome is None:
                outcome_name = self._pick_random_outcome(operation, media=media)
                outcome = self._build_response(
                    outcome_name,
                    operation,
                    digits,
                    message=message,
                    media=media,
                )
        except ProviderValidationError:
            raise
        except Exception as exc:
            outcome = WhatsAppProviderResponse.from_exception(exc, self.provider_type)

        outcome.provider_request_id = request_id
        outcome.provider_type = self.provider_type
        self._log_simulated_result(operation, request_id, outcome)
        return outcome

    def _build_response(
        self,
        outcome_name,
        operation,
        digits,
        message=None,
        media=None,
    ):
        message_id = 'mock-%s' % uuid.uuid4().hex[:16]

        if outcome_name == 'success':
            raw = {
                'idMessage': message_id,
                'mock': True,
                'operation': operation,
                'chatId': '%s@c.us' % digits,
                'status': 'sent',
            }
            if media:
                raw['fileName'] = media.filename
                raw['bytes'] = len(media.content or b'')
            provider_api_logger.info(
                '[MOCK] simulated SUCCESS op=%s message_id=%s',
                operation,
                message_id,
            )
            return WhatsAppProviderResponse(
                success=True,
                provider_message_id=message_id,
                delivery_state='sent',
                raw_response=raw,
                status_code=200,
                retryable=False,
                provider_type=self.provider_type,
            )

        if outcome_name == 'failure':
            provider_api_logger.warning('[MOCK] simulated FAILURE op=%s', operation)
            return WhatsAppProviderResponse(
                success=False,
                delivery_state='failed',
                error_message='Simulated generic API failure.',
                raw_response={'error': 'mock_generic_failure', 'mock': True},
                status_code=500,
                retryable=True,
                provider_type=self.provider_type,
            )

        if outcome_name == 'timeout':
            provider_api_logger.warning('[MOCK] simulated TIMEOUT op=%s', operation)
            return WhatsAppProviderResponse(
                success=False,
                delivery_state='failed',
                error_message='Simulated request timeout.',
                raw_response={'error': 'mock_timeout', 'mock': True},
                status_code=408,
                retryable=True,
                provider_type=self.provider_type,
            )

        if outcome_name == 'rate_limit':
            provider_api_logger.warning('[MOCK] simulated RATE LIMIT op=%s', operation)
            return WhatsAppProviderResponse(
                success=False,
                delivery_state='failed',
                error_message='Simulated rate limit exceeded.',
                raw_response={'error': 'mock_rate_limit', 'retry_after': 60, 'mock': True},
                status_code=429,
                retryable=True,
                provider_type=self.provider_type,
            )

        if outcome_name == 'auth_failure':
            provider_api_logger.warning('[MOCK] simulated AUTH FAILURE op=%s', operation)
            return WhatsAppProviderResponse(
                success=False,
                delivery_state='failed',
                error_message='Simulated authentication failure.',
                raw_response={'error': 'mock_auth_failure', 'mock': True},
                status_code=401,
                retryable=False,
                provider_type=self.provider_type,
            )

        if outcome_name == 'disconnect':
            provider_api_logger.warning('[MOCK] simulated DISCONNECT op=%s', operation)
            return WhatsAppProviderResponse(
                success=False,
                delivery_state='failed',
                error_message='Simulated provider disconnect.',
                raw_response={'error': 'mock_disconnect', 'mock': True},
                status_code=503,
                retryable=True,
                provider_type=self.provider_type,
            )

        if outcome_name == 'malformed':
            provider_api_logger.warning('[MOCK] simulated MALFORMED RESPONSE op=%s', operation)
            return WhatsAppProviderResponse(
                success=False,
                delivery_state='failed',
                error_message='Simulated malformed API response.',
                raw_response='<<not-json>>{broken',
                status_code=200,
                retryable=False,
                provider_type=self.provider_type,
            )

        if outcome_name == 'attachment_failure':
            provider_api_logger.warning(
                '[MOCK] simulated ATTACHMENT FAILURE op=%s file=%s',
                operation,
                media.filename if media else '-',
            )
            return WhatsAppProviderResponse(
                success=False,
                delivery_state='failed',
                error_message='Simulated attachment upload failure.',
                raw_response={
                    'error': 'mock_attachment_failure',
                    'fileName': media.filename if media else None,
                    'mock': True,
                },
                status_code=400,
                retryable=True,
                provider_type=self.provider_type,
            )

        return self._build_response('success', operation, digits, message=message, media=media)

    def _log_simulated_result(self, operation, request_id, response):
        provider_api_logger.info(
            '[MOCK] %s request_id=%s success=%s status=%s retryable=%s message_id=%s',
            operation,
            request_id,
            response.success,
            response.status_code,
            response.retryable,
            response.provider_message_id,
        )
