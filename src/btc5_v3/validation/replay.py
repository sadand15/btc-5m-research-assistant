"""Frozen M1/M2/M3/M5/M6 composition in memory, with explicit quality cohorts."""
from dataclasses import asdict
from decimal import Decimal,localcontext
import copy

from btc5_v3.encoding import canonical,digest,timestamp
from btc5_v3.edge.numeric import CONTEXT
from btc5_v3.edge.engine import evaluate_edge
from btc5_v3.decision.policy import decide
from btc5_v3.analytics.models import ResearchObservation,ResolvedOutcome
from btc5_v3.path.models import MarketPathPoint
from btc5_v3.risk.engine import empty_context,apply_event
from btc5_v3.data_quality.checks import inputs,quality_report
from btc5_v3.m8.models import Baseline,normalized
from btc5_v3.validation.metrics import metrics
from btc5_v3.validation.regimes import classify


def replay(dataset,baseline,*,cutoff,code_git,cohort='QUALITY_PASSED',research_variant=False):
    if dataset.manifest.role=='BLIND':raise PermissionError('blind denied')
    if research_variant:
        if dataset.manifest.role!='DEVELOPMENT':raise ValueError('variants require development data')
    else:baseline.ensure_frozen()
    if cohort not in ('QUALITY_PASSED','ALL_ELIGIBLE'):raise ValueError('unknown cohort')
    if not timestamp(cutoff):raise ValueError('invalid cutoff')
    with localcontext(CONTEXT):return _replay(dataset,baseline,cutoff,code_git,cohort)


