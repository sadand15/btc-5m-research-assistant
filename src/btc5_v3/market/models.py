from dataclasses import dataclass, asdict
from decimal import Decimal, localcontext
from enum import Enum

from btc5_v3.encoding import canonical, timestamp, identifier


class Reason(str, Enum):
    MALFORMED = 'MALFORMED'
    MISSING_BID = 'MISSING_BID'
    MISSING_ASK = 'MISSING_ASK'
    NON_FINITE = 'NON_FINITE'
    INVALID_PRICE = 'INVALID_PRICE'
    INVALID_QUANTITY = 'INVALID_QUANTITY'
    CROSSED_BOOK = 'CROSSED_BOOK'
    FUTURE_SOURCE_TIME = 'FUTURE_SOURCE_TIME'
    NEGATIVE_QUOTE_AGE = 'NEGATIVE_QUOTE_AGE'
    INVALID_TIMESTAMP = 'INVALID_TIMESTAMP'
    WRONG_MARKET = 'WRONG_MARKET'
    UNKNOWN_OUTCOME_MAPPING = 'UNKNOWN_OUTCOME_MAPPING'
    RULE_MISMATCH = 'RULE_MISMATCH'
    UNSUPPORTED_MARKET = 'UNSUPPORTED_MARKET'
    INVALID_DEPTH = 'INVALID_DEPTH'


@dataclass(frozen=True)
class RawMarketEvent:
    id: str
    experiment_id: str
    source: str
    source_at: int | None
    received_at: int
    sequence: int
    market_id: str | None
    safe_payload: str
    payload_hash: str
    schema_version: int
    redaction_status: str
    ingestion_status: str
    event_key: str
    recorded_at: int
    redaction_version: str = 'allowlist-v1'

    def __post_init__(self):
        identifier(self.experiment_id);identifier(self.source);identifier(self.event_key)
        if not timestamp(self.received_at) or not timestamp(self.recorded_at) or self.recorded_at<self.received_at:
            raise ValueError('invalid raw event envelope time')
        if type(self.sequence) is not int or not 0<=self.sequence<2**63 or self.schema_version!=1:
            raise ValueError('invalid raw event envelope sequence/schema')


@dataclass(frozen=True)
class DepthLevel:
    price: Decimal
    quantity: Decimal
    liquidity_id: str
    origin_side: str
    derived: bool


@dataclass(frozen=True, init=False)
class MarketSnapshot:
    snapshot_id: str
    raw_event_id: str
    experiment_id: str
    market_id: str
    source: str
    source_at: int
    received_at: int
    available_at: int
    sequence: int
    expiry: int
    yes_bids: tuple[DepthLevel, ...]
    yes_asks: tuple[DepthLevel, ...]
    no_bids: tuple[DepthLevel, ...]
    no_asks: tuple[DepthLevel, ...]
    feed: str
    rule_hash: str
    outcome_mapping: str
    reference_underlying_price: Decimal | None
    reference_price_at: int | None
    clock_skew_tolerance_ms: int
    validator_version: str
    config_hash: str
    price_unit: str = 'collateral/share'
    quantity_unit: str = 'shares'
    mid_definition: str = '(best_bid+best_ask)/2; descriptive, not executable'
    no_derived: bool = True
    liquidity_independent: bool = False

    def __init__(self, *args, **kwargs):
        raise TypeError('MarketSnapshot must be created by validate_market')

    @property
    def yes_bid(self): return self.yes_bids[0].price
    @property
    def yes_ask(self): return self.yes_asks[0].price
    @property
    def no_bid(self): return self.no_bids[0].price
    @property
    def no_ask(self): return self.no_asks[0].price
    @property
    def yes_mid(self):
        with localcontext() as ctx:
            ctx.prec=80
            return (self.yes_bid+self.yes_ask)/2
    @property
    def no_mid(self):
        with localcontext() as ctx:
            ctx.prec=80
            return (self.no_bid+self.no_ask)/2
    @property
    def yes_spread(self):
        with localcontext() as ctx:
            ctx.prec=80
            return self.yes_ask-self.yes_bid
    @property
    def no_spread(self):
        with localcontext() as ctx:
            ctx.prec=80
            return self.no_ask-self.no_bid
    @property
    def liquidity_groups(self):
        """Unique physical lots. NO views refer to these same lot IDs."""
        return self.yes_bids+self.yes_asks

    def to_json(self):
        return canonical(asdict(self))


@dataclass(frozen=True)
class ValidationResult:
    validation_id: str
    raw_event_id: str
    experiment_id: str
    status: str
    primary_reason: Reason | None
    all_reasons: tuple[Reason, ...]
    validator_version: str
    evaluation_at: int
    context_hash: str
    snapshot: MarketSnapshot | None


@dataclass(frozen=True)
class TemporalUsability:
    usable: bool
    quote_age_ms: int
    reasons: tuple[str, ...]


def temporal_usability(snapshot: MarketSnapshot, *, decision_at: int, max_quote_age_ms: int) -> TemporalUsability:
    if not timestamp(decision_at) or type(max_quote_age_ms) is not int or max_quote_age_ms < 0:
        raise ValueError('invalid explicit freshness parameters')
    age = decision_at-snapshot.received_at
    reasons = []
    if age < 0: reasons.append('NEGATIVE_QUOTE_AGE')
    if decision_at < snapshot.available_at: reasons.append('NOT_YET_AVAILABLE')
    if age > max_quote_age_ms: reasons.append('QUOTE_STALE')
    if decision_at >= snapshot.expiry: reasons.append('MARKET_EXPIRED')
    return TemporalUsability(not reasons, age, tuple(reasons))
