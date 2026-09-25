from dataclasses import asdict, dataclass
from decimal import Decimal

from btc5_v3.encoding import canonical
from btc5_v3.edge.models import LiquidityUse


# Both gate order and reason order within a gate are explicit, never SQL/dict order.
GATES = (
    ('IDENTITY', ('EXPERIMENT_MISMATCH','MARKET_MISMATCH','PREDICTION_MISMATCH','SNAPSHOT_MISMATCH',
                  'EDGE_LINEAGE_MISMATCH','TARGET_MISMATCH','RULE_MISMATCH','FEED_MISMATCH')),
    ('AVAILABILITY', ('DATA_INCOMPLETE','SNAPSHOT_NOT_AVAILABLE','PREDICTION_NOT_AVAILABLE',
                      'EDGE_NOT_AVAILABLE','REFERENCE_NOT_AVAILABLE','STATUS_NOT_AVAILABLE')),
    ('MARKET_STATUS', ('MARKET_STATUS_UNKNOWN','MARKET_NOT_OPEN','MARKET_STATUS_STALE','MARKET_EXPIRED')),
    ('FRESHNESS', ('NEGATIVE_RECEIPT_AGE','NEGATIVE_SOURCE_AGE','STALE_RECEIPT','STALE_SOURCE')),
    ('SOURCE_RULE', ('PRICE_SOURCE_MISMATCH','TARGET_SOURCE_MISMATCH','REFERENCE_PRICE_MISSING',
                     'REFERENCE_STALE','BASIS_TOO_WIDE')),
    ('EDGE', ('UPSTREAM_NO_EDGE','EDGE_INELIGIBLE')),
    ('SPREAD', ('SPREAD_TOO_WIDE',)),
    ('LIQUIDITY', ('INVALID_REQUESTED_SHARES','INVALID_EXECUTABLE_SHARES','INSUFFICIENT_DEPTH')),
    ('NEAR_EXPIRY', ('MARKET_NEAR_SETTLEMENT',)),
    ('FINAL', ()),
)


@dataclass(frozen=True)
class GateResult:
    gate: str
    reasons: tuple[str, ...]
    status: str


@dataclass(frozen=True)
class Decision:
    decision_id: str
    attempt_key: str
    experiment_id: str
    prediction_id: str | None
    snapshot_id: str | None
    edge_id: str | None
    evaluated_at: int
    requested_action: str
    final_action: str
    primary_reason: str | None
    all_reasons: tuple[str, ...]
    source_age_ms: int | None
    receipt_age_ms: int | None
    time_to_expiry_ms: int | None
    spread: Decimal | None
    normalized_spread: Decimal | None
    requested_shares: Decimal | None
    executable_shares: Decimal | None
    executable_fraction: Decimal | None
    edge_per_share: Decimal | None
    expected_value_total: Decimal | None
    side: str | None
    liquidity_used: tuple[LiquidityUse, ...]
    liquidity_independent: bool
    basis_bps: Decimal | None
    observed_basis: Decimal | None
    market_status: str | None
    gate_results: tuple[GateResult, ...]
    upstream_reasons: tuple[str, ...]
    decision_config_hash: str
    decision_version: str
    input_hash: str
    quote_age_definition: str = 'receipt_age_ms=evaluated_at-received_at; source_age_ms separately gated'
    numeric_policy: str = 'decimal80-ratio18-cross-product-boundaries'
    purpose: str = 'RESEARCH_SIMULATION_CANDIDATE_NOT_ORDER'

    def to_json(self):
        return canonical(asdict(self))
