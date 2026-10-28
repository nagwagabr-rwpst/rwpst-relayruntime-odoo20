# -*- coding: utf-8 -*-

from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class WhatsAppMedia:
    """Normalized media payload for provider adapters."""

    filename: str
    content: bytes
    mimetype: str = 'application/octet-stream'
    caption: str = ''


@dataclass
class WhatsAppProviderResponse:
    """Normalized response from any WhatsApp provider adapter."""

    success: bool
    provider_message_id: Optional[str] = None
    delivery_state: str = 'sent'
    raw_response: Any = None
    error_message: Optional[str] = None
    retryable: bool = False
    status_code: Optional[int] = None
    provider_request_id: Optional[str] = None
    provider_type: Optional[str] = None

    def to_dict(self):
        """Backward-compatible dict for existing business services."""
        return {
            'success': self.success,
            'status': self.delivery_state,
            'response': self.raw_response,
            'error': self.error_message,
            'provider_message_id': self.provider_message_id,
            'retryable': self.retryable,
            'status_code': self.status_code,
            'provider_request_id': self.provider_request_id,
            'provider_type': self.provider_type,
        }

    @classmethod
    def from_exception(cls, exc, provider_type=None):
        return cls(
            success=False,
            delivery_state='failed',
            error_message=str(exc),
            raw_response=getattr(exc, 'raw_response', None),
            status_code=getattr(exc, 'status_code', None),
            retryable=getattr(exc, 'retryable', False),
            provider_type=provider_type,
        )


@dataclass
class WhatsAppProviderCapabilities:
    """Feature flags exposed by a provider adapter."""

    supports_media: bool = True
    supports_templates: bool = False
    supports_delivery_tracking: bool = False
    supports_webhooks: bool = False
    supports_bulk: bool = True
    supports_catalogs: bool = True

    def to_dict(self):
        return {
            'supports_media': self.supports_media,
            'supports_templates': self.supports_templates,
            'supports_delivery_tracking': self.supports_delivery_tracking,
            'supports_webhooks': self.supports_webhooks,
            'supports_bulk': self.supports_bulk,
            'supports_catalogs': self.supports_catalogs,
        }

    @classmethod
    def from_dict(cls, data):
        if not data:
            return cls()
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class WhatsAppConnectionResult:
    """Result of provider test_connection / health check."""

    success: bool
    state_label: str = ''
    raw_response: Any = None
    error_message: Optional[str] = None
    latency_ms: float = 0.0
    provider_request_id: Optional[str] = None
