"""Pure, explicit-clock M10 interface. Signals are research labels, never orders.

Caller-supplied probability/calibration evidence is not model inference. Policies
are mandatory and have no production defaults. Gross probability-minus-ask gaps
are descriptive gates, not execution prices, fees, expected PnL or trade advice.
OFFLINE is an explicit caller provenance assertion, not a live-data ingestion path.
"""
from dataclasses import asdict, dataclass
from decimal import Decimal

from btc5_v3.encoding import digest, identifier, timestamp
from btc5_v3.m8.models import fixed_decimal

D = Decimal


def number(value):
    return isinstance(value, Decimal) and value.is_finite()


def probability(value):
    return number(value) and D(0) <= value <= D(1)


@dataclass(frozen=True)
class AssistantPolicy:
    min_gross_edge: Decimal
    max_spread: Decimal
    min_visible_depth: Decimal
    max_source_age_ms: int
    max_receipt_age_ms: int
    max_prediction_age_ms: int
    min_tte_ms: int
    max_tte_ms: int
    min_confidence: Decimal

    def __post_init__(self):
        if not probability(self.min_gross_edge) or self.min_gross_edge <= 0:
            raise ValueError('min_gross_edge must be positive')
        if not probability(self.max_spread) or not probability(self.min_confidence):
            raise ValueError('invalid probability policy')
        if not number(self.min_visible_depth) or self.min_visible_depth <= 0:
            raise ValueError('invalid depth policy')
        values = (self.max_source_age_ms, self.max_receipt_age_ms,
                  self.max_prediction_age_ms, self.min_tte_ms, self.max_tte_ms)
        if any(not timestamp(v) for v in values) or self.max_tte_ms < self.min_tte_ms:
            raise ValueError('invalid time policy')

    @property
    def hash(self):
        return digest(asdict(self))


@dataclass(frozen=True)
class AssistantInput:
    """Each visible depth is the minimum across that side's bid and ask depth.

    Calibration/quality are explicit evidence assertions supplied by the caller;
    this presentation contract does not certify or infer either assertion.
    """
    experiment_id: str
    market_id: str
    snapshot_id: str
    prediction_snapshot_id: str
    origin: str
    outcome_mapping: str
    source_at: int | None
    received_at: int | None
    available_at: int | None
    prediction_available_at: int | None
    settles_at: int | None
    p_up: Decimal | None
    p_down: Decimal | None
    confidence: Decimal | None
    calibration_version: str | None
    calibration_passed: bool | None
    quality_passed: bool | None
    yes_bid: Decimal | None
    yes_ask: Decimal | None
    no_bid: Decimal | None
    no_ask: Decimal | None
    yes_visible_depth: Decimal | None
    no_visible_depth: Decimal | None


@dataclass(frozen=True)
class AssistantResult:
    policy_hash: str
    as_of: int
    experiment_id: str | None
    market_id: str | None
    snapshot_id: str | None
    prediction_snapshot_id: str | None
    origin: str | None
    outcome_mapping: str | None
    signal: str
    gate_reasons: tuple[str, ...]
    p_up: Decimal | None
    p_down: Decimal | None
    confidence: Decimal | None
    calibration_version: str | None
    calibration_passed: bool | None
    quality_passed: bool | None
    source_age_ms: int | None
    receipt_age_ms: int | None
    prediction_age_ms: int | None
    yes_spread: Decimal | None
    no_spread: Decimal | None
    yes_visible_depth: Decimal | None
    no_visible_depth: Decimal | None
    tte_ms: int | None
    up_gross_edge: Decimal | None
    down_gross_edge: Decimal | None


