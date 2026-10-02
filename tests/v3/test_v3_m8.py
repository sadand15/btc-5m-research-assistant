"""M8 synthetic-only invariants. No production database or network."""
from dataclasses import asdict,replace
from decimal import Decimal as D
import copy
import json
import sqlite3

import pytest

from btc5_v3.encoding import canonical,digest
from btc5_v3.risk.demo import candidate,book,outcome,healthy,TD
from btc5_v3.models.models import Prediction
from btc5_v3.m8.models import Baseline,DatasetManifest,Dataset,dataset,time_split
from btc5_v3.data_quality.checks import assess,quality_report


def record(n=0,at=TD,*,p='.95',ask='.50',spread='.02',payout=1):
    original=candidate('m8-test','market-'+str(n),at=at,ask=ask)
    d=original.data();s=d['snapshot'];prediction=replace(Prediction.from_dict(d['prediction']),p_yes=D(p))
    raw=dict(market_id=s['market_id'],source_at=s['source_at'],expiry=s['expiry'],market_type='CRYPTO_UP_DOWN',
             feed=s['feed'],rule_hash=s['rule_hash'],outcome_mapping=s['outcome_mapping'],
             yes_bids=[[str(D(ask)-D(spread)),'1000']],yes_asks=[[ask,'1000']],market_status='OPEN',
             market_status_at=s['source_at'],market_status_available_at=s['source_at'])
    return dict(id='row-'+str(n),at=at,sequence=n,source='synthetic',raw=raw,received_at=s['received_at'],
                available_at=s['available_at'],prediction=json.loads(prediction.to_json()),health=asdict(healthy(at)),
                books=[dict(available_at=at+250,point=asdict(book(original,at+250)))],outcome=json.loads(outcome(original,payout).to_json()))


def test_clean_quality_and_unknown_cadence():
    r=record();before=canonical(r);q=quality_report(dataset('dev','DEVELOPMENT',[r]),TD)
    assert q['counts']['VALID']==1 and q['coverage']['status']=='UNAVAILABLE'
    assert q['missing_settlement_evidence']==1 and canonical(r)==before


@pytest.mark.parametrize('field',['raw','prediction'])
def test_missing_required(field):
    r=record();r.pop(field);assert assess(r)['state']=='INVALID'


@pytest.mark.parametrize('kind',['price','depth','probability','future_source','future_prediction','future_health','future_venue','negative_venue'])
def test_invalid_inputs(kind):
    r=record()
    if kind=='price':r['raw']['yes_asks'][0][0]='1.2'
    if kind=='depth':r['raw']['yes_asks'][0][1]='-1'
    if kind=='probability':r['prediction']['p_yes']='NaN'
    if kind=='future_source':r['raw']['source_at']=TD+1
    if kind=='future_prediction':r['prediction']['available_at']=TD+1
    if kind=='future_health':r['health']['available_at']=TD+1
    if kind in ('future_venue','negative_venue'):
        r['venue_prices']=[dict(price='-1' if kind=='negative_venue' else '100',available_at=TD+1),dict(price='101',available_at=TD)]
    assert assess(r)['state']=='INVALID'


def test_stale_and_divergence():
    r=record();r['raw']['source_at']-=4000
    q=assess(r);assert q['state']=='DEGRADED' and 'STALE_SOURCE' in q['reasons']
    r=record();r['venue_prices']=[dict(price='100',available_at=TD),dict(price='103',available_at=TD)]
    q=assess(r);assert q['venue_divergence']==D('.03') and q['state']=='DEGRADED'


def test_coverage_gaps_and_exclusion_audit():
    rows=[record(0),record(1,TD+2000)];ds=dataset('dev','DEVELOPMENT',rows,cadence_ms=1000)
    q=quality_report(ds,TD+2000)
    assert abs(q['coverage']['ratio']-D(2)/3)<D('1e-27') and q['coverage']['gap_duration_ms']==1000
    assert q['counts']==dict(VALID=1,DEGRADED=1,INVALID=0,UNKNOWN=0)
    assert q['exclusion_audit'][0]['record_id']=='row-1'
    assert quality_report(ds,TD)['records'][0]==q['records'][0]


