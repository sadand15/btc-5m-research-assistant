"""M3 synthetic-only gates. No production database, live API or performance input."""
from dataclasses import asdict, replace, FrozenInstanceError
from decimal import Decimal, localcontext, ROUND_DOWN
import json
import sqlite3

import pytest

from btc5_v3.config.models import StorageConfig, ValidatorConfig
from btc5_v3.encoding import canonical
from btc5_v3.experiments.models import Experiment
from btc5_v3.market.normalize import raw_event
from btc5_v3.market.validation import validate_market
from btc5_v3.models.models import Prediction, TargetDefinition
from btc5_v3.edge.costs import EdgeConfig
from btc5_v3.edge.engine import evaluate_edge
from btc5_v3.decision.config import DecisionConfig
from btc5_v3.decision.models import GATES
from btc5_v3.decision.policy import decide
from btc5_v3.storage.database import Database
from btc5_v3.storage.repository import Repository
from btc5_v3.storage.edge_repository import EdgeRepository
from btc5_v3.storage.decision_repository import DecisionRepository, migrate_m3

D=Decimal


def validator():
    return ValidatorConfig('m3-market','SYNTHETIC','m3-rule',clock_skew_tolerance_ms=2000)


def payload(**changes):
    values=dict(market_id='m3-market',source_at=4000,expiry=301000,market_type='CRYPTO_UP_DOWN',
                feed='SYNTHETIC',rule_hash='m3-rule',outcome_mapping='YES_UP',
                yes_bids=[['.59','100']],yes_asks=[['.61','100']],
                market_status='OPEN',market_status_at=4000,market_status_available_at=4000)
    values.update(changes)
    return values


def snapshot(received=4000,available=4000,**changes):
    event=raw_event(payload(**changes),experiment_id='m3-exp',source='synthetic',received_at=received,sequence=1)
    result=validate_market(event,validator(),evaluation_at=available)
    assert result.snapshot is not None
    return result.snapshot


def prediction(**changes):
    values=dict(experiment_id='m3-exp',prediction_key='m3-p',market_id='m3-market',p_yes='.70',
                model_version='synthetic-model',model_hash='a'*64,feature_version='synthetic-feature',
                feature_hash='b'*64,input_cutoff=4000,available_at=4500,calibration_version='none',
                target_definition=TargetDefinition('YES_UP','m3-rule',301000,
                                                   target_source='synthetic-oracle',target_feed='SYNTHETIC'))
    values.update(changes)
    return Prediction(**values)


def config(ec=None,**changes):
    values=dict(market_id='m3-market',source='synthetic',feed='SYNTHETIC',rule_hash='m3-rule',
                outcome_mapping='YES_UP',prediction_target_source='synthetic-oracle',
                expected_model_hash='a'*64,expected_edge_config_hash=(ec or EdgeConfig()).hash,
                target_source_confirmed=True,semantic_contract_hash='c'*64)
    values.update(changes)
    return DecisionConfig(**values)


def inputs(s=None,p=None,ec=None,edge_at=5000):
    s=s or snapshot();p=p or prediction();ec=ec or EdgeConfig()
    return s,p,evaluate_edge(s,p,ec,evaluation_at=edge_at)


def run(s=None,p=None,e=None,c=None,t=5000,ec=None):
    ss,pp,ee=inputs(s,p,ec)
    return decide(ss,pp,e or ee,c or config(ec),experiment_id='m3-exp',attempt_key='attempt-1',evaluation_at=t)


def test_admissible_yes_and_immutable():
    result=run()
    assert result.requested_action==result.final_action=='BUY_YES'
    assert result.primary_reason is None and result.all_reasons==()
    assert result.edge_per_share==D('.09') and result.expected_value_total==D('.09')
    assert result.purpose=='RESEARCH_SIMULATION_CANDIDATE_NOT_ORDER'
    assert tuple(x.gate for x in result.gate_results)==tuple(name for name,_ in GATES)
    with pytest.raises(FrozenInstanceError): result.final_action='BUY_NO'


