"""Causal decision-input quality, independent of future outcomes or returns."""
from dataclasses import asdict
from decimal import Decimal
from math import ceil

from btc5_v3.encoding import digest, timestamp
from btc5_v3.config.models import ValidatorConfig
from btc5_v3.market.normalize import raw_event
from btc5_v3.market.validation import validate_market
from btc5_v3.models.models import Prediction
from btc5_v3.risk.models import HealthEvidence
from btc5_v3.m8.models import Baseline,fixed_decimal
from btc5_v3.path.models import MarketPathPoint

D=Decimal
QUALITY_RULES={'version':'m8-quality-v1','primary':['VALID'],'diagnostic':['VALID','DEGRADED'],
               'divergence_reference':'FIRST_DECLARED_SOURCE','divergence_threshold':'.01',
               'gap':'EXACT_CADENCE_SLOTS','production_age_limits':'M3_M6_DEFAULTS',
               'future_evidence':'NEVER_GATE_EARLIER_DECISION'}
QUALITY_HASH=digest(QUALITY_RULES)


def distribution(values):
    values=sorted(values)
    def q(p):return values[max(0,ceil(len(values)*p)-1)] if values else None
    return dict(count=len(values),p50=q(.5),p95=q(.95),p99=q(.99),max=max(values) if values else None)


def inputs(record,baseline):
    raw=record['raw'];p=Prediction.from_dict(record['prediction'])
    if (p.model_hash!=baseline.model_hash or p.feature_hash!=baseline.feature_hash
            or p.model_version!=baseline.model_version or p.feature_version!=baseline.feature_version
            or p.calibration_version!=baseline.calibration_version): raise ValueError('prediction binding mismatch')
    cfg=ValidatorConfig(raw['market_id'],'SYNTHETIC','synthetic-rule-v1')
    event=raw_event(raw,experiment_id=p.experiment_id,source=record['source'],
                    received_at=record['received_at'],sequence=record['sequence'])
    result=validate_market(event,cfg,evaluation_at=record['available_at'])
    if result.snapshot is None: raise ValueError('M1 invariant rejection')
    s=result.snapshot
    if s.market_id!=p.market_id or s.expiry!=p.target_definition.expiry: raise ValueError('identity mismatch')
    if (p.target_definition.rule_hash!=cfg.rule_hash or p.target_definition.outcome_mapping!='YES_UP'
            or p.target_definition.target_feed!='SYNTHETIC' or p.target_definition.target_source!='synthetic-oracle'):
        raise ValueError('prediction target mismatch')
    return p,s


@fixed_decimal
def assess(record,baseline=None,*,prior_at=None,cadence_ms=None):
    baseline=baseline or Baseline();at=record['at'];reasons=[];ages={};divergence=None;skew=None
    state='VALID'
    if record.get('schema_version',1)!=1:
        return dict(record_id=record['id'],timestamp=at,source=record.get('source','UNKNOWN'),state='UNKNOWN',
                    reasons=['UNSUPPORTED_RECORD_SCHEMA'],ages={},source_skew=None,venue_divergence=None,reconstruction='NOT_VERIFIABLE')
    def mark(reason,level='DEGRADED'):
        nonlocal state
        reasons.append(reason)
        if state!='INVALID':state=level if level=='INVALID' or state=='VALID' else state
    if not record.get('raw') or not record.get('prediction'):
        mark('MISSING_REQUIRED_INPUT','INVALID')
    else:
        try:
            p,s=inputs(record,baseline);dc=baseline.decision(s.market_id)
            ages=dict(prediction=at-p.available_at,receipt=at-s.received_at,source=at-s.source_at,
                      venue_status=at-s.market_status_at if s.market_status_at is not None else None)
            if (s.available_at>at or p.available_at>at or s.source_at>at or s.received_at>at
                    or p.input_cutoff>p.available_at or at>=s.expiry):mark('CAUSAL_ALIGNMENT','INVALID')
            for field,limit in (('receipt',dc.max_receipt_age_ms),('source',dc.max_source_age_ms),('venue_status',dc.max_market_status_age_ms)):
                if ages[field] is None:mark('MISSING_'+field.upper(),'INVALID')
                elif ages[field]>limit:mark('STALE_'+field.upper())
            skew=abs(s.source_at-p.input_cutoff)
        except (KeyError,ValueError,TypeError,ArithmeticError,AttributeError):mark('DOMAIN_OR_ALIGNMENT_INVARIANT','INVALID')
    health=record.get('health')
    if health is None:mark('MISSING_HEALTH')
    else:
        try:
            h=HealthEvidence(**health)
            if h.available_at>at or any(t is not None and t>h.available_at for t in (h.source_at,h.heartbeat_at)):
                mark('HEALTH_CAUSAL_ALIGNMENT','INVALID')
            for name,t,limit in (('health_source',h.source_at,baseline.risk.max_feed_age_ms),('heartbeat',h.heartbeat_at,baseline.risk.max_heartbeat_age_ms)):
                ages[name]=None if t is None else at-t
                if t is None:mark('MISSING_'+name.upper())
                elif at-t>limit:mark('STALE_'+name.upper())
            if not h.source_matches or not h.provider_healthy or h.validation_failures>=baseline.risk.validation_failure_burst_limit:
                mark('DEGRADED_HEALTH')
        except (ValueError,TypeError,KeyError):mark('INVALID_HEALTH','INVALID')
    venues=record.get('venue_prices',[])
    if venues:
        try:
            if len(venues)!=2:raise ValueError('two fixed sources required')
            prices=[D(x['price']) for x in venues]
            if any(not p.is_finite() or p<=0 or p>D('1e18') for p in prices):raise ValueError('invalid price')
            if any(not timestamp(x['available_at']) or x['available_at']>at for x in venues):
                mark('VENUE_CAUSAL_ALIGNMENT','INVALID')
            else:
                divergence=abs(prices[0]-prices[1])/prices[0]
                if divergence>D('.01'):mark('VENUE_DIVERGENCE')
        except (KeyError,ValueError,TypeError,ArithmeticError):mark('INVALID_VENUE_PRICE','INVALID')
    if cadence_ms and prior_at is not None and at-prior_at>cadence_ms:mark('KNOWN_CADENCE_GAP')
    return dict(record_id=record['id'],timestamp=at,source=record.get('source','UNKNOWN'),state=state,
                reasons=sorted(set(reasons)),ages=ages,source_skew=skew,venue_divergence=divergence,
                reconstruction='NOT_VERIFIABLE' if record.get('reconstructed') else 'NOT_APPLICABLE')