def test_future_performance_never_changes_quality():
    r=record();q=assess(r);r['outcome']['yes_payout']='0';r['books']=[]
    assert assess(r)==q


def test_blind_denied_before_parse():
    m=DatasetManifest('blind','BLIND',TD,TD,'declared',TD,'a'*64)
    with pytest.raises(PermissionError):Dataset(m,'not even JSON')


def test_roles_hash_and_time_split():
    d=dataset('dev','DEVELOPMENT',[record()]);v=dataset('val','VALIDATION',[record(1,TD+300000)])
    time_split(d,v);assert d.manifest.hash==replace(d.manifest).hash
    with pytest.raises(ValueError):time_split(d,d)
    with pytest.raises(ValueError):Dataset(d.manifest,'[]')
    with pytest.raises(ValueError):replace(d.manifest,role='guessed')
    with pytest.raises(ValueError):replace(d.manifest,evidence_mode='LIVE')


def test_baseline_frozen():
    b=Baseline();h=b.hash;b.ensure_frozen()
    with pytest.raises(ValueError):replace(b,max_spread=D('.1')).ensure_frozen()
    assert b.hash==h


from btc5_v3.validation.replay import replay,validate
from btc5_v3.validation.metrics import grouped
CODE='c'*40


def test_fixed_replay_full_chain_deterministic():
    ds=dataset('val','VALIDATION',[record()]);before=ds.records_json
    a=validate(ds,cutoff=TD+241000,code_git=CODE)
    assert a['status']=='PASS' and a['repeat_count']==2
    r=a['cohorts']['QUALITY_PASSED'];assert r['summary']['fill_count']==1
    assert r['summary']['completed_count']==1
    assert r['rows'][0]['execution']['ledger_entries'] and r['rows'][0]['permission']['action']=='APPROVE'
    assert canonical(a)==canonical(validate(ds,cutoff=TD+241000,code_git=CODE))
    assert ds.records_json==before


def test_validation_role_and_variant_isolation():
    ds=dataset('dev','DEVELOPMENT',[record()])
    with pytest.raises(ValueError):validate(ds,cutoff=TD,code_git=CODE)
    val=dataset('val','VALIDATION',[record()]);variant=replace(Baseline(),max_spread=D(1),variant='WITHOUT_SPREAD')
    with pytest.raises(ValueError):validate(val,cutoff=TD,code_git=CODE,baseline=variant)
    with pytest.raises(ValueError):replay(val,variant,cutoff=TD,code_git=CODE,research_variant=True)


def test_future_books_outcome_do_not_change_past_replay():
    r=record();a=replay(dataset('val','VALIDATION',[r]),Baseline(),cutoff=TD,code_git=CODE)
    r['outcome']['yes_payout']='0';r['books']=[]
    b=replay(dataset('val','VALIDATION',[r]),Baseline(),cutoff=TD,code_git=CODE)
    assert canonical(a)==canonical(b)


def test_quality_filtered_comparison():
    a=record();b=record(1,TD+242000);b['raw']['source_at']-=4000
    v=validate(dataset('val','VALIDATION',[a,b]),cutoff=TD+500000,code_git=CODE)
    assert v['cohorts']['QUALITY_PASSED']['summary']['count']==1
    assert v['cohorts']['ALL_ELIGIBLE']['summary']['count']==2
    assert v['cohorts']['ALL_ELIGIBLE']['rows'][1]['decision']['final_action']=='NO_TRADE'


def test_regimes_causal_and_counts():
    ds=dataset('val','VALIDATION',[record(),record(1,TD+242000,spread='.04')])
    r=validate(ds,cutoff=TD+500000,code_git=CODE)['cohorts']['QUALITY_PASSED']
    g=grouped(r['rows'],Baseline(),'spread')
    assert set(g)=={'LOW_SPREAD','HIGH_SPREAD'} and sum(x['count'] for x in g.values())==2


