"""Synthetic/model-adapter input contract. No prediction engine or UP conversion."""
from dataclasses import asdict, dataclass, field
from decimal import Decimal
import re

from btc5_v3.encoding import canonical, digest, identifier, timestamp
from btc5_v3.edge.numeric import number


@dataclass(frozen=True)
class TargetDefinition:
    outcome_mapping: str
    rule_hash: str
    expiry: int
    probability_semantics: str = 'MARKET_YES'

    def __post_init__(self):
        for value in (self.outcome_mapping, self.rule_hash, self.probability_semantics):
            identifier(value)
        if not timestamp(self.expiry):
            raise ValueError('invalid target expiry')


@dataclass(frozen=True)
class Prediction:
    experiment_id: str
    prediction_key: str
    market_id: str
    p_yes: Decimal
    model_version: str
    model_hash: str
    feature_version: str
    feature_hash: str
    input_cutoff: int
    available_at: int
    target_definition: TargetDefinition
    calibration_version: str
    support_status: str = 'SUPPORTED'
    prediction_id: str = field(init=False)

    def __post_init__(self):
        for name in ('experiment_id', 'prediction_key', 'market_id', 'model_version',
                     'feature_version', 'calibration_version'):
            identifier(getattr(self, name))
        for value in (self.model_hash, self.feature_hash):
            if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
                raise ValueError('expected SHA256')
        if self.support_status not in ('SUPPORTED', 'UNSUPPORTED'):
            raise ValueError('invalid support status')
        if not isinstance(self.target_definition, TargetDefinition):
            raise ValueError('explicit target required')
        if (not timestamp(self.input_cutoff) or not timestamp(self.available_at)
                or self.input_cutoff > self.available_at):
            raise ValueError('prediction availability precedes inputs')
        object.__setattr__(self, 'p_yes', number(self.p_yes, minimum=0, maximum=1))
        object.__setattr__(self, 'prediction_id', digest({
            'experiment_id': self.experiment_id, 'prediction_key': self.prediction_key}))

    def to_json(self):
        return canonical(asdict(self))

    @classmethod
    def from_dict(cls, value):
        value = dict(value)
        identity = value.pop('prediction_id')
        value['target_definition'] = TargetDefinition(**value['target_definition'])
        result = cls(**value)
        if identity != result.prediction_id:
            raise ValueError('prediction identity integrity failure')
        return result
