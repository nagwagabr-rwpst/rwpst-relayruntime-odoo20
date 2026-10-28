# -*- coding: utf-8 -*-

import logging
from typing import Dict, Optional, Type

from odoo.exceptions import UserError
from odoo.tools.translate import _

from odoo.addons.relayruntime.constants import PROVIDER_SELECTION_LABELS
from odoo.addons.relayruntime.services.exceptions.provider_errors import ProviderValidationError
from odoo.addons.relayruntime.services.providers.base_provider import BaseWhatsAppProvider
from odoo.addons.relayruntime.services.providers.green_api_provider import GreenAPIProvider
from odoo.addons.relayruntime.services.providers.mock_provider import MockProvider
from odoo.addons.relayruntime.services.providers.stub_provider import (
    CustomAPIProvider,
    EvolutionProvider,
    GupshupProvider,
    MetaCloudProvider,
    TwilioProvider,
    UltraMsgProvider,
)

_logger = logging.getLogger(__name__)

# Registry: provider_type -> adapter class
PROVIDER_REGISTRY: Dict[str, Type[BaseWhatsAppProvider]] = {
    'green_api': GreenAPIProvider,
    'mock_provider': MockProvider,
    'meta_cloud': MetaCloudProvider,
    'evolution': EvolutionProvider,
    'ultramsg': UltraMsgProvider,
    'twilio': TwilioProvider,
    'gupshup': GupshupProvider,
    'custom': CustomAPIProvider,
}

class ProviderRegistry:
    """Factory for WhatsApp provider adapters."""

    @classmethod
    def get_provider_class(cls, provider_type: str) -> Optional[Type[BaseWhatsAppProvider]]:
        return PROVIDER_REGISTRY.get(provider_type or 'green_api')

    @classmethod
    def get_provider(cls, config, env=None) -> BaseWhatsAppProvider:
        """
        Instantiate the adapter for the given whatsapp.config record.

        Raises UserError if provider type is unknown or not implemented.
        """
        provider_type = config.provider_type or 'green_api'
        provider_cls = cls.get_provider_class(provider_type)
        if not provider_cls:
            raise UserError(
                _('Unknown WhatsApp provider type: %s') % provider_type
            )
        if not getattr(provider_cls, 'is_implemented', False):
            raise UserError(
                _('WhatsApp provider "%s" is not implemented yet. '
                  'Please select Green API or implement adapter %s.')
                % (provider_type, provider_cls.__name__)
            )
        return provider_cls(config, env=env)

    @classmethod
    def get_provider_for_test(cls, config, env=None) -> BaseWhatsAppProvider:
        """Return provider instance even for stubs (used for capability display)."""
        provider_type = config.provider_type or 'green_api'
        provider_cls = cls.get_provider_class(provider_type)
        if not provider_cls:
            raise UserError(_('Unknown WhatsApp provider type: %s') % provider_type)
        return provider_cls(config, env=env)

    @classmethod
    def validate_provider_type(cls, provider_type: str):
        if provider_type not in PROVIDER_REGISTRY:
            raise ProviderValidationError(
                _('Invalid provider type: %(type)s') % {'type': provider_type}
            )

    @classmethod
    def list_provider_types(cls):
        return list(PROVIDER_REGISTRY.keys())

    @classmethod
    def get_capabilities(cls, config, env=None) -> dict:
        provider = cls.get_provider_for_test(config, env=env)
        return provider.get_capability_dict()

    @classmethod
    def is_implemented(cls, provider_type: str) -> bool:
        provider_cls = cls.get_provider_class(provider_type)
        return bool(provider_cls and getattr(provider_cls, 'is_implemented', False))
