"""M4.5 synthetic-only regressions. Never opens the frozen observation database."""
from dataclasses import asdict,replace,FrozenInstanceError
from decimal import Decimal,localcontext
import json
import sqlite3

import pytest

from btc5_v3.analytics.demo import synthetic_observation
from btc5_v3.analytics.models import ResolvedOutcome
from btc5_v3.config.models import StorageConfig
from btc5_v3.encoding import canonical,digest
from btc5_v3.experiments.models import Experiment
from btc5_v3.path.models import IntracyclePathConfig,MarketPathPoint
from btc5_v3.path.engine import analyze_paths,bucket
from btc5_v3.path.demo import START,point,dataset,run_demo
from btc5_v3.path.report import markdown
from btc5_v3.storage.database import Database
from btc5_v3.storage.analytics_repository import AnalyticsRepository,RESEARCH_CONTRACT
from btc5_v3.storage.path_repository import PathRepository,migrate_path

D=Decimal
CODE='a'*40
EXP='path-test'
CFG=IntracyclePathConfig()
CUTOFF=START+302000


def result(points,outcomes=(),cfg=CFG,cutoff=CUTOFF,created=None):
    return analyze_paths(points,outcomes,cfg,experiment_id=EXP,code_git=CODE,cutoff=cutoff,created_at=cutoff if created is None else created)


def report(points,outcomes=(),**kw): return json.loads(result(points,outcomes,**kw).report_json)


def row(r,market='m',side='YES',view='ALL_STRUCTURALLY_VALID',index=0):
    return [x for x in r['observations'] if x['market_id']==market and x['side']==side and x['view']==view][index]


def series(values,*,step=3000,market='m'):
    return [point(market,i+1,D(x)-D('.01'),D(x)+D('.01'),tte=240000-i*step) for i,x in enumerate(values)]


def outcome(market='m',payout=0,**kw):
    return replace(ResolvedOutcome(EXP,market,START+300000,START+301000,D(payout),
                                  'synthetic-settlement','synthetic-rule-v1','synthetic-settlement-v1'),**kw)


@pytest.fixture(scope='module')
def demo_report():
    p,o=dataset(EXP);return report(p,o)


def test_required_a(demo_report):
    x=row(demo_report,'scenario-a')
    assert D(x['max_mid_rebound'])==D('.795')
    assert D(x['max_bid_rebound'])==D('.79')
    assert x['time_to_max_rebound']==180000
    assert len(x['missing_quote_intervals'])>0 and not x['complete_observation_window']


def test_required_b_impossible_book_rejected_and_valid_contrast(demo_report):
    with pytest.raises(ValueError): point('b',1,'.25','1.55')
    x=row(demo_report,'wide-spread-b')
    assert D(x['max_mid_rebound'])==D('.50') and D(x['max_bid_rebound'])==D('.20')
    assert D(x['max_mid_rebound'])>2*D(x['max_bid_rebound'])


def test_required_c_temporary_rebound_with_losing_settlement(demo_report):
    x=row(demo_report,'temporary-c')
    assert D(x['max_mid_rebound'])==D('.5') and x['settlement_payout']=='0'
    tables=[t for t in demo_report['study_tables'] if t['view']=='ALL_STRUCTURALLY_VALID' and t['side']=='YES' and t['price_view']=='mid']
    assert any(g['rebound_then_losing_settlement'] for t in tables for g in t['grid'])


def test_required_d_winning_rebound(demo_report):
    x=row(demo_report,'winning-d')
    assert D(x['max_mid_rebound'])==D('.7') and x['settlement_payout']=='1'


def test_continuation_negative_maximum_not_clamped(demo_report):
    x=row(demo_report,'continuation')
    assert D(x['max_mid_rebound'])==D('-.04') and D(x['max_drawdown'])==D('.07')


def test_whipsaw_noise_epsilon_and_gap_segments(demo_report):
    x=next(x for x in demo_report['market_metrics'] if x['market_id']=='whipsaw' and x['side']=='YES')
    assert x['number_of_direction_changes']==2 and x['number_of_large_reversals']==2 and x['whipsaw_observed']
    noise=report(series(['.2','.201','.199','.202']))
    assert noise['market_metrics'][0]['number_of_direction_changes']==0
    sparse=report(series(['.2','.7','.25','.8'],step=60000))
    assert sparse['market_metrics'][0]['number_of_large_reversals']==0


def test_stale_peak_separate_views(demo_report):
    a=row(demo_report,'stale-peak');c=row(demo_report,'stale-peak',view='FRESHNESS_FILTERED')
    assert D(a['max_mid_rebound'])==D('.8') and D(c['max_mid_rebound'])==D('.1')
    assert demo_report['coverage']['stale_quote_count']==1