@fixed_decimal
def coverage(manifest,records,cutoff):
    if manifest.cadence_ms is None:return dict(status='UNAVAILABLE',reason='NO_EXPECTED_CADENCE',ratio=None,gaps=[])
    end=min(manifest.time_end,cutoff);c=manifest.cadence_ms
    slots=list(range(manifest.time_start,end+1,c));observed={r['at'] for r in records};missing=[x for x in slots if x not in observed]
    groups=[]
    for x in missing:
        if groups and groups[-1]['end']+c==x:groups[-1]['end']=x;groups[-1]['duration_ms']+=c
        else:groups.append(dict(start=x,end=x,duration_ms=c))
    durations=sorted(x['duration_ms'] for x in groups);n=len(durations)
    return dict(status='AVAILABLE',expected=len(slots),observed=len(set(slots)&observed),missing=len(missing),
                ratio=D(len(slots)-len(missing))/len(slots) if slots else None,gap_count=n,gaps=groups,
                gap_duration_ms=sum(durations),max_gap_ms=max(durations,default=0),
                median_gap_ms=(D(durations[(n-1)//2])+durations[n//2])/2 if n else None)


@fixed_decimal
def quality_report(dataset,cutoff,baseline=None):
    baseline=baseline or Baseline()
    rows=[r for r in dataset.records() if r['at']<=cutoff];items=[];prior=dataset.manifest.time_start-dataset.manifest.cadence_ms if dataset.manifest.cadence_ms else None
    for r in rows:
        items.append(assess(r,baseline,prior_at=prior,cadence_ms=dataset.manifest.cadence_ms));prior=r['at']
    counts={s:sum(x['state']==s for x in items) for s in ('VALID','DEGRADED','INVALID','UNKNOWN')}
    ages={k:distribution([x['ages'][k] for x in items if x['ages'].get(k) is not None]) for k in ('prediction','receipt','source','venue_status','health_source','heartbeat')}
    stale=sum(any(y.startswith('STALE') for y in x['reasons']) for x in items)
    book_ages=[];book_audit=[]
    for r in rows:
        for b in r.get('books',[]):
            if not timestamp(b.get('available_at')):
                book_audit.append(dict(record_id=r['id'],timestamp=r['at'],reason='MALFORMED_BOOK_AVAILABILITY'));continue
            if b['available_at']>cutoff:continue
            try:
                point=MarketPathPoint(**b['point']).data()
                if point['available_at']!=b['available_at'] or point['source_at']>b['available_at']:
                    raise ValueError('book timestamp mismatch')
                age=b['available_at']-point['received_at'];book_ages.append(age)
                if age>baseline.execution.max_execution_quote_age_ms:
                    book_audit.append(dict(record_id=r['id'],timestamp=b['available_at'],reason='STALE_BOOK_RECEIPT'))
            except (ValueError,KeyError,TypeError,ArithmeticError):
                book_audit.append(dict(record_id=r['id'],timestamp=b['available_at'],reason='INVALID_BOOK_EVIDENCE'))
    return dict(contract_hash=QUALITY_HASH,total_observations=len(items),counts=counts,records=items,
                exclusion_audit=[x for x in items if x['state']!='VALID'],coverage=coverage(dataset.manifest,rows,cutoff),
                stale_count=stale,stale_rate=D(stale)/len(items) if items else None,ages=ages,
                outlier_count=sum('DOMAIN_OR_ALIGNMENT_INVARIANT' in x['reasons'] or 'INVALID_VENUE_PRICE' in x['reasons'] for x in items),
                alignment_violations=sum(any('ALIGNMENT' in y for y in x['reasons']) for x in items),
                source_skew=distribution([x['source_skew'] for x in items if x['source_skew'] is not None]),
                venue_divergence=distribution([x['venue_divergence'] for x in items if x['venue_divergence'] is not None]),
                divergence_exceedances=sum('VENUE_DIVERGENCE' in x['reasons'] for x in items),
                reconstruction_summary='NOT_VERIFIABLE_WITHOUT_GROUND_TRUTH',
                orderbook_age_at_availability=distribution(book_ages),execution_evidence_audit=book_audit,
                orderbook_stale_count=sum(x['reason']=='STALE_BOOK_RECEIPT' for x in book_audit),
                missing_execution_evidence=sum(not any(b.get('available_at',cutoff+1)<=cutoff for b in r.get('books',[])) for r in rows),
                missing_settlement_evidence=sum(not r.get('outcome') or r['outcome'].get('available_at',cutoff+1)>cutoff for r in rows),
                limitation='Quality at decision does not certify future execution evidence; statistical outlier screening unsupported.')
