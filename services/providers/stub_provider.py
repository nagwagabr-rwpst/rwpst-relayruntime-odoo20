# -*- coding: utf-8 -*-

from odoo.tools.translate import _

from odoo.addons.relayruntime.services.exceptions.provider_errors import (
    ProviderNotImplementedError,
    ProviderValidationError,
)
from odoo.addons.relayruntime.services.providers.base_provider import BaseWhatsAppProvider
from odoo.addons.relayruntime.services.providers.response import (
    WhatsAppConnectionResult,
    WhatsAppMedia,
    WhatsAppProviderCapabilities,
    WhatsAppProviderResponse,
)


class StubWhatsAppProvider(BaseWhatsAppProvider):
    """Placeholder adapter for providers not yet implemented."""

    is_implemented = False

    def validate_configuration(self):
        raise ProviderValidationError(
            _('Provider "%(provider)s" is not implemented yet. '
              'Select Green API or add a custom adapter.')
            % {'provider': self.get_provider_name()}
        )

    def test_connection(self) -> WhatsAppConnectionResult:
        raise ProviderNotImplementedError(
            'Connection test is not available for %s.' % self.get_provider_name()
        )

    def send_text_message(self, recipient_number, message) -> WhatsAppProviderResponse:
        raise ProviderNotImplementedError(
            'Sending is not implemented for %s.' % self.get_provider_name()
        )

    def send_media_message(
        self,
        recipient_number,
        message,
        media: WhatsAppMedia,
    ) -> WhatsAppProviderResponse:
        raise ProviderNotImplementedError(
            'Media sending is not implemented for %s.' % self.get_provider_name()
        )


class MetaCloudProvider(StubWhatsAppProvider):
    provider_type = 'meta_cloud'
    provider_version = '0.0.0-stub'
    capabilities = WhatsAppProviderCapabilities(
        supports_media=True,
        supports_templates=True,
        supports_delivery_tracking=True,
        supports_webhooks=True,
        supports_bulk=True,
        supports_catalogs=True,
    )


class EvolutionProvider(StubWhatsAppProvider):
    provider_type = 'evolution'
    provider_version = '0.0.0-stub'
    capabilities = WhatsAppProviderCapabilities(
        supports_media=True,
        supports_webhooks=True,
        supports_bulk=True,
    )


class UltraMsgProvider(StubWhatsAppProvider):
    provider_type = 'ultramsg'
    provider_version = '0.0.0-stub'
    capabilities = WhatsAppProviderCapabilities(
        supports_media=True,
        supports_bulk=True,
    )


class TwilioProvider(StubWhatsAppProvider):
    provider_type = 'twilio'
    provider_version = '0.0.0-stub'
    capabilities = WhatsAppProviderCapabilities(
        supports_media=True,
        supports_templates=True,
        supports_bulk=True,
    )


class GupshupProvider(StubWhatsAppProvider):
    provider_type = 'gupshup'
    provider_version = '0.0.0-stub'
    capabilities = WhatsAppProviderCapabilities(
        supports_media=True,
        supports_templates=True,
        supports_bulk=True,
    )


class CustomAPIProvider(StubWhatsAppProvider):
    provider_type = 'custom'
    provider_version = '0.0.0-stub'
    capabilities = WhatsAppProviderCapabilities(
        supports_media=True,
        supports_bulk=True,
        supports_catalogs=True,
    )