def test_mandatory_source_freshness():
    result=run(s=snapshot(source_at=1000))
    assert result.source_age_ms==4000 and result.receipt_age_ms==1000
    assert result.final_action=='NO_TRADE'
    assert result.primary_reason=='STALE_SOURCE' and result.all_reasons==('STALE_SOURCE',)


def test_mandatory_spread_no_cost_double_count(monkeypatch):
    s,p,e=inputs();before=e.to_json()
    import btc5_v3.edge.engine as engine
    monkeypatch.setattr(engine,'evaluate_edge',lambda *a,**k:pytest.fail('M3 must not recompute M2 math'))
    accepted=decide(s,p,e,config(max_absolute_spread='.02'),experiment_id='m3-exp',attempt_key='a',evaluation_at=5000)
    rejected=decide(s,p,e,config(max_absolute_spread='.019'),experiment_id='m3-exp',attempt_key='b',evaluation_at=5000)
    assert accepted.final_action=='BUY_YES' and rejected.primary_reason=='SPREAD_TOO_WIDE'
    assert accepted.spread==rejected.spread==D('.02')
    assert accepted.edge_per_share==rejected.edge_per_share==e.yes.net_edge_per_share==D('.09')
    assert accepted.expected_value_total==rejected.expected_value_total==e.yes.net_ev_total
    assert e.to_json()==before


def test_mandatory_depth_fraction():
    ec=EdgeConfig(target_shares=100,minimum_executable_fraction='.1')
    result=run(s=snapshot(yes_asks=[['.61','60']]),ec=ec)
    assert result.requested_action=='BUY_YES' and result.final_action=='NO_TRADE'
    assert result.requested_shares==100 and result.executable_shares==60 and result.executable_fraction==D('.6')
    assert result.primary_reason=='INSUFFICIENT_DEPTH'


def test_mandatory_near_settlement():
    s=snapshot(expiry=10000);p=prediction(target_definition=replace(prediction().target_definition,expiry=10000))
    r=run(s=s,p=p)
    assert r.time_to_expiry_ms==5000 and r.final_action=='NO_TRADE'
    assert r.primary_reason=='MARKET_NEAR_SETTLEMENT'


@pytest.mark.parametrize('field,value,reason',[
    ('experiment_id','other','EXPERIMENT_MISMATCH'),('market_id','other','MARKET_MISMATCH'),
    ('prediction_key','other','PREDICTION_MISMATCH'),('p_yes','.71','EDGE_LINEAGE_MISMATCH')])
def test_prediction_lineage(field,value,reason):
    s,p,e=inputs();r=run(s=s,p=replace(p,**{field:value}),e=e)
    assert r.final_action=='NO_TRADE' and r.primary_reason==reason


@pytest.mark.parametrize('field,value,reason',[
    ('snapshot_id','bad','SNAPSHOT_MISMATCH'),('prediction_id','bad','PREDICTION_MISMATCH'),
    ('edge_id','bad','EDGE_LINEAGE_MISMATCH'),('config_hash','d'*64,'EDGE_LINEAGE_MISMATCH'),
    ('edge_version','edge-other','EDGE_LINEAGE_MISMATCH'),('preferred_side','NO','EDGE_LINEAGE_MISMATCH')])
def test_edge_lineage(field,value,reason):
    s,p,e=inputs();r=run(s=s,p=p,e=replace(e,**{field:value}))
    assert r.final_action=='NO_TRADE' and reason in r.all_reasons


@pytest.mark.parametrize('changes,reason',[
    ({'rule_hash':'other'},'RULE_MISMATCH'),({'feed':'OTHER'},'FEED_MISMATCH'),
    ({'outcome_mapping':'YES_DOWN'},'TARGET_MISMATCH'),({'source':'OTHER'},'PRICE_SOURCE_MISMATCH'),
    ({'target_source_confirmed':False},'TARGET_SOURCE_MISMATCH'),
    ({'expected_model_hash':'d'*64},'TARGET_SOURCE_MISMATCH')])
