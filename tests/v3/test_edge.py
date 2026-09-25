"""All fixtures synthetic. No V2 runtime, observations, credentials or network."""
from dataclasses import asdict, replace, FrozenInstanceError
from decimal import Decimal, localcontext, ROUND_DOWN
import json
import sqlite3

import pytest

from btc5_v3.config.models import StorageConfig, ValidatorConfig
from btc5_v3.experiments.models import Experiment
from btc5_v3.market.normalize import raw_event
from btc5_v3.market.validation import validate_market
from btc5_v3.models.models import Prediction, TargetDefinition
from btc5_v3.edge.costs import EdgeConfig, FeeModel
from btc5_v3.edge.engine import evaluate_edge
from btc5_v3.storage.database import Database
from btc5_v3.storage.repository import Repository
from btc5_v3.storage.edge_repository import EdgeRepository, migrate_m2
from btc5_v3.encoding import canonical

D = Decimal


def payload(**changes):
    result = dict(market_id='synthetic-edge', source_at=1000, expiry=301000,
                  market_type='CRYPTO_UP_DOWN', feed='SYNTHETIC', rule_hash='rule-v1',
                  outcome_mapping='YES_UP', yes_bids=[['0.59', '2'], ['0.57', '3']],
                  yes_asks=[['0.61', '2'], ['0.65', '3']])
    result.update(changes)
    return result


def validator(**changes):
    return ValidatorConfig(market_id='synthetic-edge', feed='SYNTHETIC', rule_hash='rule-v1', **changes)


def snapshot(*, received_at=4000, source_at=1000, available_at=4000, **changes):
    tolerance = max(0, source_at - received_at)
    cfg = validator(clock_skew_tolerance_ms=tolerance)
    event = raw_event(payload(source_at=source_at, **changes), experiment_id='exp-edge',
                      source='synthetic', received_at=received_at, sequence=1)
    result = validate_market(event, cfg, evaluation_at=available_at)
    assert result.snapshot is not None
    return result.snapshot


def prediction(**changes):
    values = dict(experiment_id='exp-edge', prediction_key='prediction-1', market_id='synthetic-edge',
                  p_yes='0.70', model_version='synthetic-v1', model_hash='a'*64,
                  feature_version='synthetic-features-v1', feature_hash='b'*64,
                  input_cutoff=4000, available_at=4500, calibration_version='none',
                  target_definition=TargetDefinition('YES_UP', 'rule-v1', 301000))
    values.update(changes)
    return Prediction(**values)


def edge(p=None, cfg=None, s=None, at=5000):
    return evaluate_edge(s or snapshot(), p or prediction(), cfg or EdgeConfig(), evaluation_at=at)


@pytest.mark.parametrize('probability', [0, 1, .7, '0.7', D('.7')])
def test_probability_valid(probability):
    assert prediction(p_yes=probability).p_yes == D(str(probability))


@pytest.mark.parametrize('probability', [-.01, 1.01, float('nan'), float('inf'), '-Infinity', True, 'bad'])
def test_probability_invalid(probability):
    with pytest.raises(ValueError): prediction(p_yes=probability)


def test_probability_endpoints_and_no_side():
    assert edge(prediction(p_yes=1)).candidate_action == 'BUY_YES'
    result = edge(prediction(p_yes=0))
    assert result.candidate_action == 'BUY_NO'
    assert result.no.probability == 1 and result.no.net_edge_per_share == D('.59')


def test_spread_not_double_charged_regression():
    result = edge()
    assert result.yes_mid == D('.60') and result.no_mid == D('.40')
    assert result.yes.raw_edge == D('.10') and result.no.raw_edge == D('-.10')
    assert result.yes.executable_edge_before_costs == D('.09')
    assert result.yes.net_edge_per_share == D('.09') != D('.08')
    assert result.yes.cost_breakdown.spread_half_cost == D('.01')
    assert result.yes.cost_breakdown.total_cost_basis == D('.61')
    assert result.candidate_action == 'BUY_YES'


def test_source_and_receipt_age_regression():
    result = edge()
    assert result.source_age_ms == 4000 and result.receipt_age_ms == 1000


@pytest.mark.parametrize('quantity,vwap,executed,unfilled', [
    ('1', '.61', '1', '0'), ('4', '.63', '4', '0'), ('10', '.634', '5', '5')])
