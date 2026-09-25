from dataclasses import asdict, dataclass
from decimal import Decimal
import re

from btc5_v3.encoding import digest, identifier
from btc5_v3.edge.numeric import number


@dataclass(frozen=True)
class DecisionConfig:
    market_id: str
    source: str
    feed: str
    rule_hash: str
    outcome_mapping: str
    prediction_target_source: str
    expected_model_hash: str
    expected_edge_config_hash: str
    target_source_confirmed: bool = False
    semantic_contract_hash: str | None = None
    max_receipt_age_ms: int = 2000
    max_source_age_ms: int = 3000
    max_market_status_age_ms: int = 5000
    min_time_to_expiry_ms: int = 10000
    max_absolute_spread: Decimal = Decimal('.05')
    max_normalized_spread: Decimal | None = None
    minimum_executable_fraction: Decimal = Decimal('.8')
    minimum_executable_shares: Decimal | None = None
    require_reference_price: bool = False
    require_basis: bool = False
    max_basis_bps: Decimal | None = None
    max_reference_age_ms: int = 3000
    expected_edge_version: str = 'edge-v1'
    decision_version: str = 'decision-v1'
    gate_order_version: str = 'm3-gates-v1'
    assumptions: str = 'pre-registered-research-not-optimized'

    def __post_init__(self):
        for name in ('market_id','source','feed','rule_hash','prediction_target_source'):
            identifier(getattr(self, name))
        for value in (self.expected_model_hash, self.expected_edge_config_hash):
            if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
                raise ValueError('expected SHA256 binding')
        if self.outcome_mapping not in ('YES_UP', 'YES_DOWN'):
            raise ValueError('unsupported mapping')
        for name in ('target_source_confirmed','require_reference_price','require_basis'):
            if type(getattr(self, name)) is not bool:
                raise ValueError('explicit boolean required')
        if self.semantic_contract_hash is not None:
            if not isinstance(self.semantic_contract_hash, str) or not re.fullmatch('[0-9a-f]{64}', self.semantic_contract_hash):
                raise ValueError('invalid semantic contract hash')
        if self.target_source_confirmed and self.semantic_contract_hash is None:
            raise ValueError('confirmation requires a versioned semantic contract')
        for name in ('max_receipt_age_ms','max_source_age_ms','max_market_status_age_ms',
                     'min_time_to_expiry_ms','max_reference_age_ms'):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= 86400000:
                raise ValueError('invalid duration')
        for name, maximum in (('max_absolute_spread',1), ('max_normalized_spread',Decimal('1e18')),
                              ('minimum_executable_fraction',1), ('minimum_executable_shares',Decimal('1e18')),
                              ('max_basis_bps',Decimal('1e18'))):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, number(value, minimum=0, maximum=maximum))
        if self.max_absolute_spread is None or self.minimum_executable_fraction is None or self.minimum_executable_fraction <= 0:
            raise ValueError('required positive executable fraction and spread limit')
        if self.require_basis != (self.max_basis_bps is not None):
            raise ValueError('basis requirement and threshold must be specified together')
        if (self.expected_edge_version != 'edge-v1' or self.decision_version != 'decision-v1'
                or self.gate_order_version != 'm3-gates-v1' or self.assumptions != 'pre-registered-research-not-optimized'):
            raise ValueError('unsupported policy version')

    @property
    def hash(self):
        return digest(asdict(self))