def test_contract_consistency(changes,reason):
    r=run(c=config(**changes))
    assert r.final_action=='NO_TRADE' and r.primary_reason==reason


def test_target_source_not_silently_equated_to_venue():
    p=prediction(target_definition=replace(prediction().target_definition,target_source='BINANCE'))
    r=run(p=p)
    assert r.primary_reason=='TARGET_SOURCE_MISMATCH'
    assert r.basis_bps is None


def test_unknown_target_source_rejected():
    p=prediction(target_definition=TargetDefinition('YES_UP','m3-rule',301000))
    assert run(p=p).primary_reason=='TARGET_SOURCE_MISMATCH'


@pytest.mark.parametrize('kind,reason',[
    ('snapshot','SNAPSHOT_NOT_AVAILABLE'),('prediction','PREDICTION_NOT_AVAILABLE'),
    ('edge','EDGE_NOT_AVAILABLE'),('source','NEGATIVE_SOURCE_AGE'),
    ('receipt','NEGATIVE_RECEIPT_AGE')])
def test_future_and_negative_times(kind,reason):
    s=snapshot();p=prediction();ec=EdgeConfig();t=5000
    if kind=='snapshot': s=snapshot(available=5001)
    if kind=='prediction': p=prediction(available_at=5001)
    if kind=='source': s=snapshot(source_at=5001)
    if kind=='receipt': s=snapshot(received=5001,available=5001)
    _,_,e=inputs(s,p,ec,edge_at=6000 if kind in ('snapshot','prediction','source','receipt') else 5001)
    r=run(s=s,p=p,e=e,t=t)
    assert r.final_action=='NO_TRADE' and reason in r.all_reasons


@pytest.mark.parametrize('age,reason',[(2000,None),(2001,'STALE_RECEIPT')])
def test_receipt_age_boundary(age,reason):
    r=run(c=config(max_source_age_ms=10000),t=4000+age)
    assert (reason in r.all_reasons) if reason else r.final_action=='BUY_YES'


@pytest.mark.parametrize('age,reason',[(3000,None),(3001,'STALE_SOURCE')])
def test_source_age_boundary(age,reason):
    r=run(c=config(max_receipt_age_ms=10000),t=4000+age)
    assert (reason in r.all_reasons) if reason else r.final_action=='BUY_YES'


@pytest.mark.parametrize('tte,reason',[(10000,None),(9999,'MARKET_NEAR_SETTLEMENT'),(0,'MARKET_EXPIRED'),(-1,'MARKET_EXPIRED')])
def test_expiry_boundary(tte,reason):
    s=snapshot(expiry=15000);p=prediction(target_definition=replace(prediction().target_definition,expiry=15000))
    c=config(max_receipt_age_ms=20000,max_source_age_ms=20000,max_market_status_age_ms=20000)
    r=run(s=s,p=p,c=c,t=15000-tte)
    assert (reason in r.all_reasons) if reason else r.final_action=='BUY_YES'


@pytest.mark.parametrize('limit,accepted',[('.019',False),('.02',True),('.021',True)])
def test_absolute_spread_boundary(limit,accepted):
    assert (run(c=config(max_absolute_spread=limit)).final_action=='BUY_YES')==accepted


@pytest.mark.parametrize('limit,accepted',[('.031',False),('.03125',True),('.032',True)])
def test_normalized_spread_boundary(limit,accepted):
    # spread .02 / mid .64 = .03125, exactly representable.
    r=run(s=snapshot(yes_bids=[['.63','100']],yes_asks=[['.65','100']]),
          c=config(max_normalized_spread=limit))
    assert r.normalized_spread==D('.03125')
    assert (r.final_action=='BUY_YES')==accepted