def test_depth(quantity, vwap, executed, unfilled):
    result = edge(cfg=EdgeConfig(target_shares=quantity))
    yes = result.yes
    assert yes.depth_vwap == D(vwap)
    assert yes.executable_shares == D(executed) and yes.unfilled_shares == D(unfilled)
    assert yes.insufficient_depth == (D(unfilled) > 0)
    assert sum(l.shares for l in yes.liquidity_used) == D(executed)
    assert yes.net_ev_total == D(executed) * (D('.7') - D(vwap))
    if D(unfilled):
        assert result.candidate_action == 'NO_TRADE' and 'INSUFFICIENT_DEPTH' in result.reasons


def test_partial_depth_explicit_fraction():
    result = edge(cfg=EdgeConfig(target_shares=10, minimum_executable_fraction='.5'))
    assert result.yes.insufficient_depth and result.eligible_yes
    assert result.candidate_action == 'BUY_YES'
    assert result.yes.net_ev_total == D('.33')  # only five gross shares, not ten


def test_derived_no_and_no_consumption():
    s = snapshot(); before = s.to_json()
    result = edge(cfg=EdgeConfig(target_shares=4), s=s)
    assert result.no.depth_vwap == D('.42')
    assert all(l.derived and l.liquidity_origin == 'YES_BID' for l in result.no.liquidity_used)
    assert {l.liquidity_id for l in result.no.liquidity_used} == {l.liquidity_id for l in s.yes_bids}
    assert not any(l.derived for l in result.yes.liquidity_used)
    assert result.scenarios == 'MUTUALLY_EXCLUSIVE_HYPOTHETICAL'
    assert s.to_json() == before and edge(cfg=EdgeConfig(target_shares=4), s=s) == result


def test_collateral_fee():
    result = edge(cfg=EdgeConfig(target_shares=2, fee=FeeModel(rate='.02', collateral_per_share='.01')))
    cost = result.yes.cost_breakdown
    assert cost.fee_collateral_total == D('.0444') and cost.fee_shares_total == 0
    assert cost.net_shares == 2 and cost.collateral_spent == D('1.2644')
    assert result.yes.net_ev_total == D('.1356')
    assert result.yes.net_edge_per_share == D('.0678')


def test_shares_fee_payout_not_cash_subtraction():
    result = edge(cfg=EdgeConfig(target_shares=2, fee=FeeModel(denomination='SHARES', rate='.1')))
    cost = result.yes.cost_breakdown
    assert cost.net_shares == D('1.8') and cost.fee_shares_total == D('.2')
    assert cost.fee_per_share == 0 and cost.collateral_spent == D('1.22')
    assert result.yes.net_ev_total == D('.04')
    assert result.yes.net_edge_per_share == D('.02')  # .9*.7-.61, NOT .7-.61-.1


def test_zero_fee_and_full_share_fee():
    assert edge(cfg=EdgeConfig(fee=FeeModel(denomination='SHARES'))).yes.net_edge_per_share == D('.09')
    result = edge(cfg=EdgeConfig(fee=FeeModel(denomination='SHARES', rate=1)))
    assert result.yes.net_ev_total == D('-.61') and result.candidate_action == 'NO_TRADE'


def test_costs_not_double_counted():
    r = edge(cfg=EdgeConfig(target_shares=4, latency_cost_assumption='.01', extra_cost_assumption='.02'))
    c = r.yes.cost_breakdown
    assert c.depth_cost_per_share == D('.02') and c.spread_half_cost == D('.01')
    assert c.total_cost_basis == D('.66')  # .63 + .01 + .02; no extra spread or impact
    assert r.yes.net_edge_per_share == D('.04') and r.yes.net_ev_total == D('.16')


@pytest.mark.parametrize('probability,action', [('.62','NO_TRADE'), ('.620000000000000001','BUY_YES'), ('.61','NO_TRADE')])
def test_strict_threshold(probability, action):
    assert edge(prediction(p_yes=probability)).candidate_action == action


def test_exact_tie_and_both_eligible():
    # Negative research threshold deliberately makes both scenarios eligible;
    # under ordinary nonnegative costs/threshold this is impossible for complementary books.
    cfg = EdgeConfig(minimum_net_edge_per_share='-.2')
    tied = edge(prediction(p_yes='.6'), cfg)
    assert tied.eligible_yes and tied.eligible_no
    assert tied.candidate_action == 'NO_TRADE' and tied.reasons == ('EXACT_EDGE_TIE',)
    assert edge(prediction(p_yes='.7'), cfg).candidate_action == 'BUY_YES'
    assert edge(prediction(p_yes='.5'), cfg).candidate_action == 'BUY_NO'


