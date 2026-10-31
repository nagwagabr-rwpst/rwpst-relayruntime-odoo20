# -*- coding: utf-8 -*-
"""Standardized WhatsApp provider exception hierarchy."""


class ProviderError(Exception):
    """Base class for all provider errors."""

    retryable = False

    def __init__(self, message, raw_response=None, status_code=None):
        super().__init__(message)
        self.message = message
        self.raw_response = raw_response
        self.status_code = status_code


class ProviderConnectionError(ProviderError):
    retryable = True


class ProviderAuthenticationError(ProviderError):
    retryable = False


class ProviderRateLimitError(ProviderError):
    retryable = True


class ProviderValidationError(ProviderError):
    retryable = False


class ProviderTemporaryFailure(ProviderError):
    retryable = True


class ProviderNotImplementedError(ProviderError):
    """Provider type is registered but not yet implemented."""

    retryable = False