@fixed_decimal
def evaluate(item: AssistantInput, policy: AssistantPolicy, *, as_of: int) -> AssistantResult:
    """Return WAIT for missing/invalid evidence. Invalid clock/config is an error.

    All gate boundaries are inclusive; either side's bad spread/depth blocks both
    labels. No dependency on clocks, files, sockets, future quotes or settlement.
    """
    if not isinstance(item, AssistantInput) or not isinstance(policy, AssistantPolicy):
        raise TypeError('explicit assistant contracts required')
    if not timestamp(as_of):
        raise ValueError('invalid as_of timestamp')
    reasons = []
    if item.origin not in ('SYNTHETIC_TEST', 'MOCK', 'OFFLINE'):
        reasons.append('UNSUPPORTED_ORIGIN')
    if item.outcome_mapping != 'YES_UP':
        reasons.append('TARGET_MAPPING')
    identities = []
    for value in (item.experiment_id, item.market_id, item.snapshot_id, item.prediction_snapshot_id):
        try:
            identities.append(identifier(value))
        except (TypeError, ValueError):
            identities.append(None)
    if None in identities or item.snapshot_id != item.prediction_snapshot_id:
        reasons.append('IDENTITY_BINDING')
    times = (item.source_at, item.received_at, item.available_at,
             item.prediction_available_at, item.settles_at)
    source_age = receipt_age = prediction_age = tte = None
    if not all(timestamp(v) for v in times):
        reasons.append('MISSING_OR_INVALID_TIME')
    elif not (item.source_at <= item.received_at <= item.available_at
              <= item.prediction_available_at <= as_of and item.source_at < item.settles_at):
        reasons.append('NONCAUSAL_TIME')
    else:
        source_age = as_of - item.source_at
        receipt_age = as_of - item.received_at
        prediction_age = as_of - item.prediction_available_at
        tte = item.settles_at - as_of
        if source_age > policy.max_source_age_ms or receipt_age > policy.max_receipt_age_ms:
            reasons.append('STALE_DATA')
        if prediction_age > policy.max_prediction_age_ms:
            reasons.append('STALE_PREDICTION')
        if tte <= 0 or not policy.min_tte_ms <= tte <= policy.max_tte_ms:
            reasons.append('TTE_OUT_OF_RANGE')
    p_up = item.p_up if probability(item.p_up) else None
    p_down = item.p_down if probability(item.p_down) else None
    if p_up is None or p_down is None or p_up + p_down != 1:
        reasons.append('INVALID_PROBABILITY')
    confidence = item.confidence if probability(item.confidence) else None
    if confidence is None or confidence < policy.min_confidence:
        reasons.append('CONFIDENCE_GATE')
    calibration_version = None
    try:
        calibration_version = identifier(item.calibration_version)
    except (TypeError, ValueError):
        pass
    calibrated = item.calibration_passed is True and calibration_version is not None
    if not calibrated:
        reasons.append('CALIBRATION_GATE')
    if item.quality_passed is not True:
        reasons.append('QUALITY_GATE')
    spreads = []
    for bid, ask in ((item.yes_bid, item.yes_ask), (item.no_bid, item.no_ask)):
        if not probability(bid) or not probability(ask) or bid > ask:
            spreads.append(None)
        else:
            spreads.append(ask - bid)
    if None in spreads:
        reasons.append('INVALID_QUOTE')
    if any(v is not None and v > policy.max_spread for v in spreads):
        reasons.append('SPREAD_TOO_WIDE')
    depths = tuple(v if number(v) and v >= 0 else None
                   for v in (item.yes_visible_depth, item.no_visible_depth))
    if any(v is None or v < policy.min_visible_depth for v in depths):
        reasons.append('INSUFFICIENT_LIQUIDITY')
    up_edge = p_up - item.yes_ask if p_up is not None and spreads[0] is not None else None
    down_edge = p_down - item.no_ask if p_down is not None and spreads[1] is not None else None
    if up_edge is None or down_edge is None or max(up_edge, down_edge) < policy.min_gross_edge:
        reasons.append('EDGE_TOO_SMALL')
    elif up_edge == down_edge:
        reasons.append('AMBIGUOUS_DIRECTION')
    signal = 'WAIT' if reasons else ('UP' if up_edge > down_edge else 'DOWN')
    return AssistantResult(policy.hash, as_of, *identities,
                           item.origin if item.origin in ('SYNTHETIC_TEST', 'MOCK', 'OFFLINE') else None,
                           'YES_UP' if item.outcome_mapping == 'YES_UP' else None,
                           signal, tuple(reasons), p_up, p_down,
                           confidence, calibration_version,
                           item.calibration_passed if type(item.calibration_passed) is bool else None,
                           item.quality_passed if type(item.quality_passed) is bool else None,
                           source_age, receipt_age, prediction_age, *spreads, *depths,
                           tte, up_edge, down_edge)