@pytest.mark.parametrize('quantity,accepted',[('100',True),('80',True),('79.9',False)])
def test_partial_depth_boundaries(quantity,accepted):
    ec=EdgeConfig(target_shares=100,minimum_executable_fraction='.1')
    r=run(s=snapshot(yes_asks=[['.61',quantity]]),ec=ec)
    assert (r.final_action=='BUY_YES')==accepted


def test_minimum_absolute_shares():
    r=run(c=config(minimum_executable_shares=2))
    assert r.primary_reason=='INSUFFICIENT_DEPTH'


def test_zero_requested_and_zero_executable_fail_closed():
    s,p,e=inputs()
    zero=replace(e.yes,requested_shares=D(0),executable_shares=D(0),unfilled_shares=D(0),liquidity_used=())
    r=run(s=s,p=p,e=replace(e,requested_shares=D(0),yes=zero))
    assert r.final_action=='NO_TRADE' and 'INVALID_REQUESTED_SHARES' in r.all_reasons
    zero=replace(e.yes,executable_shares=D(0),unfilled_shares=D(1),liquidity_used=())
    r=run(s=s,p=p,e=replace(e,yes=zero))
    assert r.primary_reason=='INSUFFICIENT_DEPTH' and r.executable_fraction==0


def test_derived_no_keeps_origin_without_consumption():
    s,p,e=inputs(p=prediction(p_yes='.30'));before=s.to_json()
    r=run(s=s,p=p,e=e)
    assert r.final_action==r.requested_action=='BUY_NO' and r.side=='NO'
    assert r.liquidity_independent is False and r.liquidity_used==e.no.liquidity_used
    assert all(x.derived and x.liquidity_origin=='YES_BID' for x in r.liquidity_used)
    assert s.to_json()==before and 'derived' not in r.all_reasons


def test_upstream_no_trade_never_reselected():
    r=run(p=prediction(p_yes='.60'))
    assert r.requested_action==r.final_action=='NO_TRADE'
    assert r.primary_reason=='UPSTREAM_NO_EDGE'
    assert r.edge_per_share is None and r.side is None


def test_multi_reason_fixed_precedence():
    ec=EdgeConfig(target_shares=100,minimum_executable_fraction='.1')
    s=snapshot(source_at=1000,yes_asks=[['.65','60']],yes_bids=[['.55','100']])
    r=run(s=s,ec=ec)
    assert r.primary_reason=='STALE_SOURCE'
    assert r.all_reasons==('STALE_SOURCE','SPREAD_TOO_WIDE','INSUFFICIENT_DEPTH')
    assert r.gate_results[-1].status=='BLOCKED'


@pytest.mark.parametrize('status,reason',[('CLOSED','MARKET_NOT_OPEN'),('SUSPENDED','MARKET_NOT_OPEN'),('UNKNOWN','MARKET_STATUS_UNKNOWN')])
def test_market_status(status,reason):
    r=run(s=snapshot(market_status=status))
    assert r.primary_reason==reason and r.final_action=='NO_TRADE'


def test_missing_market_status_never_assumed_open():
    data=payload()
    for key in ('market_status','market_status_at','market_status_available_at'): del data[key]
    event=raw_event(data,experiment_id='m3-exp',source='synthetic',received_at=4000,sequence=1)
    s=validate_market(event,validator(),evaluation_at=4000).snapshot
    r=run(s=s)
    assert r.primary_reason=='DATA_INCOMPLETE' and 'MARKET_STATUS_UNKNOWN' in r.all_reasons
    assert 'market_status' not in json.loads(s.to_json())  # preserves old M1 representation


def test_market_status_own_age_is_gated():
    r=run(s=snapshot(market_status_at=0),c=config(max_market_status_age_ms=4999))
    assert r.primary_reason=='MARKET_STATUS_STALE'


def test_basis_required_missing_fails_closed():
    r=run(c=config(require_basis=True,max_basis_bps=20))
    assert r.primary_reason=='REFERENCE_PRICE_MISSING' and r.basis_bps is None


