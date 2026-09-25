from dataclasses import asdict, dataclass, fields
from decimal import Decimal, localcontext
import json

from btc5_v3.encoding import canonical, digest, identifier, timestamp
from btc5_v3.edge.numeric import CONTEXT, number
from btc5_v3.market.models import MarketSnapshot
from btc5_v3.decision.models import Decision

D = Decimal


@dataclass(frozen=True)
class IntracyclePathConfig:
    price_buckets: tuple = tuple(map(D, ('0','.05','.10','.20','.30','.50','.70','.80','.90','.95','1')))
    tte_buckets_ms: tuple = (0,30000,60000,120000,180000,240000,300000)
    rebound_thresholds: tuple = tuple(map(D, ('.05','.10','.20','.30','.40','.60')))
    fixed_tte_ms: tuple = (240000,180000,120000,60000,30000)
    max_quote_age_ms: int = 5000
    max_missing_interval_ms: int = 5000
    minimum_move_epsilon: Decimal = D('.05')
    large_reversal_move: Decimal = D('.20')
    minimum_sample_count: int = 20
    btc_shock_enabled: bool = False
    analysis_version: str = 'intracycle-v1'

    def __post_init__(self):
        fixed = {'price_buckets':('0','.05','.10','.20','.30','.50','.70','.80','.90','.95','1'),
                 'rebound_thresholds':('.05','.10','.20','.30','.40','.60')}
        for name, values in fixed.items():
            actual = tuple(number(x) for x in getattr(self,name))
            if actual != tuple(map(D,values)): raise ValueError('fixed preregistered grid required')
            object.__setattr__(self,name,actual)
        for name, values in (('tte_buckets_ms',(0,30000,60000,120000,180000,240000,300000)),
                             ('fixed_tte_ms',(240000,180000,120000,60000,30000))):
            if tuple(getattr(self,name)) != values: raise ValueError('fixed TTE grid required')
            object.__setattr__(self,name,values)
        for name in ('max_quote_age_ms','max_missing_interval_ms','minimum_sample_count'):
            if type(getattr(self,name)) is not int or getattr(self,name)<1: raise ValueError('positive integer required')
        for name, value in (('minimum_move_epsilon','.05'),('large_reversal_move','.20')):
            object.__setattr__(self,name,number(getattr(self,name)))
            if getattr(self,name)!=D(value): raise ValueError('fixed movement definition required')
        if self.btc_shock_enabled is not False or self.analysis_version!='intracycle-v1':
            raise ValueError('BTC shock series is not implemented; explicit causal series required')

    @property
    def hash(self): return digest(asdict(self))


