"""M4 synthetic measurement regressions. Never reads V2 observations."""
from dataclasses import asdict,replace,FrozenInstanceError
from decimal import Decimal,localcontext,ROUND_DOWN
import json
import sqlite3

import pytest

from btc5_v3.analytics.models import AnalyticsConfig,ResolvedOutcome,ResearchObservation
from btc5_v3.analytics.statistics import calibration,edge_bucket,probability_bin,tte_bucket,spearman
from btc5_v3.analytics.engine import analyze
from btc5_v3.analytics.demo import synthetic_observation,run_demo
from btc5_v3.analytics.report import markdown
from btc5_v3.config.models import StorageConfig
from btc5_v3.encoding import canonical,digest
from btc5_v3.experiments.models import Experiment
from btc5_v3.storage.database import Database
from btc5_v3.storage.analytics_repository import AnalyticsRepository,RESEARCH_CONTRACT,migrate_m4

D=Decimal
CFG=AnalyticsConfig(minimum_sample_count=3)
EXP='analytics-test'
CODE='a'*40


def dataset(n=4,**kwargs):
    pairs=[synthetic_observation(EXP,i,**kwargs) for i in range(n)]
    return tuple(p[0] for p in pairs),tuple(p[1] for p in pairs)


def result(obs,outs,cfg=CFG,cutoff=None,code=CODE):
    cutoff=cutoff if cutoff is not None else max((o.available_at for o in outs),default=1704067600000)+1000
    return analyze(obs,outs,cfg,experiment_id=EXP,code_git=code,cutoff=cutoff,created_at=cutoff)


def report(obs,outs,**kwargs):return json.loads(result(obs,outs,**kwargs).report_json)


def test_brier_mandatory_regression():
    r=calibration([('.8',1),('.2',0)],CFG)
    assert r['brier_payout']==D('.04') and r['brier_binary']==D('.04')


def test_perfect_calibration_and_over_under_confidence():
    calibrated=calibration([('.2',1)]*2+[('.2',0)]*8+[('.8',1)]*8+[('.8',0)]*2,CFG)
    over=calibration([('.01',1)]*2+[('.01',0)]*8+[('.99',1)]*8+[('.99',0)]*2,CFG)
    under=calibration([('.4',1)]*2+[('.4',0)]*8+[('.6',1)]*8+[('.6',0)]*2,CFG)
    assert calibrated['ece']==0 and calibrated['mce']==0
    assert over['ece']==D('.19') and under['ece']==D('.2')
    assert over['brier_binary']>calibrated['brier_binary']


def test_ece_weighting_and_empty_single_bins():
    r=calibration([('.2',0)]*3+[('.8',1)],CFG)
    assert r['ece']==D('.2')
    assert r['bins'][2]['binary_count']==3 and r['bins'][8]['binary_count']==1
    assert r['bins'][0]['count']==0 and r['bins'][0]['observed_yes_rate'] is None


@pytest.mark.parametrize('p,expected',[(0,0),('.1',1),('.2',2),('.9',9),(1,9)])
def test_calibration_boundaries(p,expected):
    assert probability_bin(D(p),CFG.calibration_bin_edges)==expected


def test_zero_one_clip_retains_original_input():
    pairs=[(D(0),D(1)),(D(1),D(0))]
    original=list(pairs);r=calibration(pairs,CFG)
    assert pairs==original and r['log_loss_clipped_count']==2
    assert r['log_loss'].is_finite() and r['log_loss_epsilon']==CFG.log_loss_epsilon
    assert r['brier_binary']==1


def test_split_not_binary_logloss():
    r=calibration([('.8',1),('.2',0),('.8','.5')],CFG)
    assert r['binary_settled_count']==2 and r['split_count']==1
    assert r['log_loss']==calibration([('.8',1),('.2',0)],CFG)['log_loss']
    assert r['log_loss_split_excluded_count']==1
    assert float(r['brier_payout'])==pytest.approx(.17/3)
    all_split=calibration([('.5','.5')],CFG)
    assert all_split['log_loss'] is None and all_split['ece'] is None and all_split['brier_payout']==0