@pytest.mark.parametrize('price,accepted',[('100.2',True),('99.8',True),('100.2001',False),('99.7999',False)])
def test_basis_boundaries(price,accepted):
    s=snapshot(reference_underlying_price='100',reference_price_at=4000)
    p=prediction(target_definition=replace(prediction().target_definition,reference_price=D(price),reference_price_at=4000))
    r=run(s=s,p=p,c=config(require_basis=True,max_basis_bps=20))
    assert (r.final_action=='BUY_YES')==accepted
    assert r.observed_basis==D(price)-100
    assert r.basis_bps==(D(price)/100-1)*10000


def test_basis_not_computed_for_semantic_mismatch():
    s=snapshot(reference_underlying_price='100',reference_price_at=4000)
    p=prediction(target_definition=replace(prediction().target_definition,reference_price=D('100'),reference_price_at=4000,target_source='BINANCE'))
    r=run(s=s,p=p,c=config(require_basis=True,max_basis_bps=20))
    assert r.primary_reason=='TARGET_SOURCE_MISMATCH' and r.basis_bps is None


def test_reference_availability_and_staleness():
    s=snapshot(reference_underlying_price='100',reference_price_at=5001)
    assert 'REFERENCE_NOT_AVAILABLE' in run(s=s).all_reasons
    s=snapshot(reference_underlying_price='100',reference_price_at=1000)
    assert run(s=s,c=config(require_reference_price=True)).primary_reason=='REFERENCE_STALE'


def test_missing_inputs_are_normal_no_trade():
    r=decide(None,None,None,config(),experiment_id='m3-exp',attempt_key='missing',evaluation_at=5000)
    assert r.final_action=='NO_TRADE' and r.primary_reason=='DATA_INCOMPLETE'


def test_deterministic_config_and_decimal_context():
    c=config();r=run(c=c)
    assert c.hash==DecisionConfig(**json.loads(canonical(asdict(c)))).hash
    assert c.hash!=replace(c,max_source_age_ms=3001).hash
    with localcontext() as ctx:
        ctx.prec=6;ctx.rounding=ROUND_DOWN
        assert run(c=c).to_json()==r.to_json()
    with pytest.raises(FrozenInstanceError): c.max_source_age_ms=10000


@pytest.mark.parametrize('changes',[{'max_receipt_age_ms':-1},{'max_source_age_ms':True},
    {'minimum_executable_fraction':0},{'max_absolute_spread':float('nan')},
    {'require_basis':True},{'max_basis_bps':10},{'semantic_contract_hash':None}])
def test_invalid_config(changes):
    with pytest.raises(ValueError): config(**changes)


@pytest.fixture
def stored(tmp_path):
    with Database(StorageConfig(project_root=tmp_path)) as db:
        market=Repository(db,validator())
        market.register(Experiment('m3-exp','a'*40,'synthetic-m3',42,900,validator().hash))
        s=market.ingest(payload(),experiment_id='m3-exp',source='synthetic',received_at=4000,sequence=1,evaluation_at=4000).snapshot
        er=EdgeRepository(market);p=prediction();e=er.evaluate_and_store(s.snapshot_id,p,EdgeConfig(),evaluation_at=5000)
        yield DecisionRepository(er),s,p,e


def store(stored,**changes):
    repo,s,p,e=stored
    args=dict(config=config(),experiment_id='m3-exp',attempt_key='attempt-1',evaluation_at=5000,
              prediction_id=p.prediction_id,snapshot_id=s.snapshot_id,edge_id=e.edge_id)
    args.update(changes)
    return repo.decide_and_store(**args)


def test_persistence_idempotent(stored):
    repo,s,p,e=stored;r=store(stored)
    assert r==store(stored)==repo.get_decision(r.decision_id)
    assert repo.db.connection.execute('SELECT COUNT(*) FROM decisions').fetchone()[0]==1
    assert repo.db.connection.execute('PRAGMA foreign_key_check').fetchall()==[]


