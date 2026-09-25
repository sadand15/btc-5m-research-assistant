"""Versioned simulation assumptions; not verified venue economics."""
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from btc5_v3.encoding import digest, identifier
from btc5_v3.edge.numeric import number


@dataclass(frozen=True)
class FeeModel:
    denomination: str = 'COLLATERAL'
    rate: Decimal = Decimal('0')
    collateral_per_share: Decimal = Decimal('0')
    version: str = 'simulation-fee-v1'

    def __post_init__(self):
        if self.denomination not in ('COLLATERAL', 'SHARES'):
            raise ValueError('unsupported fee denomination')
        identifier(self.version)
        object.__setattr__(self, 'rate', number(self.rate, minimum=0, maximum=1))
        object.__setattr__(self, 'collateral_per_share', number(self.collateral_per_share, minimum=0, maximum=1))
        if self.denomination == 'SHARES' and self.collateral_per_share != 0:
            raise ValueError('share fee cannot also specify collateral fee')


@dataclass(frozen=True)
class EdgeConfig:
    target_shares: Decimal = Decimal('1')
    minimum_net_edge_per_share: Decimal = Decimal('0.01')
    fee: FeeModel = field(default_factory=FeeModel)
    latency_cost_assumption: Decimal = Decimal('0')
    extra_cost_assumption: Decimal = Decimal('0')
    minimum_executable_fraction: Decimal = Decimal('1')
    split_treatment: str = 'IGNORE_SPLIT_EXPLICIT_PROXY'
    assumptions_version: str = 'simulation-costs-v1'
    edge_version: str = 'edge-v1'
    numeric_policy: str = 'decimal80-half-even-output18-v1'
    threshold_provenance: str = 'placeholder-research-not-empirically-optimized'

    def __post_init__(self):
        limits = {'target_shares': (0, Decimal('1e18')),
                  'minimum_net_edge_per_share': (-1, 1),
                  'latency_cost_assumption': (0, 1), 'extra_cost_assumption': (0, 1),
                  'minimum_executable_fraction': (0, 1)}
        for name, (low, high) in limits.items():
            object.__setattr__(self, name, number(getattr(self, name), minimum=low, maximum=high))
        if self.target_shares <= 0 or self.minimum_executable_fraction <= 0:
            raise ValueError('quantity and executable fraction must be positive')
        if not isinstance(self.fee, FeeModel):
            raise ValueError('explicit fee model required')
        if (self.split_treatment != 'IGNORE_SPLIT_EXPLICIT_PROXY' or self.edge_version != 'edge-v1'
                or self.numeric_policy != 'decimal80-half-even-output18-v1'
                or self.threshold_provenance != 'placeholder-research-not-empirically-optimized'):
            raise ValueError('unsupported edge policy')
        identifier(self.assumptions_version)

    @property
    def hash(self):
        return digest(asdict(self))

    @classmethod
    def from_dict(cls, value):
        value = dict(value)
        value['fee'] = FeeModel(**value['fee'])
        return cls(**value)


@dataclass(frozen=True)
class CostBreakdown:
    best_ask: Decimal
    mid: Decimal
    spread_half_cost: Decimal
    depth_vwap: Decimal
    depth_cost_per_share: Decimal
    fee_per_share: Decimal
    fee_denomination: str
    fee_collateral_total: Decimal
    fee_shares_total: Decimal
    assumed_latency_cost_per_share: Decimal
    assumed_extra_cost_per_share: Decimal
    total_cost_basis: Decimal
    collateral_spent: Decimal
    gross_shares: Decimal
    net_shares: Decimal
    assumptions_version: str
    fee_version: str
    economics_status: str = 'SIMULATION_ASSUMPTIONS'
    cost_unit: str = 'collateral/gross_executed_share'
