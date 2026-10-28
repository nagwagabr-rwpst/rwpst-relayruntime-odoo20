# -*- coding: utf-8 -*-
"""Webhook interface skeleton for future incoming message handling."""

from abc import ABC, abstractmethod


class BaseWhatsAppWebhookHandler(ABC):
    """Provider-specific webhook verification and payload parsing."""

    provider_type: str = 'base'

    def __init__(self, config, env=None):
        self.config = config
        self.env = env

    @abstractmethod
    def verify_signature(self, payload, headers) -> bool:
        """Verify webhook authenticity (signature, secret, etc.)."""

    @abstractmethod
    def parse_incoming_payload(self, payload, headers) -> dict:
        """Normalize incoming webhook payload to a common dict shape."""

    def handle_delivery_update(self, payload, headers) -> dict:
        """Optional delivery status updates."""
        return {'handled': False, 'provider_type': self.provider_type}
