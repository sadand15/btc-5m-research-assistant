"""Explicit immutable research contracts; no implicit clocks or data discovery."""
from dataclasses import dataclass, field, asdict, replace
from decimal import Decimal
import json
import re
from functools import wraps
from decimal import localcontext
from btc5_v3.edge.numeric import CONTEXT

from btc5_v3.encoding import canonical, digest, identifier, timestamp
from btc5_v3.edge.costs import EdgeConfig
from btc5_v3.decision.config import DecisionConfig
from btc5_v3.execution.models import ExecutionConfig, ExitPolicy
from btc5_v3.risk.models import RiskConfig
from btc5_v3.analytics.models import AnalyticsConfig

D = Decimal
APPROVED = 'e4b67ed728073864a6cc809d26ad6f23c822c973'


def fixed_decimal(function):
    @wraps(function)
    def wrapped(*args,**kwargs):
        with localcontext(CONTEXT):return function(*args,**kwargs)
    return wrapped


@dataclass(frozen=True)
class Baseline:
    source_git: str = APPROVED
    model_hash: str = digest('synthetic-risk-model')
    model_version: str = 'synthetic-risk-model'
    feature_hash: str = 'b'*64
    feature_version: str = 'synthetic-features'
    calibration_version: str = 'none'
    edge: EdgeConfig = field(default_factory=lambda: EdgeConfig(target_shares=D(100)))
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    policy: ExitPolicy = field(default_factory=ExitPolicy)
    analytics: AnalyticsConfig = field(default_factory=AnalyticsConfig)
    max_spread: Decimal = D('.05')
    variant: str = 'BASELINE'

    def __post_init__(self):
        if self.source_git != APPROVED: raise ValueError('unapproved source baseline')
        for x in (self.model_hash, self.feature_hash):
            if not re.fullmatch('[0-9a-f]{64}', x): raise ValueError('invalid binding')
        identifier(self.calibration_version);identifier(self.variant)
        if not D(0) <= self.max_spread <= 1: raise ValueError('invalid spread')

    def decision(self, market):
        return DecisionConfig(market, 'synthetic', 'SYNTHETIC', 'synthetic-rule-v1', 'YES_UP',
                              'synthetic-oracle', self.model_hash, self.edge.hash,
                              target_source_confirmed=True, semantic_contract_hash=digest('SYNTHETIC_ONLY'),
                              max_absolute_spread=self.max_spread)

    def configuration(self):
        return dict(asdict(self),decision_template=asdict(self.decision('M8_TEMPLATE')))

    @property
    def hash(self): return digest(self.configuration())

    def ensure_frozen(self):
        if self != Baseline(): raise ValueError('validation requires exact frozen baseline')


@dataclass(frozen=True)
class DatasetManifest:
    dataset_id: str
    role: str
    time_start: int
    time_end: int
    source: str
    created_at: int
    payload_hash: str
    evidence_mode: str = 'SYNTHETIC'
    quality_status: str = 'NOT_EVALUATED'
    cadence_ms: int | None = None

    def __post_init__(self):
        identifier(self.dataset_id);identifier(self.source)
        if self.role not in ('DEVELOPMENT','VALIDATION','BLIND'): raise ValueError('explicit dataset role required')
        if not all(timestamp(t) for t in (self.time_start,self.time_end,self.created_at)) or self.time_start>self.time_end:
            raise ValueError('invalid dataset window')
        if not re.fullmatch('[0-9a-f]{64}',self.payload_hash): raise ValueError('payload hash required')
        if self.evidence_mode!='SYNTHETIC': raise ValueError('real settlement adapter unsupported')
        if self.quality_status!='NOT_EVALUATED': raise ValueError('manifest cannot certify quality')
        if self.cadence_ms is not None and (type(self.cadence_ms) is not int or self.cadence_ms<=0):
            raise ValueError('invalid cadence')
        if self.cadence_ms and (self.time_end-self.time_start)//self.cadence_ms>100000:
            raise ValueError('coverage budget exceeded')

    @property
    def hash(self): return digest(asdict(self))


@dataclass(frozen=True)
class Dataset:
    manifest: DatasetManifest
    records_json: str

    def __post_init__(self):
        # Deny blind before deserialization, iteration, hashing or numeric inspection.
        if self.manifest.role=='BLIND': raise PermissionError('blind payload access prohibited')
        rows=json.loads(self.records_json)
        if not isinstance(rows,list) or len(rows)>2000: raise ValueError('bounded record list required')
        if canonical(rows)!=self.records_json or digest(rows)!=self.manifest.payload_hash: raise ValueError('dataset integrity failure')
        ids=[];order=[]
        for r in rows:
            identifier(r['id']);ids.append(r['id'])
            if not timestamp(r['at']) or not self.manifest.time_start<=r['at']<=self.manifest.time_end:
                raise ValueError('record outside manifest')
            if type(r['sequence']) is not int or r['sequence']<0: raise ValueError('invalid sequence')
            order.append((r['at'],r['sequence']))
        if len(ids)!=len(set(ids)) or len(order)!=len(set(order)): raise ValueError('duplicate record identity/order')

    def records(self):return sorted(json.loads(self.records_json),key=lambda r:(r['at'],r['sequence'],r['id']))


def dataset(identity,role,records,*,source='explicit-synthetic-fixture',cadence_ms=None):
    """Fixture/helper factory. External data require an explicit independently supplied manifest."""
    if role=='BLIND': raise PermissionError('blind payload access prohibited')
    times=[r['at'] for r in records]
    return Dataset(DatasetManifest(identity,role,min(times),max(times),source,max(times),digest(records),
                                   cadence_ms=cadence_ms),canonical(records))


def time_split(development,validation):
    if development.manifest.role!='DEVELOPMENT' or validation.manifest.role!='VALIDATION': raise ValueError('explicit ordered roles required')
    if development.manifest.time_end>=validation.manifest.time_start: raise ValueError('overlapping chronological split')
    def markets(d):return {r.get('raw',{}).get('market_id') for r in d.records()}
    if (markets(development)&markets(validation))-{None}: raise ValueError('market leakage across split')


def normalized(value):return json.loads(canonical(value))