@pytest.mark.parametrize('edge,bucket',[
    ('-.10','NEGATIVE'),('0','ZERO'),('.01','POS_LT_02'),('.02','02_TO_05'),('.03','02_TO_05'),
    ('.05','05_TO_10'),('.07','05_TO_10'),('.10','10_TO_15'),('.12','10_TO_15'),('.15','GE_15'),('.20','GE_15')])
def test_signed_edge_buckets(edge,bucket):assert edge_bucket(D(edge))==bucket


@pytest.mark.parametrize('ms,bucket',[(0,'0_TO_30S'),(30000,'30_TO_60S'),(60000,'60_TO_120S'),
                                     (120000,'120_TO_180S'),(180000,'GE_180S')])
def test_tte_boundaries(ms,bucket):assert tte_bucket(ms)==bucket


def test_spearman_ties_constant_and_small_samples():
    r=spearman([D(1),D(1),D(3)],[D(2),D(2),D(4)],minimum_sample_count=3,unique_markets=3)
    assert r['correlation']==1
    assert spearman([1,2,3],[3,2,1],minimum_sample_count=3,unique_markets=3)['correlation']==-1
    assert spearman([1,2,3],[1,2,3],minimum_sample_count=3,unique_markets=1)['status']=='INSUFFICIENT_SAMPLE'
    assert spearman([1,1,1],[1,2,3],minimum_sample_count=3,unique_markets=3)['status']=='CONSTANT_SERIES'


def test_threshold_full_grid_no_ranking_api():
    obs,outs=dataset();r=report(obs,outs)
    thresholds=[x for x in r['sensitivity'] if x['scenario']=='THRESHOLD']
    assert [D(x['value']) for x in thresholds]==list(CFG.threshold_grid)
    def check(x):
        if isinstance(x,dict):
            assert not {'best_threshold','optimal_threshold','recommended_threshold'} & x.keys()
            for value in x.values():check(value)
        elif isinstance(x,list):
            for value in x:check(value)
    check(r)


def test_m3_stale_rejection_not_resurrected():
    obs,outs=dataset(stale=True,p='.9',delta='.2');r=report(obs,outs)
    assert r['coverage']['edge_candidates']==4 and r['coverage']['m3_admissible_candidates']==0
    assert all(s['admissible_candidates']==0 for s in r['sensitivity'])
    assert r['coverage']['eligible_research_observations']==4
    assert all('STALE_SOURCE' in x['m3_reasons'] for x in r['observations'])


def test_cost_stress_positive_to_negative_without_mutation():
    obs,outs=dataset(n=1,delta='.05',fee='.02');before=obs[0].payload_json
    r=report(obs,outs);stress=[x for x in r['sensitivity'] if x['scenario']=='COST_MULTIPLIER']
    assert D(stress[0]['rows'][0]['hypothetical_net_edge'])==D('.02')
    assert D(stress[-1]['rows'][0]['hypothetical_net_edge'])==D('-.02')
    assert stress[0]['admissible_candidates']==1 and stress[-1]['admissible_candidates']==0
    assert obs[0].payload_json==before


def test_future_outcome_changes_only_analytics():
    obs,outs=dataset(n=1);before=obs[0].payload_json
    a=result(obs,outs);b=result(obs,(replace(outs[0],yes_payout=D(0)),))
    assert a.report_json!=b.report_json and a.input_hash!=b.input_hash
    assert obs[0].payload_json==before  # all four upstream IDs and full content unchanged


def test_outcome_cutoff_and_posthoc_contract():
    obs,outs=dataset(n=1);o=outs[0]
    assert report(obs,outs,cutoff=o.available_at-1)['coverage']['resolved_rows']==0
    assert report(obs,outs,cutoff=o.available_at)['coverage']['resolved_rows']==1
    data=obs[0].data();at=data['decision']['evaluated_at']
    bad=replace(o,resolution_at=at,available_at=at)
    r=report(obs,(bad,))
    assert r['coverage']['resolved_rows']==0 and r['coverage']['excluded_reasons']['OUTCOME_NOT_POSTHOC']==1


