from dataclasses import asdict, dataclass, field
from decimal import Decimal
import json
import re

from btc5_v3.encoding import canonical, digest, identifier, timestamp
from btc5_v3.edge.numeric import number


@dataclass(frozen=True)
class AnalyticsConfig:
    calibration_bin_edges: tuple = tuple(Decimal(i)/10 for i in range(11))
    edge_bucket_edges: tuple = (Decimal(0),Decimal('.02'),Decimal('.05'),Decimal('.10'),Decimal('.15'))
    tte_bucket_edges_ms: tuple = (0,30000,60000,120000,180000)
    threshold_grid: tuple = tuple(map(Decimal,('.02','.03','.05','.07','.10','.15')))
    cost_multiplier_grid: tuple = tuple(map(Decimal,('1','1.5','2','3')))
    cost_stress_threshold: Decimal = Decimal('.01')
    minimum_sample_count: int = 20
    log_loss_epsilon: Decimal = Decimal('0.000000000001')
    outcome_source: str = 'synthetic-settlement'
    settlement_version: str = 'synthetic-settlement-v1'
    split_handling: str = 'PAYOUT_BRIER_BINARY_CALIBRATION_SPLIT_SEPARATE'
    inclusion_rule: str = 'ONE_EXPLICIT_ROW_PER_PREDICTION_AVAILABLE_BY_CUTOFF'
    cost_stress_rule: str = 'SCALE_FEES_LATENCY_EXTRA_NOT_BOOK_PRICE'
    analysis_version: str = 'analytics-v1'

    def __post_init__(self):
        fixed = {'edge_bucket_edges':('0','.02','.05','.10','.15'),
                 'threshold_grid':('.02','.03','.05','.07','.10','.15'),
                 'cost_multiplier_grid':('1','1.5','2','3')}
        for name in ('calibration_bin_edges',*fixed):
            values=tuple(number(x) for x in getattr(self,name))
            object.__setattr__(self,name,values)
            if name in fixed and values!=tuple(map(Decimal,fixed[name])):
                raise ValueError('v1 sensitivity/bucket grids are preregistered and fixed')
        if self.calibration_bin_edges!=tuple(Decimal(i)/10 for i in range(11)):
            raise ValueError('v1 uses fixed ten calibration bins')
        object.__setattr__(self,'tte_bucket_edges_ms',tuple(self.tte_bucket_edges_ms))
        if self.tte_bucket_edges_ms!=(0,30000,60000,120000,180000):
            raise ValueError('v1 TTE grid is fixed')
        if type(self.minimum_sample_count) is not int or self.minimum_sample_count<3:
            raise ValueError('minimum sample count must be >=3')
        object.__setattr__(self,'cost_stress_threshold',number(self.cost_stress_threshold))
        if self.cost_stress_threshold!=Decimal('.01'):raise ValueError('v1 cost stress uses a fixed .01 research threshold')
        object.__setattr__(self,'log_loss_epsilon',number(self.log_loss_epsilon,minimum=Decimal('1e-18'),maximum=Decimal('.01')))
        identifier(self.outcome_source);identifier(self.settlement_version)
        if (self.split_handling!='PAYOUT_BRIER_BINARY_CALIBRATION_SPLIT_SEPARATE'
                or self.inclusion_rule!='ONE_EXPLICIT_ROW_PER_PREDICTION_AVAILABLE_BY_CUTOFF'
                or self.cost_stress_rule!='SCALE_FEES_LATENCY_EXTRA_NOT_BOOK_PRICE' or self.analysis_version!='analytics-v1'):
            raise ValueError('unsupported analytics policy')

    @property
    def hash(self):return digest(asdict(self))