def projection(s):
    """Validate an archived M1 snapshot shape without constructing a permissive snapshot."""
    allowed={f.name for f in fields(MarketSnapshot)}
    optional={'market_status','market_status_at','market_status_available_at'}
    if set(s)-allowed or allowed-optional-set(s): raise ValueError('invalid snapshot archive fields')
    for name in ('snapshot_id','raw_event_id','experiment_id','market_id','source','feed','rule_hash','validator_version','config_hash'):
        identifier(s[name])
    if s['snapshot_id']!=digest([s['raw_event_id'],s['config_hash'],s['validator_version']]):
        raise ValueError('snapshot identity mismatch')
    if any(not timestamp(s[k]) for k in ('source_at','received_at','available_at','expiry')):
        raise ValueError('invalid path timestamp')
    if (s['available_at']<s['received_at'] or s['expiry']<=s['received_at']
            or type(s['sequence']) is not int or not 0<=s['sequence']<2**63
            or s['outcome_mapping'] not in ('YES_UP','YES_DOWN')):
        raise ValueError('invalid snapshot envelope')
    skew=s['clock_skew_tolerance_ms']
    if type(skew) is not int or not 0<=skew<=60000 or s['source_at']>s['received_at']+skew:
        raise ValueError('invalid source clock')
    levels={}
    for key in ('yes_bids','yes_asks','no_bids','no_asks'):
        rows=s[key]
        if not rows or len(rows)>1000: raise ValueError('missing or excessive depth')
        for row in rows:
            if set(row)!={'price','quantity','liquidity_id','origin_side','derived'}: raise ValueError('invalid depth fields')
            identifier(row['liquidity_id'])
            if row['origin_side'] not in ('YES_BID','YES_ASK'): raise ValueError('invalid depth origin')
        values=[(number(x['price']),number(x['quantity'])) for x in rows]
        if any(not 0<p<1 or not 0<q<=D('1e18') for p,q in values): raise ValueError('invalid depth')
        prices=[p for p,q in values]
        if len(set(prices))!=len(prices) or prices!=sorted(prices,reverse=key.endswith('bids')):
            raise ValueError('noncanonical depth order')
        levels[key]=values
    for side in ('yes','no'):
        if levels[side+'_bids'][0][0]>levels[side+'_asks'][0][0]: raise ValueError('crossed book')
    # Current M1 supports only complementary NO depth sharing the YES lots.
    with localcontext(CONTEXT):
        for nk,yk in (('no_bids','yes_asks'),('no_asks','yes_bids')):
            if levels[nk]!=[(1-p,q) for p,q in levels[yk]]: raise ValueError('invalid complementary depth')
            if any(not n['derived'] or n['liquidity_id']!=y['liquidity_id'] for n,y in zip(s[nk],s[yk])):
                raise ValueError('invalid derived liquidity')
        if s['no_derived'] is not True or s['liquidity_independent'] is not False:
            raise ValueError('unsupported independent NO book')
        result={k:s[k] for k in ('experiment_id','market_id','snapshot_id','source_at','received_at','available_at','sequence','expiry','source','feed','rule_hash','outcome_mapping')}
        result['remaining_ms']=s['expiry']-s['available_at']
        for side in ('yes','no'):
            bid=levels[side+'_bids'][0][0];ask=levels[side+'_asks'][0][0]
            result.update({side+'_bid':bid,side+'_ask':ask,side+'_mid':(bid+ask)/2,side+'_spread':ask-bid,
                           side+'_visible_bid_depth':sum((q for p,q in levels[side+'_bids']),D(0)),
                           side+'_visible_ask_depth':sum((q for p,q in levels[side+'_asks']),D(0))})
        result.update(no_derived=True,liquidity_independent=False)
        reference=s['reference_underlying_price'];reference_at=s['reference_price_at']
        if reference is not None:
            number(reference,minimum=D('1e-18'),maximum=D('1e18'))
            if not timestamp(reference_at): raise ValueError('invalid reference time')
        elif reference_at is not None: raise ValueError('reference pair required')
        usable=reference is not None and reference_at<=min(s['received_at'],s['available_at'])
        result.update(reference_underlying_price=number(reference) if usable else None,
                      reference_price_at=reference_at if usable else None,
                      reference_status='CAUSAL_SNAPSHOT_REFERENCE' if usable else 'UNAVAILABLE_OR_FUTURE_REFERENCE',
                      btc_price=None,btc_return_5s=None,btc_return_15s=None,btc_return_30s=None,btc_return_60s=None,
                      btc_shock_status='UNAVAILABLE_NO_CAUSAL_BTC_SERIES')
        return result


@dataclass(frozen=True)
class MarketPathPoint:
    snapshot_json: str
    decision_json: str | None = None
    observation_at: int | None = None

    def __post_init__(self):
        s=json.loads(self.snapshot_json)
        if canonical(s)!=self.snapshot_json: raise ValueError('canonical snapshot archive required')
        projection(s)
        if self.observation_at is not None and (not timestamp(self.observation_at) or not s['available_at']<=self.observation_at<s['expiry']):
            raise ValueError('observation must be after snapshot availability and before expiry')
        if self.decision_json is not None:
            d=json.loads(self.decision_json)
            if (set(d)!={f.name for f in fields(Decision)} or canonical(d)!=self.decision_json or d['experiment_id']!=s['experiment_id']
                    or d['snapshot_id']!=s['snapshot_id'] or not timestamp(d['evaluated_at'])
                    or d['decision_id']!=digest([s['experiment_id'],d['attempt_key']])):
                raise ValueError('invalid linked decision archive')

    @classmethod
    def from_snapshot(cls,snapshot,decision=None,*,observation_at=None):
        if not isinstance(snapshot,MarketSnapshot): raise TypeError('validated MarketSnapshot required')
        if decision is not None and not isinstance(decision,Decision): raise TypeError('Decision required')
        return cls(snapshot.to_json(),decision.to_json() if decision else None,observation_at)

    def data(self):
        result=projection(json.loads(self.snapshot_json))
        at=result['available_at'] if self.observation_at is None else self.observation_at
        result.update(observation_at=at,remaining_ms=result['expiry']-at)
        d=json.loads(self.decision_json) if self.decision_json else None
        status='UNAVAILABLE'
        if d is not None:
            if d['evaluated_at']>at: status='NOT_YET_AVAILABLE'
            else: status='ADMISSIBLE' if d['final_action'] in ('BUY_YES','BUY_NO') and not d['all_reasons'] else 'REJECTED'
        result.update(m3_status=status,m3_reasons=d['all_reasons'] if d and status in ('ADMISSIBLE','REJECTED') else [])
        return result

    @property
    def input_hash(self): return digest(asdict(self))


@dataclass(frozen=True)
class PathAnalysisResult:
    analysis_id: str
    experiment_id: str
    code_git: str
    cutoff: int
    created_at: int
    config_hash: str
    input_hash: str
    report_json: str
    analysis_version: str = 'intracycle-v1'

    def to_json(self): return canonical(asdict(self))
