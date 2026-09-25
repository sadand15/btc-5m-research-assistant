"""Stable JSON and identifiers, with no implicit clock or process environment."""
import hashlib
import json
import re
from decimal import Decimal


def decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError('nonfinite decimal')
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False, default=lambda x: decimal_text(x) if isinstance(x, Decimal) else _unsupported())


def _unsupported():
    raise TypeError('unsupported serialization type')


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def identifier(value: str) -> str:
    if (not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value)
            or re.search(r'(?i)pred_sk_|gh[pousr]_|github_pat_|bearer|authorization|cookie|secret|password|api.?key', value)):
        raise ValueError('unsafe or invalid identifier')
    return value


def timestamp(value) -> bool:
    return type(value) is int and 0 <= value <= 253402300799999