def test_wrong_rule_source_version_and_isolation():
    obs,outs=dataset(n=1)
    for kwargs in ({'rule_hash':'different'},{'source':'different'},{'settlement_version':'different'}):
        r=report(obs,(replace(outs[0],**kwargs),))
        assert r['coverage']['excluded_reasons']['OUTCOME_CONTRACT_MISMATCH']==1
    with pytest.raises(ValueError,match='cross-experiment'):result(obs,(replace(outs[0],experiment_id='other'),))
    other,_=synthetic_observation('other',0)
    with pytest.raises(ValueError,match='cross-experiment'):result((other,),outs)


def test_duplicate_predictions_and_ambiguous_outcomes_rejected():
    obs,outs=dataset(n=1)
    with pytest.raises(ValueError,match='duplicate'):result(obs+obs,outs)
    with pytest.raises(ValueError,match='ambiguous'):result(obs,outs+outs)


def test_coverage_denominator_does_not_drop_unresolved():
    obs,outs=dataset();a=report(obs,outs);b=report(obs,outs[:1])
    for key in ('total_predictions','valid_snapshot_rows','eligible_research_observations','m3_admissible_candidates','candidate_coverage'):
        assert a['coverage'][key]==b['coverage'][key]
    assert b['coverage']['resolved_rows']==1


def test_missing_snapshot_counted_and_excluded():
    obs,outs=dataset(n=1);data=obs[0].data();data.update(snapshot=None,edge=None,decision=None)
    r=report((ResearchObservation(canonical(data)),),outs)
    assert r['coverage']['total_predictions']==1 and r['coverage']['valid_snapshot_rows']==0
    assert r['coverage']['candidate_coverage'] is None
    assert r['coverage']['excluded_reasons']['MISSING_OR_INCOMPATIBLE_SNAPSHOT']==1


def test_tte_and_chronological_groups_no_edge_changes():
    a,o1=synthetic_observation(EXP,0,tte=20000)
    b,o2=synthetic_observation(EXP,1,tte=150000,at=1704153605000)
    before=(a.payload_json,b.payload_json);r=report((b,a),(o2,o1))
    assert r['tte'][0]['count']==1 and r['tte'][3]['count']==1
    assert [x['utc_day'] for x in r['chronological_periods']]==['2024-01-01','2024-01-02']
    assert before==(a.payload_json,b.payload_json)
    assert a.data()['edge']['yes']['net_edge_per_share']==b.data()['edge']['yes']['net_edge_per_share']


def test_yes_no_and_split_hypothetical_return_units():
    a,o1=synthetic_observation(EXP,0,p='.8',payout=D('.5'),fee='0')
    r=report((a,),(o1,));views=r['edge_analysis_all_scenarios']
    assert [v['side'] for v in views]==['YES','NO','COMBINED']
    yes=a.data()['edge']['yes'];expected=D('.5')-D(yes['cost_breakdown']['collateral_spent'])
    bucket=next(b for b in views[0]['buckets'] if b['count'])
    assert D(bucket['mean_hypothetical_realized_return'])==expected
    assert bucket['split_count']==1 and bucket['binary_win_fraction'] is None
    assert r['hypothetical_sharpe'] is None and r['hypothetical_profit_factor'] is None


def test_empty_analysis_and_determinism():
    assert report((),())['prediction_quality']['brier_payout'] is None
    obs,outs=dataset();first=result(obs,outs)
    with localcontext() as ctx:
        ctx.prec=6;ctx.rounding=ROUND_DOWN
        second=result(tuple(reversed(obs)),tuple(reversed(outs)))
    assert first==second and markdown(first)==markdown(second)
    with pytest.raises(FrozenInstanceError):CFG.minimum_sample_count=1


@pytest.mark.parametrize('changes',[{'threshold_grid':('.03',)},{'cost_multiplier_grid':(1,2)},
    {'minimum_sample_count':1},{'log_loss_epsilon':0},{'log_loss_epsilon':float('nan')},
    {'tte_bucket_edges_ms':(0,1000)},{'calibration_bin_edges':(0,.5,1)}])
