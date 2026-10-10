"""Pure tie-aware selection evaluation.

This module computes a signal only after the caller supplies independently
verified market, prediction, calibration, quote and causal evidence.  It has
no network, clock, file, account, or order access.  Missing evidence is a
visible ``WAIT`` and is never filled with defaults.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import FrozenSet

D = Decimal
ZERO = D("0")
ONE = D("1")


def finite(value):
    return isinstance(value, D) and value.is_finite()


def nonnegative(value):
    return finite(value) and value >= ZERO


@dataclass(frozen=True)
class DecisionPolicy:
    min_edge: D
    max_spread: D
    min_depth: D
    min_tte_ms: int
    max_tte_ms: int
    max_quote_age_ms: int = 15_000

    def __post_init__(self):
        if not finite(self.min_edge) or self.min_edge < ZERO:
            raise ValueError("invalid min_edge")
        if not finite(self.max_spread) or self.max_spread < ZERO:
            raise ValueError("invalid max_spread")
        if not nonnegative(self.min_depth):
            raise ValueError("invalid min_depth")
        if any(type(x) is not int for x in (self.min_tte_ms, self.max_tte_ms, self.max_quote_age_ms)):
            raise ValueError("invalid TTE")
        if self.min_tte_ms < 0 or self.max_tte_ms < self.min_tte_ms:
            raise ValueError("invalid TTE range")
        if self.max_quote_age_ms <= 0:
            raise ValueError("invalid quote age")


@dataclass(frozen=True)
class DecisionInput:
    as_of: int
    market_id: str | None
    market_start: int | None
    market_end: int | None
    market_rule_hash: str | None
    token_mapping: str | None
    target_contract_hash: str | None
    source_at: int | None
    received_at: int | None
    available_at: int | None
    prediction_generated_at: int | None
    prediction_expires_at: int | None
    p_up: D | None
    p_down: D | None
    p_tie: D | None
    calibration_verified: bool
    quality_verified: bool
    approval_digest: str | None
    approved_digests: FrozenSet[str]
    yes_bid: D | None
    yes_ask: D | None
    no_bid: D | None
    no_ask: D | None
    yes_depth: D | None
    no_depth: D | None
    fee_per_share: D | None
    slippage_per_share: D | None
    origin: str


@dataclass(frozen=True)
class Decision:
    signal: str
    state: str
    reasons: tuple[str, ...]
    probabilities: tuple[D | None, D | None, D | None]
    up_edge: D | None
    down_edge: D | None
    tte_ms: int | None
    origin: str
    market_id: str | None
    generated_at: int | None


def _valid_id(value):
    return isinstance(value, str) and bool(value.strip())


def evaluate(item: DecisionInput, policy: DecisionPolicy) -> Decision:
    """Return ``WAIT`` with ``NOT_EVALUATED`` unless every binding is verified."""
    if not isinstance(item, DecisionInput) or not isinstance(policy, DecisionPolicy):
        raise TypeError("explicit decision contracts required")
    reasons = []
    gates = []
    p = (item.p_up, item.p_down, item.p_tie)
    if not all(finite(x) and ZERO <= x <= ONE for x in p) or sum(p, ZERO) != ONE:
        reasons.append("INVALID_THREE_CLASS_PROBABILITY")
    if item.origin not in {"SYNTHETIC_TEST", "MOCK", "REAL_VERIFIED"}:
        reasons.append("UNKNOWN_ORIGIN")
    if item.origin == "REAL_VERIFIED" and not item.approval_digest:
        reasons.append("MISSING_APPROVAL_DIGEST")
    # The input's allowlist is suitable only for fixtures, never real approval.
    # No independently verified real predictor registry exists yet.
    if item.origin == "REAL_VERIFIED":
        reasons.append("REAL_PREDICTOR_REGISTRY_UNAVAILABLE")
    if item.approval_digest not in item.approved_digests:
        reasons.append("PREDICTION_APPROVAL_NOT_VERIFIED")
    for name, value in (("market_id", item.market_id), ("market_rule_hash", item.market_rule_hash),
                        ("token_mapping", item.token_mapping), ("target_contract_hash", item.target_contract_hash)):
        if not _valid_id(value):
            reasons.append("MISSING_" + name.upper())
    if item.token_mapping not in {"YES_UP_NO_DOWN_HALF_TIE", "YES_UP_NO_DOWN_STRICT"}:
        reasons.append("AMBIGUOUS_TOKEN_MAPPING")
    times = (item.as_of, item.market_start, item.market_end, item.source_at, item.received_at,
             item.available_at, item.prediction_generated_at, item.prediction_expires_at)
    if not all(type(x) is int and x >= 0 for x in times):
        reasons.append("MISSING_TIME_BINDING")
        tte = None
    else:
        tte = item.market_end - item.as_of
        if item.market_start % 300_000 or item.market_end - item.market_start != 300_000:
            reasons.append("NOT_UTC_5M_MARKET")
        if not item.market_start <= item.prediction_generated_at <= item.as_of < item.market_end:
            reasons.append("PREDICTION_OUTSIDE_MARKET")
        if not (item.source_at <= item.received_at <= item.available_at <= item.prediction_generated_at <= item.as_of):
            reasons.append("NONCAUSAL_PREDICTION_TIME")
        if item.as_of >= item.prediction_expires_at:
            reasons.append("PREDICTION_EXPIRED")
        if not item.prediction_generated_at < item.prediction_expires_at <= item.market_end:
            reasons.append("INVALID_PREDICTION_VALIDITY")
        if item.as_of - item.source_at > policy.max_quote_age_ms:
            reasons.append("STALE_QUOTE")
        if not policy.min_tte_ms <= tte <= policy.max_tte_ms:
            gates.append("TTE_OUT_OF_RANGE")
    if item.calibration_verified is not True:
        reasons.append("CALIBRATION_NOT_VERIFIED")
    if item.quality_verified is not True:
        reasons.append("DATA_QUALITY_NOT_VERIFIED")
    for name, value in (("fee_per_share", item.fee_per_share), ("slippage_per_share", item.slippage_per_share)):
        if not nonnegative(value):
            reasons.append("MISSING_" + name.upper())
    quotes = (item.yes_bid, item.yes_ask, item.no_bid, item.no_ask)
    if not all(finite(x) and ZERO <= x <= ONE for x in quotes) or item.yes_bid > item.yes_ask or item.no_bid > item.no_ask:
        reasons.append("INVALID_MARKET_QUOTE")
    spreads = ((item.yes_ask - item.yes_bid) if not "INVALID_MARKET_QUOTE" in reasons else None,
               (item.no_ask - item.no_bid) if not "INVALID_MARKET_QUOTE" in reasons else None)
    if spreads[0] is not None and (spreads[0] > policy.max_spread or spreads[1] > policy.max_spread):
        gates.append("SPREAD_TOO_WIDE")
    if not nonnegative(item.yes_depth) or not nonnegative(item.no_depth):
        reasons.append("INVALID_LIQUIDITY")
    elif item.yes_depth < policy.min_depth or item.no_depth < policy.min_depth:
        gates.append("LIQUIDITY_TOO_LOW")
    if reasons:
        return Decision("WAIT", "NOT_EVALUATED", tuple(dict.fromkeys(reasons + gates)), p, None, None, tte, item.origin, item.market_id, item.prediction_generated_at)
    cost = item.fee_per_share + item.slippage_per_share if nonnegative(item.fee_per_share) and nonnegative(item.slippage_per_share) else None
    tie_payout = item.p_tie * D(".5") if item.token_mapping == "YES_UP_NO_DOWN_HALF_TIE" else ZERO
    up_edge = item.p_up + tie_payout - item.yes_ask - cost
    down_edge = item.p_down + tie_payout - item.no_ask - cost
    if up_edge is None or down_edge is None or max(up_edge, down_edge) < policy.min_edge:
        gates.append("EDGE_TOO_SMALL_OR_UNAVAILABLE")
    elif up_edge == down_edge:
        gates.append("AMBIGUOUS_DIRECTION")
    if gates:
        return Decision("WAIT", "EVALUATED", tuple(dict.fromkeys(gates)), p, up_edge, down_edge, tte, item.origin, item.market_id, item.prediction_generated_at)
    return Decision("UP" if up_edge > down_edge else "DOWN", "EVALUATED", (), p, up_edge, down_edge, tte, item.origin, item.market_id, item.prediction_generated_at)
