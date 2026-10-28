# -*- coding: utf-8 -*-
"""
Centralized logging for relayruntime.

Provider-aware loggers propagate to Odoo root logging.
Optional rotating file handlers do not replace default Odoo handlers.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

CAMPAIGN_LOGGER_NAME = 'odoo.addons.relayruntime.campaign'
API_LOGGER_NAME = 'odoo.addons.relayruntime.api'
ATTACHMENT_LOGGER_NAME = 'odoo.addons.relayruntime.attachment'
PROVIDER_API_LOGGER_NAME = 'odoo.addons.relayruntime.provider_api'
FAILURES_LOGGER_NAME = 'odoo.addons.relayruntime.failures'

DEFAULT_LOG_PATH = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')),
    'logs',
    'whatsapp.log',
)
DEFAULT_PROVIDER_LOG_PATH = os.path.join(
    os.path.dirname(DEFAULT_LOG_PATH),
    'provider_api.log',
)
DEFAULT_FAILURES_LOG_PATH = os.path.join(
    os.path.dirname(DEFAULT_LOG_PATH),
    'failures.log',
)

_LOG_FORMAT = '%(asctime)s | %(levelname)-7s | %(name)s | %(message)s'
_FILE_HANDLERS = {}

campaign_logger = logging.getLogger(CAMPAIGN_LOGGER_NAME)
api_logger = logging.getLogger(API_LOGGER_NAME)
attachment_logger = logging.getLogger(ATTACHMENT_LOGGER_NAME)
provider_api_logger = logging.getLogger(PROVIDER_API_LOGGER_NAME)
failures_logger = logging.getLogger(FAILURES_LOGGER_NAME)

_ALL_LOGGERS = (
    campaign_logger,
    api_logger,
    attachment_logger,
    provider_api_logger,
    failures_logger,
)

for _logger in _ALL_LOGGERS:
    _logger.propagate = True


def _attach_file_handler(log_path, loggers=None, max_bytes=10 * 1024 * 1024, backup_count=5):
    log_path = os.path.abspath(log_path)
    if log_path in _FILE_HANDLERS:
        return

    log_dir = os.path.dirname(log_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8',
    )
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    handler.setLevel(logging.DEBUG)

    targets = loggers or _ALL_LOGGERS
    for logger in targets:
        if handler not in logger.handlers:
            logger.addHandler(handler)

    _FILE_HANDLERS[log_path] = handler


def configure_whatsapp_logging(env=None, log_path=None, enabled=None):
    if env is not None:
        try:
            config = env['whatsapp.config'].sudo().search([
                ('active', '=', True),
                ('company_id', 'in', [False, env.company.id]),
            ], limit=1)
        except Exception:
            config = env['whatsapp.config'].sudo().browse()
        if config:
            enabled = config.file_log_enabled if enabled is None else enabled
            log_path = config.file_log_path or DEFAULT_LOG_PATH if log_path is None else log_path

    if not enabled:
        return

    path = log_path or DEFAULT_LOG_PATH
    _attach_file_handler(path, _ALL_LOGGERS)
    base_dir = os.path.dirname(path)
    _attach_file_handler(
        os.path.join(base_dir, 'provider_api.log'),
        (provider_api_logger, api_logger),
    )
    _attach_file_handler(
        os.path.join(base_dir, 'failures.log'),
        (failures_logger, campaign_logger),
    )


def log_provider_request(provider_type, operation, request_id, **extra):
    provider_api_logger.info(
        'provider=%s op=%s request_id=%s %s',
        provider_type,
        operation,
        request_id,
        ' '.join('%s=%s' % (k, v) for k, v in extra.items()),
    )


def log_provider_failure(provider_type, operation, request_id, error, **extra):
    failures_logger.warning(
        'provider=%s op=%s request_id=%s error=%s %s',
        provider_type,
        operation,
        request_id,
        error,
        ' '.join('%s=%s' % (k, v) for k, v in extra.items()),
    )


def summarize_api_payload(payload):
    if not isinstance(payload, dict):
        return str(payload)[:200]
    safe = {k: v for k, v in payload.items() if k not in ('file', 'access_token', 'token')}
    if 'file' in payload:
        safe['file'] = '<binary>'
    return str(safe)[:500]