def test_fixed_config_and_invalid_values(changes):
    with pytest.raises(ValueError):AnalyticsConfig(**changes)


@pytest.fixture
def stored(tmp_path):
    with Database(StorageConfig(project_root=tmp_path)) as db:
        repo=AnalyticsRepository(db)
        repo.register(Experiment(EXP,CODE,'synthetic-m4',42,0,digest(RESEARCH_CONTRACT)))
        yield repo


def save(repo,obs,outs,**changes):
    cutoff=max(o.available_at for o in outs)+1000
    args=dict(experiment_id=EXP,code_git=CODE,cutoff=cutoff,created_at=cutoff);args.update(changes)
    return repo.run(obs,outs,CFG,**args)


def test_persistence_idempotent_readback(stored):
    obs,outs=dataset();r=save(stored,obs,outs)
    assert r==save(stored,obs,outs,created_at=r.created_at+1000)==stored.get_run(r.analysis_id)
    assert stored.db.connection.execute('SELECT COUNT(*) FROM analysis_runs').fetchone()[0]==1
    assert stored.db.connection.execute('PRAGMA foreign_key_check').fetchall()==[]


def test_conflicting_outcome_retry(stored):
    obs,outs=dataset(n=1);r=save(stored,obs,outs)
    with pytest.raises(ValueError,match='conflicting'):save(stored,obs,(replace(outs[0],yes_payout=D(0)),))
    assert stored.get_run(r.analysis_id)==r


@pytest.mark.parametrize('table,key',[('resolved_outcomes','payload_hash'),('analysis_runs','input_hash'),('analysis_results','result_hash')])
def test_corrupt_read_and_immutable_records(stored,table,key):
    obs,outs=dataset(n=1);r=save(stored,obs,outs);conn=stored.db.connection
    for sql in (f"UPDATE {table} SET {key}='changed'",f'DELETE FROM {table}',f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}'):
        with pytest.raises(sqlite3.IntegrityError):conn.execute(sql)
        conn.rollback()
    conn.execute(f'DROP TRIGGER {table}_immutable_update')
    conn.execute(f"UPDATE {table} SET {key}='changed'");conn.commit()
    with pytest.raises(ValueError,match='integrity'):stored.get_run(r.analysis_id)


