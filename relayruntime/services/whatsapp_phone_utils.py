# -*- coding: utf-8 -*-

import logging
import re

_logger = logging.getLogger(__name__)

# E.164 practical bounds (digits only, without +).
MIN_PHONE_DIGITS = 10
MAX_PHONE_DIGITS = 15
EGYPT_COUNTRY_CODE = '20'


def _digits_only(number):
    return re.sub(r'\D', '', number or '')


def _normalize_egyptian(digits):
    """Normalize common Egyptian mobile formats to 20XXXXXXXXXX."""
    if not digits:
        return digits

    if digits.startswith('00'):
        digits = digits[2:]

    # 01xxxxxxxxx (11 digits) -> 201xxxxxxxxx
    if digits.startswith('0') and len(digits) == 11 and digits[1] == '1':
        normalized = EGYPT_COUNTRY_CODE + digits[1:]
        _logger.debug('Egyptian phone normalized: %s -> %s', digits, normalized)
        return normalized

    # 1xxxxxxxxx (10 digits, missing leading 0) -> 201xxxxxxxxx
    if digits.startswith('1') and len(digits) == 10 and not digits.startswith(EGYPT_COUNTRY_CODE):
        normalized = EGYPT_COUNTRY_CODE + digits
        _logger.debug('Egyptian phone normalized: %s -> %s', digits, normalized)
        return normalized

    # Already international Egyptian
    if digits.startswith(EGYPT_COUNTRY_CODE) and len(digits) in (12, 13):
        return digits

    return digits


def normalize_phone_number(number):
    """
    Normalize a phone number for WhatsApp delivery.

    - Removes spaces and symbols
    - Preserves international country codes
    - Applies Egyptian-specific corrections
    - Returns digits only, or a full chatId if already formatted
  """
    if not number:
        return ''

    raw = number.strip()
    if '@' in raw:
        # Already a WhatsApp chat id; validate basic shape.
        local, sep, domain = raw.partition('@')
        if not sep or not local or not domain:
            _logger.debug('Malformed WhatsApp chat id rejected: %s', raw)
            return ''
        local_digits = _digits_only(local)
        if not local_digits or len(local_digits) < MIN_PHONE_DIGITS:
            return ''
        return f'{local_digits}@{domain}'

    digits = _digits_only(raw)
    if not digits:
        return ''

    if digits.startswith('00'):
        digits = digits[2:]

    digits = _normalize_egyptian(digits)

    if len(digits) < MIN_PHONE_DIGITS or len(digits) > MAX_PHONE_DIGITS:
        _logger.debug('Phone rejected (invalid length %s): %s', len(digits), raw)
        return ''

    return digits


def format_chat_id(recipient_number):
    """Build a WhatsApp chatId from a normalized number."""
    normalized = normalize_phone_number(recipient_number)
    if not normalized:
        return ''
    if '@' in normalized:
        return normalized
    return f'{normalized}@c.us'