@pytest.mark.parametrize('kind,reason', [
    ('prediction','PREDICTION_NOT_AVAILABLE'), ('snapshot','SNAPSHOT_NOT_AVAILABLE'),
    ('receipt','NEGATIVE_RECEIPT_AGE'), ('source','NEGATIVE_SOURCE_AGE'), ('expiry','MARKET_EXPIRED')])
def test_time_fails_closed(kind, reason):
    p=prediction();s=snapshot();at=5000
    if kind=='prediction': p=prediction(available_at=5001)
    if kind=='snapshot': s=snapshot(available_at=5001)
    if kind=='receipt': at=3999
    if kind=='source': s=snapshot(source_at=5001)
    if kind=='expiry': at=301000
    result=edge(p,s=s,at=at)
    assert result.candidate_action=='NO_TRADE' and reason in result.reasons
    assert result.yes is None and result.no is None and not result.eligible_yes


def test_later_time_reports_age_without_implicit_stale_gate():
    result=edge(at=300000)
    assert result.source_age_ms==299000 and result.receipt_age_ms==296000
    assert result.candidate_action=='BUY_YES'


@pytest.mark.parametrize('changes,reason', [
    ({'market_id':'different'}, 'MARKET_MISMATCH'),
    ({'experiment_id':'different'}, 'EXPERIMENT_MISMATCH'),
    ({'support_status':'UNSUPPORTED'}, 'UNSUPPORTED_PREDICTION'),
    ({'target_definition':TargetDefinition('YES_DOWN','rule-v1',301000)}, 'TARGET_MISMATCH'),
    ({'target_definition':TargetDefinition('YES_UP','other-rule',301000)}, 'TARGET_MISMATCH'),
    ({'target_definition':TargetDefinition('YES_UP','rule-v1',301001)}, 'TARGET_MISMATCH'),
    ({'target_definition':TargetDefinition('YES_UP','rule-v1',301000,'BTC_UP')}, 'TARGET_MISMATCH')])
def test_compatibility(changes,reason):
    result=edge(prediction(**changes))
    assert result.candidate_action=='NO_TRADE' and reason in result.reasons and result.yes is None


def test_yes_is_not_assumed_up():
    cfg=validator(outcome_mapping='YES_DOWN')
    event=raw_event(payload(outcome_mapping='YES_DOWN'),experiment_id='exp-edge',source='synthetic',received_at=4000,sequence=1)
    s=validate_market(event,cfg,evaluation_at=4000).snapshot
    p=prediction(target_definition=TargetDefinition('YES_DOWN','rule-v1',301000))
    assert edge(p,s=s).yes.probability==D('.7')  # adapter has already mapped to YES


def test_deterministic_rounding_and_replay():
    s=snapshot(yes_asks=[['.61','1'],['.62','2']]);cfg=EdgeConfig(target_shares=3)
    first=edge(s=s,cfg=cfg)
    with localcontext() as ctx:
        ctx.prec=6;ctx.rounding=ROUND_DOWN
        second=edge(s=s,cfg=cfg)
    assert first.to_json()==second.to_json()
    assert first.yes.depth_vwap==D('.616666666666666667')
    assert first.yes.net_ev_total==D('.25')


def test_immutable_and_config_hash():
    p=prediction();r=edge(p);cfg=EdgeConfig()
    with pytest.raises(FrozenInstanceError): p.p_yes=D('.5')
    with pytest.raises(FrozenInstanceError): r.candidate_action='BUY_NO'
    assert cfg.hash==EdgeConfig.from_dict(json.loads(canonical(asdict(cfg)))).hash
    assert cfg.hash!=replace(cfg,latency_cost_assumption='.01').hash
    assert r.split_model=='unavailable' and r.split_treatment=='IGNORE_SPLIT_EXPLICIT_PROXY'
    with pytest.raises(ValueError): EdgeConfig(split_treatment='COMPLETE_REAL_EV')


@pytest.mark.parametrize('changes', [{'target_shares':0},{'target_shares':-1},{'latency_cost_assumption':-.1},
                                     {'minimum_executable_fraction':0},{'minimum_executable_fraction':1.1}])
def test_config_rejects_invalid(changes):
    with pytest.raises(ValueError): EdgeConfig(**changes)


def test_prediction_cutoff_cannot_follow_availability():
    with pytest.raises(ValueError): prediction(input_cutoff=4501)