def _replay(dataset,baseline,cutoff,code_git,cohort):
    # Gate always uses frozen quality rules, not the variant's relaxed gates.
    quality=quality_report(dataset,cutoff,Baseline());allowed={'VALID'} if cohort=='QUALITY_PASSED' else {'VALID','DEGRADED'}
    include={r['record_id'] for r in quality['records'] if r['state'] in allowed}
    records=[r for r in dataset.records() if r['id'] in include and r['at']<=cutoff]
    contexts={};traces=[];samples={};originals={};tasks=[];diagnostics=[]
    # One dataset must be one explicit experiment; no hidden portfolio pooling.
    experiments={r['prediction']['experiment_id'] for r in records}
    if len(experiments)>1:raise ValueError('cross-experiment replay forbidden')
    run=dict(experiment_id=next(iter(experiments),'empty'),code_git=code_git,config=asdict(baseline.risk),
             config_hash=baseline.risk.hash,created_at=dataset.manifest.time_start,version='risk-v1')
    run['run_id']=digest(run);ctx=empty_context()
    for r in records:
        tasks.append((r['at'],0,r['sequence'],r['id'],'EVALUATE'))
        times={b['available_at'] for b in r.get('books',[]) if timestamp(b.get('available_at')) and r['at']<=b['available_at']<=cutoff}
        o=r.get('outcome')
        if o and timestamp(o.get('available_at')) and o['available_at']<=cutoff:times.add(max(r['at'],o['available_at']))
        if o and not timestamp(o.get('available_at')):
            diagnostics.append(dict(record_id=r['id'],at=r['at'],reason='MALFORMED_SETTLEMENT_AVAILABILITY'))
        if any(not timestamp(b.get('available_at')) for b in r.get('books',[])):
            diagnostics.append(dict(record_id=r['id'],at=r['at'],reason='MALFORMED_BOOK_AVAILABILITY'))
        for at in times:tasks.append((at,1,r['sequence'],r['id'],'EXECUTE'))
        contexts[r['id']]=r
    for at,phase,seq,identity,kind in sorted(tasks):
        r=contexts[identity]
        if kind=='EVALUATE':
            p,s=inputs(r,baseline);e=evaluate_edge(s,p,baseline.edge,evaluation_at=at)
            d=decide(s,p,e,baseline.decision(s.market_id),experiment_id=p.experiment_id,attempt_key='m8-'+identity,evaluation_at=at)
            original=ResearchObservation.from_inputs(p,s,e,d);originals[identity]=original
            value=dict(original=original.data(),at=at,health=r.get('health'),execution_config=asdict(baseline.execution),policy=asdict(baseline.policy))
            output=apply_event(ctx,run,kind,normalized(value));rid=output['risk_decision']['risk_decision_id']
            samples[identity]=dict(record_id=identity,market_id=s.market_id,at=at,p_yes=p.p_yes,side=d.side,
                  edge=d.edge_per_share,decision=normalized(asdict(d)),candidate=normalized(asdict(e)),
                  permission=output['risk_decision'],regimes=classify(p,s,at),outcome=None,execution=None,risk_events=[])
        else:
            row=samples[identity];rid=row['permission']['risk_decision_id']
            # Labels are post-hoc and validated even for rejected candidates, for calibration.
            visible_outcome=None
            if r.get('outcome') and r['outcome'].get('available_at',cutoff+1)<=at:
                try:
                    o=ResolvedOutcome.from_dict(r['outcome']);s=originals[identity].data()['snapshot']
                    if (o.experiment_id!=run['experiment_id'] or o.market_id!=s['market_id'] or o.rule_hash!=s['rule_hash']
                        or o.resolution_at<s['expiry'] or o.source!=baseline.analytics.outcome_source
                        or o.settlement_version!=baseline.analytics.settlement_version):raise ValueError('outcome mismatch')
                    visible_outcome=normalized(asdict(o));row['outcome']=o.yes_payout
                except (ValueError,TypeError,KeyError,ArithmeticError):
                    diagnostics.append(dict(record_id=identity,at=at,reason='INVALID_SETTLEMENT_EVIDENCE'));continue
            if row['permission']['action']=='REJECT':continue
            res=ctx['reservations'].get(rid)
            if res and res['status'] in ('EXPIRED','RELEASED') and not ctx['reports'].get(rid,{}).get('positions'):continue
            try:
                visible=[b for b in r.get('books',[]) if timestamp(b.get('available_at')) and b['available_at']<=at]
                books=[MarketPathPoint(**b['point']) for b in visible]
                if any(b.data()['available_at']!=v['available_at'] for b,v in zip(books,visible)):
                    raise ValueError('book availability envelope mismatch')
                value=dict(at=at,risk_decision_id=rid,books=[asdict(b) for b in books],outcome=visible_outcome)
                # A failing reducer may have touched its context; commit only a successful trial.
                trial=copy.deepcopy(ctx);output=apply_event(trial,run,kind,normalized(value));ctx=trial
                row['execution']=output['execution']
            except (ValueError,TypeError,KeyError,ArithmeticError):
                diagnostics.append(dict(record_id=identity,at=at,reason='INVALID_EXECUTION_EVIDENCE'));continue
        samples[identity]['risk_events']+=output['control_events']
        traces.append(dict(record_id=identity,at=at,kind=kind,output=output))
    rows=list(samples.values());summary=metrics(rows,baseline)
    return normalized(dict(cohort=cohort,variant=baseline.variant,baseline_hash=baseline.hash,
         quality=quality,rows=rows,events=traces,summary=summary,diagnostics=diagnostics,
         status='FAIL' if diagnostics else 'EVALUABLE' if rows else 'INSUFFICIENT_DATA'))


def validate(dataset,*,cutoff,code_git,baseline=None):
    baseline=baseline or Baseline();baseline.ensure_frozen()
    if dataset.manifest.role!='VALIDATION':raise ValueError('validation role required')
    results={}
    for cohort in ('QUALITY_PASSED','ALL_ELIGIBLE'):
        a=replay(dataset,baseline,cutoff=cutoff,code_git=code_git,cohort=cohort)
        b=replay(dataset,baseline,cutoff=cutoff,code_git=code_git,cohort=cohort)
        if canonical(a)!=canonical(b):raise ValueError('REPLAY_MISMATCH')
        results[cohort]=a
    return dict(status='PASS' if results['QUALITY_PASSED']['status']=='EVALUABLE' else results['QUALITY_PASSED']['status'],
                meaning='CAUSALLY_EVALUABLE_AND_REPRODUCIBLE_NOT_PROFITABILITY',repeat_count=2,
                replay_hashes={k:digest(v) for k,v in results.items()},cohorts=results)
