from dataclasses import asdict, dataclass
from decimal import Decimal
from btc5_v3.encoding import canonical
from btc5_v3.edge.costs import CostBreakdown


@dataclass(frozen=True)
class LiquidityUse:
    liquidity_id: str
    liquidity_origin: str
    derived: bool
    shares: Decimal
    price: Decimal


@dataclass(frozen=True)
class SideEvaluation:
    side: str
    probability: Decimal
    raw_edge: Decimal
    requested_shares: Decimal
    executable_shares: Decimal
    unfilled_shares: Decimal
    insufficient_depth: bool
    depth_vwap: Decimal
    executable_edge_before_costs: Decimal
    cost_breakdown: CostBreakdown
    net_edge_per_share: Decimal
    net_ev_total: Decimal
    liquidity_used: tuple[LiquidityUse, ...]
    eligible: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class EdgeEvaluation:
    edge_id: str
    experiment_id: str
    prediction_id: str
    snapshot_id: str
    evaluated_at: int
    p_yes: Decimal
    p_no: Decimal
    yes_mid: Decimal
    no_mid: Decimal
    requested_shares: Decimal
    receipt_age_ms: int
    source_age_ms: int
    yes: SideEvaluation | None
    no: SideEvaluation | None
    preferred_side: str | None
    candidate_action: str
    reasons: tuple[str, ...]
    config_hash: str
    edge_version: str
    split_treatment: str
    split_model: str = 'unavailable'
    scenarios: str = 'MUTUALLY_EXCLUSIVE_HYPOTHETICAL'
    ev_basis: str = 'BINARY_BUY_HOLD_PROXY_NOT_FULL_VENUE_EV'
    per_share_denominator: str = 'gross_executed_shares'

    @property
    def eligible_yes(self): return self.yes is not None and self.yes.eligible

    @property
    def eligible_no(self): return self.no is not None and self.no.eligible

    def to_json(self):
        return canonical(asdict(self))