def test_invalid_future_execution_diagnostic_no_source_write():
    r=record();r['outcome']['resolution_at']=TD
    result=validate(dataset('val','VALIDATION',[r]),cutoff=TD+241000,code_git=CODE)
    assert result['status']=='FAIL'
    assert result['cohorts']['QUALITY_PASSED']['diagnostics'][0]['reason']=='INVALID_SETTLEMENT_EVIDENCE'


from btc5_v3.robustness.sensitivity import sensitivity,shape
from btc5_v3.robustness.ablation import ablation
from btc5_v3.robustness.bootstrap import bootstrap
from btc5_v3.robustness.dependence import dependence,drift


def test_plateau_cliff_and_no_baseline_mutation():
    b=Baseline();before=b.hash
    plateau=sensitivity(dataset('dev','DEVELOPMENT',[record()]),cutoff=TD+241000,code_git=CODE)
    cliff=sensitivity(dataset('dev','DEVELOPMENT',[record(p='.515')]),cutoff=TD+241000,code_git=CODE)
    assert len(plateau['grid'])==5 and plateau['grid'][2]['config_hash']==before
    assert plateau['stability']['plateau_intervals']==[0,1,2,3]
    assert cliff['stability']['cliff_intervals'] and b.hash==before
    assert shape([1,2,1],3)['spike_points']==[1]


def test_ablation_changes_only_research_variant():
    ds=dataset('dev','DEVELOPMENT',[record(spread='.06')]);before=ds.records_json
    a=ablation(ds,cutoff=TD+241000,code_git=CODE)
    assert a['delta']['candidate_count']==1 and a['baseline_hash']==Baseline().hash
    assert ds.records_json==before


def many_rows():
    ds=dataset('dev','DEVELOPMENT',[record(i,TD+i*242000,payout=i%2) for i in range(10)])
    return replay(ds,Baseline(),cutoff=TD+10*242000,code_git=CODE)['rows']


@pytest.mark.parametrize('metric',['mean_edge','fill_rate','reject_rate','brier','mean_return'])
def test_bootstrap_seed_and_small_sample(metric):
    rows=many_rows();a=bootstrap(rows,metric);b=bootstrap(copy.deepcopy(rows),metric)
    assert canonical(a)==canonical(b)
    assert bootstrap(rows[:2],metric)['status']=='INSUFFICIENT_SAMPLE'
    if a['status']=='ESTIMATE':assert a['interval'][0]<=a['point_estimate']<=a['interval'][1] or metric=='reject_rate'


def test_bootstrap_clusters_not_quotes():
    rows=many_rows()
    for r in rows:r['market_id']='same-market'
    assert bootstrap(rows,'mean_edge')['status']=='INSUFFICIENT_SAMPLE'


def test_drift_stable_changed_and_bucket_specific():
    rows=many_rows();b=Baseline();stable=drift(rows,copy.deepcopy(rows),b)
    assert stable['overall']['brier_delta']==0
    changed=copy.deepcopy(rows)
    for r in changed:r['outcome']=D(1)
    d=drift(rows,changed,b)
    assert d['overall']['brier_delta']<0 and d['groups']['probability']['9']['brier_delta']<0


def test_concentration_and_sample_shares():
    rows=many_rows();c=dependence(rows)
    assert c['probability']['sample_hhi']==1
    assert sum(x['sample_share'] for x in c['market']['buckets'])==1
    assert c['market']['sample_hhi']==D('.1')


from btc5_v3.m8.demo import run_demo,fixtures,save_fixtures,ARCHIVE
from btc5_v3.validation.datasets import load_dataset,reader
from btc5_v3.m8.research import run_research


def test_unified_demo_twelve_cases_and_restart(tmp_path):
    a=run_demo(tmp_path,CODE,'v3-dev');b=run_demo(tmp_path,CODE,'v3-dev')
    assert a==b and len(a['cases'])==12 and all(a['cases'].values())
    assert len(a['artifacts'])==8


