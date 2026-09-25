"""M2 fixed deterministic decimal policy, independent of ambient context."""
from decimal import Context, Decimal, ROUND_HALF_EVEN

CONTEXT = Context(prec=80, rounding=ROUND_HALF_EVEN)
QUANTUM = Decimal('0.000000000000000001')


def number(value, *, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError('invalid numeric type')
    try:
        # Float adapters get 15 significant decimal digits. Explicit Decimal/string
        # inputs retain up to 18 fractional digits; binary float noise is not an edge.
        result = Decimal(format(value, '.15g') if isinstance(value, float) else str(value))
    except Exception as exc:
        raise ValueError('invalid decimal') from exc
    if (not result.is_finite() or len(result.as_tuple().digits) > 36
            or result.as_tuple().exponent < -18 or result.adjusted() > 18
            or (minimum is not None and result < minimum)
            or (maximum is not None and result > maximum)):
        raise ValueError('nonfinite, out-of-range or excessive-precision number')
    return Decimal(0) if result == 0 else result


def rounded(value):
    return value.quantize(QUANTUM, context=CONTEXT)