def test_zero_rebound_and_absent_future_not_losses():
    r=report(series(['.2','.2']))
    assert row(r)['max_mid_rebound']=='0'
    last=row(r,index=1)
    assert last['max_mid_rebound'] is None and last['settlement_payout'] is None


def test_negative_drawdown_is_signed_future_only():
    r=report(series(['.2','.4','.5']))
    assert row(r)['max_drawdown']=='-0.2'


def test_yes_no_not_mixed(demo_report):
    yes=row(demo_report,'scenario-a');no=row(demo_report,'scenario-a',side='NO')
    assert D(yes['max_mid_rebound'])>0 and D(no['max_mid_rebound'])<0
    assert no['settlement_payout']=='0' and no['no_derived']
    assert {x['side'] for x in demo_report['study_tables']}=={'YES','NO'}


def test_deterministic_order_same_ms_sequence():
    p=[point('m',2,'.69','.71'),point('m',1,'.19','.21'),point('m',3,'.29','.31')]
    a=result(p);b=result(list(reversed(p)))
    assert a==b
    r=json.loads(a.report_json)
    assert [x['sequence'] for x in r['points']]==[1,2,3]
    assert row(r)['max_mid_rebound']=='0.5' and row(r)['time_to_max_rebound']==0


def test_received_not_source_order():
    p=series(['.2','.7'])
    p[1]=point('m',2,'.69','.71',tte=237000,source_age=4000)
    r=report(p)
    assert r['points'][1]['source_at']<r['points'][0]['source_at']
    assert row(r)['max_mid_rebound']=='0.5'


@pytest.mark.parametrize('price,index',[('0',0),('.05',1),('.10',2),('.20',3),('.30',4),('.50',5),('.70',6),('.80',7),('.90',8),('.95',9),('1',9)])
def test_price_boundary(price,index): assert bucket(D(price),CFG.price_buckets)==index


@pytest.mark.parametrize('tte,index',[(0,0),(29999,0),(30000,1),(60000,2),(120000,3),(180000,4),(240000,5),(300000,5)])
def test_tte_boundary(tte,index): assert bucket(tte,CFG.tte_buckets_ms)==index


def test_missing_fixed_tte_no_future_backfill():
    p=[point('m',1,'.1','.2',tte=239999)]
    r=report(p)
    view=next(x for x in r['fixed_tte'] if x['target_tte_ms']==240000)
    assert view['status']=='MISSING'
    assert r['coverage']['missing_intervals'][0]['missing_intervals']


def test_fixed_tte_availability_and_age_gated():
    p=[point('m',1,'.1','.2',tte=241000,available_delay=2000)]
    assert report(p)['fixed_tte'][0]['status']=='MISSING'
    p=[point('m',1,'.1','.2',tte=241000)]
    x=report(p)['fixed_tte'][0]
    assert x['status']=='OBSERVED_ASOF' and x['quote_received_at']==START+59000
    assert x['metrics']['receipt_age_ms']==1000
    p=[point('m',1,'.1','.2',tte=246000)]
    assert report(p)['fixed_tte'][0]['status']=='MISSING'


def test_cutoff_excludes_future_and_marks_censoring():
    p=series(['.2','.7']);r=report(p,cutoff=START+61000)
    assert r['coverage']['path_points']==1 and r['coverage']['exclusions']=={'NOT_YET_AVAILABLE':1}
    assert len(r['points'])==1 and row(r)['right_censored'] and row(r)['max_mid_rebound'] is None


def test_complete_observation_window_requires_dense_tail():
    p=[point('m',i+1,'.2','.3',tte=t) for i,t in enumerate((12000,8000,4000,1))]
    r=report(p)
    assert row(r)['complete_observation_window']
    assert not row(r,index=3)['complete_observation_window']


def test_availability_lag_does_not_use_pre_observation_quote():
    p=[point('m',1,'.1','.2',tte=240000,available_delay=4000),point('m',2,'.8','.9',tte=237000)]
    assert row(report(p))['max_mid_rebound'] is None


@pytest.mark.parametrize('kwargs,status',[
    ({'available_at':CUTOFF+1},'OUTCOME_NOT_YET_AVAILABLE'),
    ({'resolution_at':START+299000},'PREMATURE_RESOLUTION'),
    ({'rule_hash':'different'},'INCOMPATIBLE_OUTCOME'),
    ({'source':'different'},'INCOMPATIBLE_OUTCOME')])
