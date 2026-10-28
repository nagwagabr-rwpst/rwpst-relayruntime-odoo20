# -*- coding: utf-8 -*-
"""
Module-level constants for relayruntime.

Kept free of Odoo model/service imports so models can load without
pulling in the full provider stack at registry init time.
"""

PROVIDER_SELECTION_LABELS = [
    ('green_api', 'Green API'),
    ('mock_provider', 'Mock Provider (Test Mode)'),
    ('meta_cloud', 'Meta WhatsApp Cloud API'),
    ('evolution', 'Evolution API'),
    ('ultramsg', 'UltraMsg'),
    ('twilio', 'Twilio WhatsApp'),
    ('gupshup', 'Gupshup'),
    ('custom', 'Custom Internal API'),
]

# Provider brand names stay English; status labels are user-facing UX (exported via selection i18n).
PROVIDER_STATUS_SELECTION = [
    ('healthy', 'Healthy'),
    ('degraded', 'Degraded'),
    ('disconnected', 'Disconnected'),
]

# Execution-attempt lease and heartbeat (minimal runtime coordination).
EXECUTION_LEASE_MINUTES = 15
EXECUTION_STALE_MINUTES = 30
EXECUTION_HEARTBEAT_EVERY_N_RECIPIENTS = 5
EXECUTION_HEARTBEAT_MIN_INTERVAL_SECONDS = 45
EXECUTION_CAMPAIGN_PROGRESS_EVERY_N_RECIPIENTS = 1
