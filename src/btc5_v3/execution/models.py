from dataclasses import dataclass,field,asdict
from decimal import Decimal
import json

from btc5_v3.encoding import canonical,digest
from btc5_v3.edge.costs import FeeModel
from btc5_v3.edge.numeric import number

D=Decimal
LATENCY_GRID=(0,100,250,500,1000,2000)
SIZE_GRID=tuple(map(D,('1','10','50','100')))
REBOUND_GRID=tuple(map(D,('.05','.10','.20','.30','.40','.60')))
TTE_GRID=(120000,60000,30000)


@dataclass(frozen=True)
class ExitPolicy:
    kind: str = 'HOLD'
    rebound: Decimal | None = None
    tte_ms: int | None = None
    version: str = 'preregistered-exit-v1'

    def __post_init__(self):
        if self.rebound is not None:object.__setattr__(self,'rebound',number(self.rebound))
        if self.version!='preregistered-exit-v1' or self.kind not in ('HOLD','BID_REBOUND','FIXED_TTE'):
            raise ValueError('unsupported exit policy')
        if self.kind=='HOLD' and (self.rebound is not None or self.tte_ms is not None):raise ValueError('hold has no trigger')
        if self.kind=='BID_REBOUND' and (self.rebound not in REBOUND_GRID or self.tte_ms is not None):raise ValueError('fixed rebound grid required')
        if self.kind=='FIXED_TTE' and (type(self.tte_ms) is not int or self.tte_ms not in TTE_GRID or self.rebound is not None):raise ValueError('fixed TTE grid required')

    @property
    def hash(self):return digest(asdict(self))


def policy_grid():
    return (ExitPolicy(),*(ExitPolicy('BID_REBOUND',x) for x in REBOUND_GRID),
            *(ExitPolicy('FIXED_TTE',tte_ms=x) for x in TTE_GRID))


@dataclass(frozen=True)
class ExecutionConfig:
    decision_to_order_latency_ms: int = 250
    exit_latency_ms: int = 250
    max_execution_quote_age_ms: int = 3000
    maximum_wait_for_next_book_ms: int = 5000
    max_market_status_age_ms: int = 5000
    max_exit_attempts: int = 3
    allow_same_book_zero_exit_latency: bool = False
    requested_shares: Decimal | None = None
    entry_fee: FeeModel = field(default_factory=FeeModel)
    exit_fee: FeeModel = field(default_factory=FeeModel)
    settlement_fee: FeeModel = field(default_factory=FeeModel)
    version: str = 'execution-v1'
    liquidity_policy: str = 'PHYSICAL_LOT_PER_RECORDED_SNAPSHOT_NO_INFERRED_REPLENISHMENT'

    def __post_init__(self):
        for name in ('decision_to_order_latency_ms','exit_latency_ms','max_execution_quote_age_ms',
                     'maximum_wait_for_next_book_ms','max_market_status_age_ms','max_exit_attempts'):
            v=getattr(self,name)
            if type(v) is not int or not 0<=v<=300000:raise ValueError('invalid execution time/count')
        if not 1<=self.max_exit_attempts<=10:raise ValueError('bounded preregistered exit attempts required')
        if type(self.allow_same_book_zero_exit_latency) is not bool:raise ValueError('explicit zero exit opt-in required')
        if self.requested_shares is not None:
            object.__setattr__(self,'requested_shares',number(self.requested_shares,minimum=D('1e-18'),maximum=D('1e18')))
        for name in ('entry_fee','exit_fee','settlement_fee'):
            if not isinstance(getattr(self,name),FeeModel):raise TypeError('explicit M2 FeeModel required')
        if self.version!='execution-v1' or self.liquidity_policy!='PHYSICAL_LOT_PER_RECORDED_SNAPSHOT_NO_INFERRED_REPLENISHMENT':
            raise ValueError('unsupported execution contract')

    @property
    def hash(self):return digest(asdict(self))

    @classmethod
    def from_dict(cls,value):
        value=dict(value)
        for name in ('entry_fee','exit_fee','settlement_fee'):value[name]=FeeModel(**value[name])
        return cls(**value)


@dataclass(frozen=True)
class SimulatedOrderIntent:
    order_id: str
    experiment_id: str
    market_id: str
    decision_id: str
    position_id: str | None
    purpose: str
    side: str
    requested_shares: Decimal
    created_at: int
    ready_at: int
    deadline: int
    trigger_snapshot_id: str
    config_hash: str
    policy_hash: str


@dataclass(frozen=True)
class SimulatedPosition:
    position_id: str
    experiment_id: str
    market_id: str
    side: str
    filled_shares_gross: Decimal
    filled_shares_net: Decimal
    entry_vwap: Decimal
    collateral_spent: Decimal
    entry_fee_collateral: Decimal
    entry_fee_shares: Decimal
    opened_at: int
    order_id: str
    fill_id: str


@dataclass(frozen=True)
class ExecutionResult:
    execution_id: str
    experiment_id: str
    code_git: str
    cutoff: int
    created_at: int
    config_hash: str
    policy_hash: str
    input_hash: str
    report_json: str
    version: str = 'execution-v1'

    def to_json(self):return canonical(asdict(self))

    def data(self):return json.loads(self.report_json)