def test_read_only_dataset_and_blind_table_isolation(tmp_path):
    dev,val=fixtures();save_fixtures(tmp_path,(dev,val));path=tmp_path/ARCHIVE
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE blind_observations(secret_performance TEXT)')
        c.execute('INSERT INTO blind_observations VALUES (?)',('never-read',))
        m=asdict(dev.manifest);m.update(dataset_id='blind',role='BLIND')
        c.execute('INSERT INTO m8_dataset_manifests VALUES (?,?)',('blind',canonical(m)))
        c.execute('INSERT INTO m8_dataset_records VALUES (?,?)',('blind','NOT JSON: MUST NOT READ'))
    before=path.read_bytes();a=load_dataset(tmp_path,ARCHIVE,dev.manifest.dataset_id,required_role='DEVELOPMENT')
    with pytest.raises(PermissionError):load_dataset(tmp_path,ARCHIVE,'blind',required_role='DEVELOPMENT')
    with pytest.raises(PermissionError):load_dataset(tmp_path,ARCHIVE,'blind',required_role='BLIND')
    with reader(tmp_path,ARCHIVE) as c:
        with pytest.raises(sqlite3.DatabaseError):c.execute('SELECT * FROM blind_observations')
        with pytest.raises(sqlite3.DatabaseError):c.execute('DELETE FROM m8_dataset_records')
    assert path.read_bytes()==before
    with sqlite3.connect(path) as c:c.execute('UPDATE blind_observations SET secret_performance=?',('changed-unread-value',))
    b=load_dataset(tmp_path,ARCHIVE,dev.manifest.dataset_id,required_role='DEVELOPMENT')
    assert a==b
    assert canonical(replay(a,Baseline(),cutoff=dev.manifest.time_end,code_git=CODE))==canonical(replay(b,Baseline(),cutoff=dev.manifest.time_end,code_git=CODE))


def test_read_only_missing_and_tampered_dataset(tmp_path):
    with pytest.raises(FileNotFoundError):load_dataset(tmp_path,ARCHIVE,'x',required_role='DEVELOPMENT')
    assert not (tmp_path/ARCHIVE).exists()
    dev,val=fixtures();save_fixtures(tmp_path,(dev,val))
    with sqlite3.connect(tmp_path/ARCHIVE) as c:c.execute('UPDATE m8_dataset_records SET records_json=? WHERE dataset_id=?',('[]',dev.manifest.dataset_id))
    with pytest.raises(ValueError):load_dataset(tmp_path,ARCHIVE,dev.manifest.dataset_id,required_role='DEVELOPMENT')


def test_same_ms_sequence_deterministic():
    rows=[record(1),record(0)];a=replay(dataset('dev','DEVELOPMENT',rows),Baseline(),cutoff=TD+241000,code_git=CODE)
    b=replay(dataset('dev','DEVELOPMENT',list(reversed(rows))),Baseline(),cutoff=TD+241000,code_git=CODE)
    assert a==b and [r['record_id'] for r in a['rows']]==['row-0','row-1']


def test_future_loss_cannot_change_previous_permission():
    rows=[record(0),record(1,TD+242000)];a=replay(dataset('val','VALIDATION',rows),Baseline(),cutoff=TD+250,code_git=CODE)
    rows[0]['outcome']['yes_payout']='0';rows[1]['raw']['source_at']+=9000
    b=replay(dataset('val','VALIDATION',rows),Baseline(),cutoff=TD+250,code_git=CODE)
    assert a==b


def test_corrupt_book_keeps_diagnostics():
    r=record();r['books'][0]['point']['snapshot_json']='{}'
    v=validate(dataset('val','VALIDATION',[r]),cutoff=TD+250,code_git=CODE)
    assert v['status']=='FAIL' and v['cohorts']['QUALITY_PASSED']['diagnostics']


def test_bootstrap_seed_changes_variable_distribution():
    rows=many_rows()
    for i,r in enumerate(rows):r['outcome']=D(i<5)
    a=bootstrap(rows,'brier',seed=1);b=bootstrap(rows,'brier',seed=2)
    assert a['draws']!=b['draws'] and a['point_estimate']==b['point_estimate']


def test_empty_quality_never_validation_pass():
    r=record();r['raw']=None
    v=validate(dataset('val','VALIDATION',[r]),cutoff=TD+250,code_git=CODE)
    assert v['status']=='INSUFFICIENT_DATA' and v['cohorts']['QUALITY_PASSED']['summary']['simulated_pnl'] is None