def test_outcome_temporal_contract(kwargs,status):
    r=report(series(['.2','.7']),[outcome(**kwargs)])
    assert r['coverage']['outcome_status']['m']==status and row(r)['settlement_payout'] is None


def test_split_never_forced_to_win(demo_report):
    assert row(demo_report,'split')['settlement_payout']=='0.5'
    assert row(demo_report,'split',side='NO')['settlement_payout']=='0.5'


def test_future_causality_upstream_archive_unchanged():
    original,o=synthetic_observation(EXP,0)
    archive=original.payload_json;up=json.loads(archive)
    p=MarketPathPoint(canonical(up['snapshot']),canonical(up['decision']))
    s=p.data();future=point(s['market_id'],999,'.89','.91',tte=60000,expiry=s['expiry'])
    a=result([p,future],[o]);changed=point(s['market_id'],999,'.29','.31',tte=60000,expiry=s['expiry'])
    b=result([p,changed],[o])
    assert a.report_json!=b.report_json and original.payload_json==archive
    assert p.snapshot_json==canonical(up['snapshot']) and p.decision_json==canonical(up['decision'])
    assert all(json.loads(original.payload_json)[k]==up[k] for k in ('snapshot','prediction','edge','decision'))


def test_m3_status_unknown_or_not_yet_available():
    original,_=synthetic_observation(EXP,0);d=original.data()
    p=MarketPathPoint(canonical(d['snapshot']),canonical(d['decision']))
    assert p.data()['m3_status']=='NOT_YET_AVAILABLE'
    assert series(['.2'])[0].data()['m3_status']=='UNAVAILABLE'


@pytest.mark.parametrize('stale,expected',[(False,'ADMISSIBLE'),(True,'REJECTED')])
def test_m3_status_at_explicit_causal_observation(stale,expected):
    original,_=synthetic_observation(EXP,0,stale=stale);d=original.data()
    p=MarketPathPoint(canonical(d['snapshot']),canonical(d['decision']),d['decision']['evaluated_at'])
    assert p.data()['m3_status']==expected
    r=report([p])
    assert r['observations'][0]['m3_status']==expected
    assert p.data()['available_at']==d['snapshot']['available_at']
    assert p.data()['remaining_ms']==d['snapshot']['expiry']-d['decision']['evaluated_at']


def test_reference_is_not_fabricated_btc_series():
    p=point('m',1,'.1','.2',reference=('60000',START+59999));d=p.data()
    assert d['reference_underlying_price']==60000 and d['btc_price'] is None
    assert d['btc_return_30s'] is None
    with pytest.raises(ValueError): IntracyclePathConfig(btc_shock_enabled=True)


def test_full_grids_no_strategy_outputs(demo_report):
    for t in demo_report['study_tables']:
        assert [D(g['threshold']) for g in t['grid']]==list(CFG.rebound_thresholds)
    text=canonical(demo_report)
    for key in ('best_threshold','optimal_price','optimal_tte','recommended_strategy','order_id','execution_pnl'):
        assert key not in text.lower()
    assert {x['price_view'] for x in demo_report['study_tables']}=={'mid','bid'}


def test_conditioning_and_insufficient_samples(demo_report):
    assert {x['dimension'] for x in demo_report['conditioning']}=={'spread','normalized_spread','visible_bid_depth','visible_ask_depth','source_age_ms','receipt_age_ms','m3_status'}
    assert all(t['status']=='INSUFFICIENT_SAMPLE' for t in demo_report['study_tables'])


def test_config_hash_immutable_and_ambient_decimal():
    assert CFG.hash==IntracyclePathConfig(**json.loads(canonical(asdict(CFG)))).hash
    assert CFG.hash!=replace(CFG,max_quote_age_ms=6000).hash
    with pytest.raises(FrozenInstanceError): CFG.minimum_sample_count=5
    with pytest.raises(ValueError): replace(CFG,rebound_thresholds=(D('.4'),))
    p=series(['.2','.3']);expected=result(p)
    with localcontext() as ctx:
        ctx.prec=4
        assert result(p)==expected


@pytest.mark.parametrize('kind',['duplicate','order','experiment','contract','outcome'])
def test_invalid_archive_is_explicit_error(kind):
    p=series(['.2','.3']);outs=[]
    if kind=='duplicate':p=[p[0],p[0]]
    if kind=='order':p=[p[0],point('m',1,'.6','.7')]
    if kind=='experiment':p=[point('m',1,'.2','.3',experiment_id='other')]
    if kind=='contract':p=[p[0],point('m',2,'.2','.3',expiry=START+301000)]
    if kind=='outcome':outs=[outcome(),outcome(payout=1)]
    with pytest.raises(ValueError):result(p,outs)


