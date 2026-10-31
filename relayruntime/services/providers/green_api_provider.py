# -*- coding: utf-8 -*-

import logging

import requests

from odoo.tools.translate import _

from odoo.addons.relayruntime.services.exceptions.provider_errors import (
    ProviderConnectionError,
    ProviderValidationError,
)
from odoo.addons.relayruntime.services.logger import summarize_api_payload
from odoo.addons.relayruntime.services.providers.base_provider import BaseWhatsAppProvider
from odoo.addons.relayruntime.services.providers.response import (
    WhatsAppConnectionResult,
    WhatsAppMedia,
    WhatsAppProviderCapabilities,
    WhatsAppProviderResponse,
)

_logger = logging.getLogger(__name__)


class GreenAPIProvider(BaseWhatsAppProvider):
    """Green API (green-api.com) adapter — production implementation."""

    provider_type = 'green_api'
    provider_version = '1.0.0'
    is_implemented = True
    capabilities = WhatsAppProviderCapabilities(
        supports_media=True,
        supports_templates=False,
        supports_delivery_tracking=False,
        supports_webhooks=True,
        supports_bulk=True,
        supports_catalogs=True,
    )

    def validate_configuration(self):
        if not self.config.api_url:
            raise ProviderValidationError(_('API URL is required for Green API.'))
        if not self.config.instance_id:
            raise ProviderValidationError(_('Instance ID is required for Green API.'))
        if not self.config.access_token:
            raise ProviderValidationError(_('Access Token is required for Green API.'))

    def _base_url(self):
        return (self.config.api_url or '').rstrip('/')

    def _instance_path(self, endpoint):
        return (
            f'{self._base_url()}/waInstance{self.config.instance_id}'
            f'/{endpoint}/{self.config.access_token}'
        )

    def test_connection(self) -> WhatsAppConnectionResult:
        self.validate_configuration()
        url = self._instance_path('getStateInstance')

        def _call():
            try:
                response = requests.get(url, timeout=15)
            except requests.RequestException as exc:
                raise ProviderConnectionError(str(exc)) from exc
            parsed = self.parse_response(response)
            if not parsed.success:
                raise ProviderConnectionError(
                    parsed.error_message or 'Connection test failed',
                    parsed.raw_response,
                    parsed.status_code,
                )
            state = parsed.raw_response
            if isinstance(state, dict):
                state_label = state.get('stateInstance') or state.get('state') or str(state)
            else:
                state_label = str(state)
            return WhatsAppConnectionResult(
                success=True,
                state_label=state_label,
                raw_response=parsed.raw_response,
            )

        return self._timed_request('test_connection', _call)

    def send_text_message(self, recipient_number, message) -> WhatsAppProviderResponse:
        self.validate_configuration()
        chat_id = self.prepare_chat_id(recipient_number)
        payload = {'chatId': chat_id, 'message': message or ''}

        def _call():
            try:
                response = requests.post(
                    self._instance_path('sendMessage'),
                    json=payload,
                    timeout=30,
                )
            except requests.RequestException as exc:
                mapped = self.map_exception(exc)
                return WhatsAppProviderResponse.from_exception(mapped, self.provider_type)
            return self.parse_response(response)

        self._log_request('send_text', self._new_request_id(), payload=summarize_api_payload(payload))
        return self._timed_request('send_text_message', _call)

    def send_media_message(
        self,
        recipient_number,
        message,
        media: WhatsAppMedia,
    ) -> WhatsAppProviderResponse:
        self.validate_configuration()
        chat_id = self.prepare_chat_id(recipient_number)
        filename = media.filename or 'attachment'
        mimetype = media.mimetype or 'application/octet-stream'

        def _call():
            try:
                response = requests.post(
                    self._instance_path('sendFileByUpload'),
                    data={'chatId': chat_id, 'caption': message or media.caption or ''},
                    files=[('file', (filename, media.content, mimetype))],
                    timeout=60,
                )
            except requests.RequestException as exc:
                mapped = self.map_exception(exc)
                return WhatsAppProviderResponse.from_exception(mapped, self.provider_type)
            return self.parse_response(response)

        self._log_request(
            'send_media',
            self._new_request_id(),
            file=filename,
            bytes=len(media.content or b''),
        )
        return self._timed_request('send_media_message', _call)