@pytest.fixture
def stored(tmp_path):
    cfg=validator()
    with Database(StorageConfig(project_root=tmp_path)) as db:
        repo=Repository(db,cfg)
        repo.register(Experiment('exp-edge','a'*40,'synthetic-v1',42,900,cfg.hash))
        result=repo.ingest(payload(),experiment_id='exp-edge',source='synthetic',received_at=4000,sequence=1,evaluation_at=4000)
        yield EdgeRepository(repo),result.snapshot


def test_persistence_idempotency_integrity(stored):
    repo,s=stored;p=prediction();cfg=EdgeConfig()
    assert repo.put_prediction(p)==repo.put_prediction(p)==repo.get_prediction(p.prediction_id)
    r=repo.evaluate_and_store(s.snapshot_id,p,cfg,evaluation_at=5000)
    assert r==repo.evaluate_and_store(s.snapshot_id,p,cfg,evaluation_at=5000)==repo.get_edge(r.edge_id)
    for table in ('predictions','edge_evaluations'):
        assert repo.db.connection.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==1
    assert repo.db.connection.execute('PRAGMA foreign_key_check').fetchall()==[]


def test_conflicting_prediction_retry(stored):
    repo,s=stored;p=prediction();repo.put_prediction(p)
    with pytest.raises(ValueError,match='conflicting'):
        repo.put_prediction(replace(p,p_yes='.8'))
    with pytest.raises(ValueError,match='conflicting'):
        repo.evaluate_and_store(s.snapshot_id,replace(p,p_yes='.8'),EdgeConfig(),evaluation_at=5000)
    assert repo.get_prediction(p.prediction_id)==p


def test_atomic_write_failure(stored):
    repo,s=stored;conn=repo.db.connection
    conn.execute("CREATE TRIGGER fail_edge BEFORE INSERT ON edge_evaluations BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError): repo.evaluate_and_store(s.snapshot_id,prediction(),EdgeConfig(),evaluation_at=5000)
    assert conn.execute('SELECT COUNT(*) FROM predictions').fetchone()[0]==0
    assert conn.execute('SELECT COUNT(*) FROM edge_evaluations').fetchone()[0]==0
    assert repo.market.get_snapshot(s.snapshot_id)==s


@pytest.mark.parametrize('table', ['predictions','edge_evaluations'])
def test_corrupted_read_rejected(stored,table):
    repo,s=stored;p=prediction();r=repo.evaluate_and_store(s.snapshot_id,p,EdgeConfig(),evaluation_at=5000)
    conn=repo.db.connection
    with pytest.raises(sqlite3.IntegrityError): conn.execute(f"UPDATE {table} SET payload_hash='broken'")
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError): conn.execute(f'DELETE FROM {table}')
    conn.rollback()
    conn.execute(f'DROP TRIGGER {table}_immutable_update')
    conn.execute(f"UPDATE {table} SET payload_hash='broken'");conn.commit()
    with pytest.raises(ValueError,match='integrity'): repo.get_edge(r.edge_id)


def test_cross_experiment_link_and_fk(stored):
    repo,s=stored;p=prediction(experiment_id='other')
    repo.market.register(Experiment('other','b'*40,'synthetic-v1',43,900,repo.market.config.hash))
    repo.put_prediction(p)
    with pytest.raises(ValueError,match='cross-experiment'):
        repo.evaluate_and_store(s.snapshot_id,p,EdgeConfig(),evaluation_at=5000)
    with pytest.raises(sqlite3.IntegrityError):
        repo.db.connection.execute('INSERT INTO edge_evaluations VALUES (?,?,?,?,?,?,?,?,?)',
            ('bad','exp-edge',p.prediction_id,s.snapshot_id,5000,'hash','{}','{}','hash'))
    repo.db.connection.rollback()


def test_wrong_market_no_trade_is_persisted(stored):
    repo,s=stored;r=repo.evaluate_and_store(s.snapshot_id,prediction(market_id='different'),EdgeConfig(),evaluation_at=5000)
    assert repo.get_edge(r.edge_id).reasons==('MARKET_MISMATCH',)


def test_migration_keeps_m1_and_reopens(stored):
    repo,s=stored;conn=repo.db.connection
    before=repo.market.counts();migrate_m2(repo.db)
    assert repo.market.counts()==before
    assert conn.execute('PRAGMA user_version').fetchone()[0]==2
    with Database(StorageConfig(project_root=repo.db.path.parents[2])) as reopened:
        assert reopened.connection.execute('PRAGMA user_version').fetchone()[0]==2
        assert {x[0] for x in reopened.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}=={
            'experiments','raw_market_events','market_validation_events','market_snapshots','predictions','edge_evaluations'}