@pytest.mark.parametrize('changes',[{'evaluation_at':5001},{'config':config(max_source_age_ms=3001)},{'edge_id':None}])
def test_conflicting_retry(stored,changes):
    before=store(stored)
    with pytest.raises(ValueError,match='conflicting'):store(stored,**changes)
    assert stored[0].get_decision(before.decision_id)==before


def test_missing_inputs_persist_with_nullable_fk(stored):
    r=store(stored,prediction_id=None,snapshot_id=None,edge_id=None)
    assert r.primary_reason=='DATA_INCOMPLETE' and stored[0].get_decision(r.decision_id)==r


def test_cross_experiment_and_fk(stored):
    repo,s,p,e=stored
    repo.edges.market.register(Experiment('other','b'*40,'synthetic-m3',42,900,validator().hash))
    with pytest.raises(ValueError,match='cross-experiment'): store(stored,experiment_id='other')
    r=store(stored);conn=repo.db.connection
    values=list(conn.execute('SELECT * FROM decisions').fetchone());values[0]='bad';values[1]='other';values[2]='other-attempt'
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute('INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?,?)',values)
    conn.rollback()
    assert repo.get_decision(r.decision_id)==r


def test_corrupted_read_and_immutable_sql(stored):
    repo,s,p,e=stored;r=store(stored);conn=repo.db.connection
    for sql in ("UPDATE decisions SET payload_hash='changed'",'DELETE FROM decisions',
                'INSERT OR REPLACE INTO decisions SELECT * FROM decisions'):
        with pytest.raises(sqlite3.IntegrityError):conn.execute(sql)
        conn.rollback()
    conn.execute('DROP TRIGGER decisions_immutable_update')
    conn.execute("UPDATE decisions SET payload_hash='changed'");conn.commit()
    with pytest.raises(ValueError,match='integrity'):repo.get_decision(r.decision_id)