def test_atomic_analysis_failure(stored):
    obs,outs=dataset();conn=stored.db.connection
    conn.execute("CREATE TRIGGER fail_result BEFORE INSERT ON analysis_results BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):save(stored,obs,outs)
    assert all(conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0 for table in
               ('resolved_outcomes','analysis_runs','analysis_results'))


def test_fk_and_schema4_reopen(stored):
    obs,outs=dataset(n=1);r=save(stored,obs,outs);conn=stored.db.connection
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute('INSERT INTO analysis_results VALUES (?,?,?,?)',('missing',EXP,'{}','hash'))
    conn.rollback()
    with Database(StorageConfig(project_root=stored.db.path.parents[2])) as db:
        assert AnalyticsRepository(db).get_run(r.analysis_id)==r
        names={x[0] for x in db.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert len(names)==10 and not names & {'orders','fills','positions','ledger','settlements','risk'}


def test_migration_rollback(tmp_path,monkeypatch):
    import btc5_v3.storage.analytics_repository as module
    from btc5_v3.storage.edge_repository import migrate_m2
    from btc5_v3.storage.decision_repository import migrate_m3
    with Database(StorageConfig(project_root=tmp_path)) as db:
        migrate_m2(db);migrate_m3(db)
        monkeypatch.setattr(module,'DDL',module.DDL+('INVALID SQL',))
        with pytest.raises(sqlite3.OperationalError):migrate_m4(db)
        assert db.connection.execute('PRAGMA user_version').fetchone()[0]==3
        assert db.connection.execute("SELECT name FROM sqlite_master WHERE name='resolved_outcomes'").fetchall()==[]


def test_synthetic_demo_report_and_repeat(tmp_path):
    a=run_demo(tmp_path,CODE);b=run_demo(tmp_path,CODE)
    assert a==b
    r=json.loads(a.report_json)
    assert r['coverage']['split_count']==4 and r['coverage']['resolved_rows']==64
    well=next(x for x in r['by_model'] if x['model_version']=='well-calibrated-synthetic')
    assert D(well['ece'])==0
    assert (tmp_path/'runtime/v3/m4-report.md').read_text(encoding='utf-8')==markdown(a)


def test_share_deducted_fee_stress_units_and_invalid_stress():
    from btc5_v3.edge.costs import FeeModel
    obs,outs=dataset(n=1,p='.8',delta='.2',fee_model=FeeModel(denomination='SHARES',rate='.1'))
    r=report(obs,outs);stress=[x for x in r['sensitivity'] if x['scenario']=='COST_MULTIPLIER']
    assert D(stress[0]['rows'][0]['hypothetical_net_edge'])==D('.11')
    assert D(stress[-1]['rows'][0]['hypothetical_net_edge'])==D('-.05')
    obs,outs=dataset(n=1,p='.9',delta='.8',fee_model=FeeModel(denomination='SHARES',rate='.5'))
    r=report(obs,outs)
    assert r['sensitivity'][-1]['rows'][0]['status']=='INVALID_SHARE_FEE_STRESS'
    assert r['sensitivity'][-1]['admissible_candidates']==0


def test_lineage_change_excluded_from_candidate_coverage():
    obs,outs=dataset(n=1);data=obs[0].data();data['edge']['p_yes']='.9'
    r=report((ResearchObservation(canonical(data)),),outs)
    assert r['coverage']['eligible_research_observations']==0
    assert r['coverage']['excluded_reasons']['MISSING_OR_INCOMPATIBLE_EDGE']==1


def test_m3_reasons_counted_separately():
    obs,outs=dataset(n=2,stale=True)
    assert report(obs,outs)['coverage']['m3_rejection_reasons']['STALE_SOURCE']==2


def test_settlement_direction_groups_are_posthoc():
    obs,outs=dataset(n=3)
    outs=(outs[0],replace(outs[1],yes_payout=D(0)),replace(outs[2],yes_payout=D('.5')))
    r=report(obs,outs)
    assert [g['direction'] for g in r['by_settlement_direction']]==['YES','NO','SPLIT']
    assert [g['count'] for g in r['by_settlement_direction']]==[1,1,1]


@pytest.mark.parametrize('payout',['.4','-1','2','NaN','Infinity'])
def test_outcome_contract_rejects_invalid_payout(payout):
    _,outs=dataset(n=1)
    with pytest.raises(ValueError):replace(outs[0],yes_payout=payout)


def test_creation_metadata_and_cutoff_required():
    obs,outs=dataset(n=1)
    with pytest.raises(ValueError):
        analyze(obs,outs,CFG,experiment_id=EXP,code_git=CODE,cutoff=100,created_at=99)


def test_future_prediction_not_in_denominator():
    obs,outs=dataset(n=1);at=obs[0].data()['prediction']['available_at']
    r=report(obs,outs,cutoff=at-1)
    assert r['coverage']['total_predictions']==0 and r['coverage']['candidate_coverage'] is None
    assert r['coverage']['excluded_reasons']['PREDICTION_AFTER_CUTOFF']==1


def test_readback_does_not_absorb_later_outcomes(stored):
    obs,outs=dataset(n=2);first=save(stored,obs,(outs[0],))
    later=save(stored,obs,outs)
    assert later.analysis_id!=first.analysis_id and stored.get_run(first.analysis_id)==first


def test_concurrent_analytics_same_input_is_one_run(stored):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    obs,outs=dataset(n=1);root=stored.db.path.parents[2];barrier=threading.Barrier(2)
    def worker():
        barrier.wait(timeout=10)
        with Database(StorageConfig(project_root=root)) as db:return save(AnalyticsRepository(db),obs,outs)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a,b=list(pool.map(lambda _:worker(),range(2)))
    assert a==b==stored.get_run(a.analysis_id)
    assert stored.db.connection.execute('SELECT COUNT(*) FROM analysis_runs').fetchone()[0]==1