def test_float_noise_does_not_move_threshold():
    p=prediction(p_yes=0.1+0.2)
    assert p.p_yes==D('.3')
    assert edge(prediction(p_yes=.6+.02)).candidate_action=='NO_TRADE'


@pytest.mark.parametrize('table', ['predictions','edge_evaluations'])
def test_sql_replace_cannot_overwrite(stored,table):
    repo,s=stored;repo.evaluate_and_store(s.snapshot_id,prediction(),EdgeConfig(),evaluation_at=5000)
    conn=repo.db.connection
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}')
    conn.rollback()


def test_tampered_config_and_conflicting_edge_retry(stored):
    repo,s=stored;p=prediction();cfg=EdgeConfig()
    r=repo.evaluate_and_store(s.snapshot_id,p,cfg,evaluation_at=5000)
    conn=repo.db.connection
    conn.execute('DROP TRIGGER edge_evaluations_immutable_update')
    conn.execute("UPDATE edge_evaluations SET config_hash='changed'");conn.commit()
    with pytest.raises(ValueError,match='integrity'): repo.get_edge(r.edge_id)
    with pytest.raises(ValueError,match='integrity'):
        repo.evaluate_and_store(s.snapshot_id,p,cfg,evaluation_at=5000)


def test_migration_failure_is_atomic(tmp_path,monkeypatch):
    import btc5_v3.storage.edge_repository as module
    with Database(StorageConfig(project_root=tmp_path)) as db:
        monkeypatch.setattr(module,'DDL',module.DDL+('INVALID SQL',))
        with pytest.raises(sqlite3.OperationalError): migrate_m2(db)
        assert db.connection.execute('PRAGMA user_version').fetchone()[0]==1
        assert db.connection.execute("SELECT name FROM sqlite_master WHERE name='predictions'").fetchall()==[]


def test_edge_demo_idempotent(tmp_path):
    from btc5_v3.edge.demo import run_demo
    first=run_demo(tmp_path,'a'*40)
    assert first==run_demo(tmp_path,'a'*40)
    a,b=first['evaluations']
    assert a['candidate_action']=='BUY_YES' and b['candidate_action']=='NO_TRADE'
    assert a['yes']['raw_edge']==D('.10') and a['yes']['net_edge_per_share']==D('.09')


def test_concurrent_edge_idempotency(stored):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    repo,s=stored;root=repo.db.path.parents[2];barrier=threading.Barrier(2)
    def worker():
        barrier.wait(timeout=10)
        with Database(StorageConfig(project_root=root)) as db:
            other=EdgeRepository(Repository(db,validator()))
            return other.evaluate_and_store(s.snapshot_id,prediction(),EdgeConfig(),evaluation_at=5000)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first,second=list(pool.map(lambda _:worker(),range(2)))
    assert first==second and repo.get_edge(first.edge_id)==first
    assert repo.db.connection.execute('SELECT COUNT(*) FROM edge_evaluations').fetchone()[0]==1


def test_half_even_rounding_boundary():
    s=snapshot(yes_asks=[['.600000000000000001','1'],['.600000000000000002','1']])
    r=edge(s=s,cfg=EdgeConfig(target_shares=2))
    assert r.yes.depth_vwap==D('.600000000000000002')
    assert r.yes.net_edge_per_share==D('.099999999999999998')
    assert r.yes.net_ev_total==D('.199999999999999997')


def test_available_at_equality_is_usable():
    r=edge(prediction(available_at=5000),s=snapshot(available_at=5000))
    assert r.candidate_action=='BUY_YES'


@pytest.mark.parametrize('kwargs',[{'denomination':'UNKNOWN'},{'rate':-1},{'rate':1.1},
                                  {'denomination':'SHARES','collateral_per_share':'.01'}])
def test_fee_contract_rejects_ambiguous_units(kwargs):
    with pytest.raises(ValueError): FeeModel(**kwargs)


def test_future_reference_price_not_used():
    cfg=validator(clock_skew_tolerance_ms=2000)
    event=raw_event(payload(reference_underlying_price='100000',reference_price_at=5001),
                    experiment_id='exp-edge',source='synthetic',received_at=4000,sequence=1)
    result=validate_market(event,cfg,evaluation_at=4000)
    assert result.snapshot is not None
    r=edge(s=result.snapshot)
    assert r.candidate_action=='NO_TRADE' and 'REFERENCE_PRICE_NOT_AVAILABLE' in r.reasons