def test_redacted_artifacts_and_explicit_provenance(tmp_path):
    from btc5_v3.m8.report import write_reports
    sentinel='synthetic-'+('z'*30)
    dev,val=fixtures();reports=run_research(dev,val,cutoff=val.manifest.time_end+241000,code_git=CODE)
    for key in ('validation','robustness','summary'):reports[key]['api_key']=sentinel
    for item in reports['data_quality'].values():item['report']['headers']={'Authorization':'Bearer '+sentinel}
    paths=write_reports(tmp_path,reports)
    assert all(sentinel not in (tmp_path/p['path']).read_text(encoding='utf-8') for p in paths)


def test_old_domain_source_unchanged():
    import subprocess
    from pathlib import Path
    from btc5_v3.m8.models import APPROVED
    root=Path(__file__).resolve().parents[2]
    old=set(subprocess.check_output(['git','ls-tree','-r','--name-only',APPROVED,'src'],cwd=root,text=True).splitlines())
    changed=set(subprocess.check_output(['git','diff','--name-only',APPROVED,'--','src'],cwd=root,text=True).splitlines())
    assert not old&changed


def test_unsupported_record_unknown_not_primary():
    r=record();r['schema_version']=2;assert assess(r)['state']=='UNKNOWN'
    v=validate(dataset('val','VALIDATION',[r]),cutoff=TD,code_git=CODE)
    assert v['status']=='INSUFFICIENT_DATA'


def test_quality_decimal_context_independent():
    from decimal import localcontext
    r=record();r['venue_prices']=[dict(price='103',available_at=TD),dict(price='107',available_at=TD)]
    a=assess(r)
    with localcontext() as c:
        c.prec=6;assert assess(r)==a


def test_early_settlement_fails_without_changing_decision():
    r=record();r['outcome']['available_at']=TD;r['outcome']['resolution_at']=TD
    a=validate(dataset('val','VALIDATION',[r]),cutoff=TD,code_git=CODE)
    assert a['status']=='FAIL'
    assert a['cohorts']['QUALITY_PASSED']['rows'][0]['decision']['final_action']=='BUY_YES'


def test_stale_book_separate_from_past_quality():
    r=record();point=r['books'][0]['point'];s=json.loads(point['snapshot_json'])
    s['available_at']+=4000;point['snapshot_json']=canonical(s);r['books'][0]['available_at']+=4000
    ds=dataset('dev','DEVELOPMENT',[r]);past=quality_report(ds,TD);later=quality_report(ds,TD+5000)
    assert later['orderbook_stale_count']==1 and later['records']==past['records']


def test_leading_trailing_gap_and_explicit_range():
    r=record();ds=dataset('dev','DEVELOPMENT',[r],cadence_ms=1000)
    ds=Dataset(replace(ds.manifest,time_start=TD-1000,time_end=TD+1000),ds.records_json)
    q=quality_report(ds,TD+1000)
    assert q['coverage']['gap_count']==2 and q['coverage']['missing']==2


def test_partial_fill_metric_and_fee_units():
    r=record();s=json.loads(r['books'][0]['point']['snapshot_json'])
    # Use the original validated fixture API, not hand-made depth identifiers.
    original=candidate('m8-test','market-0',at=TD)
    r['books'][0]['point']=asdict(book(original,TD+250,quantity='60'))
    v=validate(dataset('val','VALIDATION',[r]),cutoff=TD+241000,code_git=CODE)['cohorts']['QUALITY_PASSED']
    assert v['summary']['partial_fill_rate']=='1'
    assert set(v['summary']['fees'])=={'collateral','entry_shares','exit_shares','settlement_shares'}


@pytest.mark.parametrize('kind',['overlap','same_market'])
def test_split_rejects_leakage(kind):
    a=dataset('dev','DEVELOPMENT',[record()]);r=record(1,TD if kind=='overlap' else TD+300000)
    if kind=='same_market':r['raw']['market_id']='market-0'
    with pytest.raises(ValueError):time_split(a,dataset('val','VALIDATION',[r]))
