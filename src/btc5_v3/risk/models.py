"""Immutable, preregistered M6 contracts."""
from dataclasses import dataclass, asdict
from decimal import Decimal
import json

from btc5_v3.encoding import canonical, digest, identifier, timestamp
from btc5_v3.edge.numeric import number

D = Decimal


@dataclass(frozen=True)
class RiskConfig:
    starting_capital: Decimal = D('1000')
    max_position_notional: Decimal = D('100')
    max_position_fraction: Decimal = D('.20')
    max_total_open_exposure: Decimal = D('800')
    max_total_open_exposure_fraction: Decimal = D('.80')
    max_pending_exposure: Decimal = D('400')
    max_market_exposure: Decimal = D('200')
    max_daily_simulated_loss: Decimal = D('50')
    max_drawdown: Decimal = D('.10')
    max_consecutive_losses: int = 3
    minimum_available_cash: Decimal = D('0')
    minimum_share_unit: Decimal = D('1')
    reservation_timeout: int = 10000
    max_portfolio_age_ms: int = 30000
    max_feed_age_ms: int = 3000
    max_heartbeat_age_ms: int = 5000
    validation_failure_burst_limit: int = 3
    require_data_health: bool = True
    require_provider_health: bool = True
    loss_day_timezone: str = 'UTC'
    pause_behavior: str = 'BLOCK_NEW_ENTRY_ONLY'
    equity_basis: str = 'CASH_PLUS_REMAINING_COST_BASIS'
    version: str = 'risk-v1'

    def __post_init__(self):
        for name in ('starting_capital', 'max_position_notional', 'max_position_fraction',
                     'max_total_open_exposure', 'max_total_open_exposure_fraction',
                     'max_pending_exposure', 'max_market_exposure', 'max_daily_simulated_loss',
                     'max_drawdown', 'minimum_available_cash', 'minimum_share_unit'):
            value = number(getattr(self, name), minimum=D(0))
            if name != 'minimum_available_cash' and value == 0:
                raise ValueError('positive risk limit required')
            if name in ('max_position_fraction', 'max_total_open_exposure_fraction', 'max_drawdown') and value > 1:
                raise ValueError('fraction exceeds one')
            object.__setattr__(self, name, value)
        for name in ('max_consecutive_losses', 'reservation_timeout', 'max_portfolio_age_ms',
                     'max_feed_age_ms', 'max_heartbeat_age_ms', 'validation_failure_burst_limit'):
            if type(getattr(self, name)) is not int or not 0 < getattr(self, name) <= 86400000:
                raise ValueError('positive bounded risk count/time required')
        for name in ('require_data_health', 'require_provider_health'):
            if type(getattr(self, name)) is not bool:
                raise ValueError('explicit health requirement required')
        if (self.version != 'risk-v1' or self.loss_day_timezone != 'UTC'
                or self.pause_behavior != 'BLOCK_NEW_ENTRY_ONLY'
                or self.equity_basis != 'CASH_PLUS_REMAINING_COST_BASIS'):
            raise ValueError('unsupported risk contract')

    @property
    def hash(self):
        return digest(asdict(self))


@dataclass(frozen=True)
class HealthEvidence:
    """Explicit synthetic/replay evidence; no environment or clock is consulted."""
    available_at: int
    source_at: int | None
    heartbeat_at: int | None
    provider_healthy: bool = True
    source_matches: bool = True
    validation_failures: int = 0
    reference: str = 'synthetic-health'

    def __post_init__(self):
        if not timestamp(self.available_at):
            raise ValueError('invalid health availability')
        for name in ('source_at', 'heartbeat_at'):
            if getattr(self, name) is not None and not timestamp(getattr(self, name)):
                raise ValueError('invalid evidence timestamp')
        for name in ('provider_healthy', 'source_matches'):
            if type(getattr(self, name)) is not bool:
                raise ValueError('explicit health boolean required')
        if type(self.validation_failures) is not int or self.validation_failures < 0:
            raise ValueError('invalid validation burst')
        identifier(self.reference)


@dataclass(frozen=True)
class RiskDecision:
    risk_decision_id: str
    experiment_id: str
    decision_id: str
    evaluated_at: int
    requested_shares: Decimal
    requested_notional: Decimal
    approved_shares: Decimal
    approved_notional: Decimal
    action: str
    primary_reason: str
    all_reasons: tuple[str, ...]
    portfolio_state_id: str
    risk_config_hash: str
    risk_version: str = 'risk-v1'

    def to_json(self):
        return canonical(asdict(self))


@dataclass(frozen=True)
class CapitalReservation:
    reservation_id: str
    decision_id: str
    approved_shares: Decimal
    reserved_collateral: Decimal
    created_at: int
    expires_at: int
    status: str
    consumed_collateral: Decimal = D(0)
    released_collateral: Decimal = D(0)
    remaining_collateral: Decimal = D(0)


@dataclass(frozen=True)
class PortfolioState:
    """Immutable audit cache, reconstructed from archived ledger and events."""
    payload_json: str

    def data(self):
        return json.loads(self.payload_json)

    @property
    def portfolio_state_id(self):
        return digest(json.loads(self.payload_json))
