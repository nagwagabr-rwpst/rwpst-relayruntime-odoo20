# -*- coding: utf-8 -*-
"""
Webhook router skeleton.

Routes incoming HTTP webhooks to provider-specific handlers when implemented.
No controllers are registered yet — architecture readiness only.
"""

import logging

_logger = logging.getLogger(__name__)


class WhatsAppWebhookRouter:
    """Dispatch webhooks by provider_type on whatsapp.config."""

    HANDLER_REGISTRY = {}  # provider_type -> handler class (future)

    def __init__(self, env, config):
        self.env = env
        self.config = config

    def route(self, payload, headers=None):
        """
        Entry point for future HTTP controller.

        Returns normalized dict with routing metadata.
        """
        provider_type = self.config.provider_type or 'green_api'
        handler_cls = self.HANDLER_REGISTRY.get(provider_type)
        if not handler_cls:
            _logger.debug(
                'Webhook received for provider %s — no handler registered yet',
                provider_type,
            )
            return {
                'accepted': False,
                'reason': 'handler_not_registered',
                'provider_type': provider_type,
            }
        handler = handler_cls(self.config, self.env)
        if not handler.verify_signature(payload, headers or {}):
            return {
                'accepted': False,
                'reason': 'signature_verification_failed',
                'provider_type': provider_type,
            }
        return {
            'accepted': True,
            'provider_type': provider_type,
            'events': handler.parse_incoming_payload(payload, headers or {}),
        }

    @classmethod
    def register_handler(cls, provider_type, handler_class):
        """Register a provider webhook handler (for future modules)."""
        cls.HANDLER_REGISTRY[provider_type] = handler_class