@pytest.mark.parametrize('mutation',['mid','depth','complement','id','time'])
def test_snapshot_archive_integrity(mutation):
    d=json.loads(series(['.2'])[0].snapshot_json)
    if mutation=='mid':d['yes_mid']='.9'
    if mutation=='depth':d['yes_bids'][0]['quantity']='-1'
    if mutation=='complement':d['no_bids'][0]['price']='.1'
    if mutation=='id':d['snapshot_id']='bad'
    if mutation=='time':d['source_at']=d['received_at']+60001
    with pytest.raises(ValueError):MarketPathPoint(canonical(d))


def open_repo(tmp_path):
    db=Database(StorageConfig(tmp_path));repo=PathRepository(db)
    repo.register(Experiment(EXP,CODE,'path-synthetic',42,START,digest(RESEARCH_CONTRACT)))
    return db,repo


def persist(repo,points=None,created=CUTOFF):
    return repo.run(points or series(['.2','.7']),[outcome()],CFG,experiment_id=EXP,code_git=CODE,cutoff=CUTOFF,created_at=created)


def test_idempotent_replay_first_creation_and_schema_reopen(tmp_path):
    db,repo=open_repo(tmp_path)
    a=persist(repo);b=persist(repo,created=CUTOFF+1)
    assert a==b==repo.get_run(a.analysis_id)
    assert db.connection.execute('SELECT COUNT(*) FROM path_analysis_runs').fetchone()[0]==1
    assert db.connection.execute('SELECT COUNT(*) FROM market_snapshots').fetchone()[0]==0
    assert db.connection.execute('PRAGMA user_version').fetchone()[0]==5
    db.connection.close()
    with Database(StorageConfig(tmp_path)) as db:
        assert PathRepository(db).get_run(a.analysis_id)==a
        assert len(db.connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())==12


@pytest.mark.parametrize('table',['path_analysis_runs','path_analysis_results'])
@pytest.mark.parametrize('operation',['UPDATE','DELETE','REPLACE'])
def test_append_only(tmp_path,table,operation):
    db,repo=open_repo(tmp_path);persist(repo)
    sql={'UPDATE':f'UPDATE {table} SET experiment_id=experiment_id','DELETE':f'DELETE FROM {table}',
         'REPLACE':f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}'}[operation]
    with pytest.raises(sqlite3.IntegrityError):
        with db.connection:db.connection.execute(sql)
    db.connection.close()


@pytest.mark.parametrize('table,column,value',[
    ('path_analysis_runs','code_git','b'*40),('path_analysis_runs','input_hash','bad'),
    ('path_analysis_results','result_hash','bad')])
def test_readback_corruption(tmp_path,table,column,value):
    db,repo=open_repo(tmp_path);a=persist(repo)
    with db.connection:
        db.connection.execute(f'DROP TRIGGER {table}_immutable_update')
        db.connection.execute(f'UPDATE {table} SET {column}=?',(value,))
    with pytest.raises(ValueError):repo.get_run(a.analysis_id)
    db.connection.close()


def test_transaction_rollback(tmp_path):
    db,repo=open_repo(tmp_path)
    with db.connection: db.connection.execute("CREATE TRIGGER injected BEFORE INSERT ON path_analysis_results BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):persist(repo)
    assert db.connection.execute('SELECT COUNT(*) FROM path_analysis_runs').fetchone()[0]==0
    db.connection.close()


def test_migration_rollback(tmp_path):
    with Database(StorageConfig(tmp_path)) as db:
        AnalyticsRepository(db)
        db.connection.execute('CREATE TABLE path_analysis_results (id TEXT)')
        with pytest.raises(sqlite3.OperationalError):migrate_path(db)
        assert db.connection.execute('PRAGMA user_version').fetchone()[0]==4
        assert db.connection.execute("SELECT name FROM sqlite_master WHERE name='path_analysis_runs'").fetchone() is None


def test_synthetic_demo_deterministic_artifacts(tmp_path):
    a=run_demo(tmp_path,CODE);b=run_demo(tmp_path,CODE)
    assert a==b
    assert (tmp_path/'runtime/v3/m4-5-report.md').read_text(encoding='utf-8')==markdown(a)
    assert (tmp_path/'runtime/v3/m4-5-report.json').read_text(encoding='utf-8')==a.to_json()
    assert json.loads(a.report_json)['coverage']['markets']==8