@dataclass(frozen=True)
class ResolvedOutcome:
    experiment_id: str
    market_id: str
    resolution_at: int
    available_at: int
    yes_payout: Decimal
    source: str
    rule_hash: str
    settlement_version: str
    semantics: str = 'SYNTHETIC_RESEARCH'
    outcome_id: str = field(init=False)

    def __post_init__(self):
        for x in (self.experiment_id,self.market_id,self.source,self.rule_hash,self.settlement_version):identifier(x)
        if not timestamp(self.resolution_at) or not timestamp(self.available_at) or self.available_at<self.resolution_at:
            raise ValueError('invalid resolution availability')
        value=number(self.yes_payout)
        if value not in (Decimal(0),Decimal('.5'),Decimal(1)):raise ValueError('binary/split payout required')
        if self.semantics!='SYNTHETIC_RESEARCH':raise ValueError('real settlement semantics not implemented')
        object.__setattr__(self,'yes_payout',value)
        object.__setattr__(self,'outcome_id',digest([self.experiment_id,self.market_id,self.settlement_version]))

    def to_json(self):return canonical(asdict(self))

    @classmethod
    def from_dict(cls,value):
        value=dict(value);identity=value.pop('outcome_id');result=cls(**value)
        if identity!=result.outcome_id:raise ValueError('outcome identity mismatch')
        return result


@dataclass(frozen=True)
class ResearchObservation:
    """An explicit immutable archive of upstream records, not a latest-row query.

    Policy evaluation remains in M1-M3. The archive contains all original JSON,
    making analytical input fingerprints independent of later database additions.
    """
    payload_json: str
    input_hash: str = field(init=False)

    def __post_init__(self):
        data=json.loads(self.payload_json)
        if set(data)!={'prediction','snapshot','edge','decision'} or not isinstance(data['prediction'],dict):
            raise ValueError('explicit prediction archive required')
        if canonical(data)!=self.payload_json:raise ValueError('noncanonical observation')
        p=data['prediction']
        from btc5_v3.models.models import Prediction
        if Prediction.from_dict(p).to_json()!=canonical(p):raise ValueError('prediction archive integrity failure')
        identifier(p['experiment_id']);identifier(p['market_id']);identifier(p['prediction_id'])
        number(p['p_yes'],minimum=0,maximum=1)
        if not timestamp(p['available_at']) or not timestamp(p['input_cutoff']) or p['input_cutoff']>p['available_at']:
            raise ValueError('invalid prediction availability')
        for name in ('snapshot','edge','decision'):
            x=data[name]
            if x is not None and (not isinstance(x,dict) or x['experiment_id']!=p['experiment_id']):
                raise ValueError('cross-experiment archive forbidden')
        object.__setattr__(self,'input_hash',digest(data))

    @classmethod
    def from_inputs(cls,prediction,snapshot=None,edge=None,decision=None):
        from btc5_v3.models.models import Prediction
        from btc5_v3.market.models import MarketSnapshot
        from btc5_v3.edge.models import EdgeEvaluation
        from btc5_v3.decision.models import Decision
        if not isinstance(prediction,Prediction):raise TypeError('Prediction required')
        for x,c in ((snapshot,MarketSnapshot),(edge,EdgeEvaluation),(decision,Decision)):
            if x is not None and not isinstance(x,c):raise TypeError('invalid upstream record')
        return cls(canonical({k:json.loads(x.to_json()) if x is not None else None
                              for k,x in (('prediction',prediction),('snapshot',snapshot),('edge',edge),('decision',decision))}))

    def data(self):return json.loads(self.payload_json)


@dataclass(frozen=True)
class AnalysisResult:
    analysis_id: str
    experiment_id: str
    code_git: str
    cutoff: int
    created_at: int
    config_hash: str
    input_hash: str
    report_json: str
    analysis_version: str = 'analytics-v1'

    def to_json(self):return canonical(asdict(self))


@dataclass(frozen=True)
class EdgeSensitivityResult:
    scenario: str
    value: Decimal
    eligible_research_observations: int
    admissible_candidates: int
    coverage: Decimal | None
    resolved_candidates: int
    mean_hypothetical_net_edge: Decimal | None
    mean_hypothetical_realized_return: Decimal | None
    rows: tuple
    edge_threshold: Decimal
    status: str = 'COUNTERFACTUAL_SENSITIVITY_NOT_OPTIMIZATION'


def validate_run_identity(experiment_id,code_git,cutoff,created_at):
    identifier(experiment_id)
    if not isinstance(code_git,str) or not re.fullmatch('[0-9a-f]{40}',code_git):raise ValueError('Git SHA required')
    if not timestamp(cutoff) or not timestamp(created_at) or created_at<cutoff:raise ValueError('invalid analysis cutoff/creation time')