def test_atomic_write_failure(stored):
    repo,s,p,e=stored;conn=repo.db.connection
    before=repo.edges.market.counts()
    conn.execute("CREATE TRIGGER fail_decision BEFORE INSERT ON decisions BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):store(stored)
    assert conn.execute('SELECT COUNT(*) FROM decisions').fetchone()[0]==0
    assert repo.edges.market.counts()==before and repo.edges.get_edge(e.edge_id)==e


def test_future_event_cannot_change_past_decision(stored):
    repo,s,p,e=stored;before=store(stored)
    later=payload(source_at=15000,market_status_at=15000,market_status_available_at=15000,
                  yes_bids=[['.89','3']],yes_asks=[['.90','4']])
    repo.edges.market.ingest(later,experiment_id='m3-exp',source='synthetic',received_at=15000,sequence=2,evaluation_at=15000)
    assert store(stored)==before==repo.get_decision(before.decision_id)


def test_schema3_reopen_and_no_future_tables(stored):
    repo,s,p,e=stored;migrate_m3(repo.db)
    with Database(StorageConfig(project_root=repo.db.path.parents[2])) as db:
        again=DecisionRepository(EdgeRepository(Repository(db,validator())))
        assert db.connection.execute('PRAGMA user_version').fetchone()[0]==3
        tables={x[0] for x in db.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert tables=={'experiments','raw_market_events','market_validation_events','market_snapshots',
                        'predictions','edge_evaluations','decisions'}
        assert again.edges.get_edge(e.edge_id)==e


def test_migration_failure_rolls_back(tmp_path,monkeypatch):
    import btc5_v3.storage.decision_repository as module
    with Database(StorageConfig(project_root=tmp_path)) as db:
        EdgeRepository(Repository(db,validator()))
        monkeypatch.setattr(module,'DDL',module.DDL+('INVALID SQL',))
        with pytest.raises(sqlite3.OperationalError):migrate_m3(db)
        assert db.connection.execute('PRAGMA user_version').fetchone()[0]==2
        assert db.connection.execute("SELECT name FROM sqlite_master WHERE name='decisions'").fetchall()==[]


def test_gate_order_is_versioned_contract():
    assert [name for name,_ in GATES]==[
        'IDENTITY','AVAILABILITY','MARKET_STATUS','FRESHNESS','SOURCE_RULE',
        'EDGE','SPREAD','LIQUIDITY','NEAR_EXPIRY','FINAL']
    s,p,e=inputs(s=snapshot(source_at=1000))
    r=run(s=s,p=replace(p,market_id='wrong',available_at=6000),e=e)
    assert r.primary_reason=='MARKET_MISMATCH'
    assert r.all_reasons.index('PREDICTION_NOT_AVAILABLE') < r.all_reasons.index('STALE_SOURCE')


def test_availability_and_status_age_equal_boundaries():
    s=snapshot(available=5000,market_status_at=0)
    p=prediction(available_at=5000)
    assert run(s=s,p=p).final_action=='BUY_YES'


def test_normalized_spread_rounding_cannot_relax_gate():
    # Report rounds 1/30, but the exact cross-product must reject a lower max.
    r=run(c=config(max_normalized_spread='.033333333333333333'))
    assert r.normalized_spread==D('.033333333333333333')
    assert r.primary_reason=='SPREAD_TOO_WIDE'


def test_bad_liquidity_lineage_rejected():
    s,p,e=inputs()
    bad=replace(e.yes,liquidity_used=(replace(e.yes.liquidity_used[0],liquidity_id='wrong'),))
    r=run(s=s,p=p,e=replace(e,yes=bad))
    assert r.primary_reason=='EDGE_LINEAGE_MISMATCH'


@pytest.mark.parametrize('changes',[{'market_status':'OTHER'},{'market_status_at':-1},
                                  {'market_status_available_at':4001},{'market_status_at':5000}])
def test_market_metadata_validation(changes):
    event=raw_event(payload(**changes),experiment_id='m3-exp',source='synthetic',received_at=4000,sequence=1)
    r=validate_market(event,validator(),evaluation_at=4000)
    assert r.status=='INVALID' and r.snapshot is None


def test_old_prediction_bytes_preserved():
    p=prediction(target_definition=TargetDefinition('YES_UP','m3-rule',301000))
    value=json.loads(p.to_json())
    assert set(value['target_definition'])=={'outcome_mapping','rule_hash','expiry','probability_semantics'}
    assert Prediction.from_dict(value)==p


def test_target_reference_cannot_follow_model_cutoff():
    with pytest.raises(ValueError,match='cutoff'):
        prediction(target_definition=replace(prediction().target_definition,reference_price=D(100),reference_price_at=4001))


def test_demo_all_four_scenarios_and_idempotency(tmp_path):
    from btc5_v3.decision.demo import run_demo
    result=run_demo(tmp_path,'a'*40)
    assert result==run_demo(tmp_path,'a'*40)
    decisions=[s['decision'] for s in result['scenarios']]
    assert [d['final_action'] for d in decisions]==['BUY_YES','NO_TRADE','NO_TRADE','NO_TRADE']
    assert [d['primary_reason'] for d in decisions]==[None,'STALE_SOURCE','SPREAD_TOO_WIDE','INSUFFICIENT_DEPTH']


def test_concurrent_decisions_idempotent(stored):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    repo,s,p,e=stored;root=repo.db.path.parents[2];barrier=threading.Barrier(2)
    def worker():
        barrier.wait(timeout=10)
        with Database(StorageConfig(project_root=root)) as db:
            other=DecisionRepository(EdgeRepository(Repository(db,validator())))
            return store((other,s,p,e))
    with ThreadPoolExecutor(max_workers=2) as pool:
        a,b=list(pool.map(lambda _:worker(),range(2)))
    assert a==b==repo.get_decision(a.decision_id)
    assert repo.db.connection.execute('SELECT COUNT(*) FROM decisions').fetchone()[0]==1
