"""M6 synthetic-only invariants, permission races and replay corruption checks."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace, FrozenInstanceError
from decimal import Decimal, localcontext
import json
import sqlite3
import threading

import pytest

from btc5_v3.encoding import canonical, digest
from btc5_v3.config.models import StorageConfig
from btc5_v3.experiments.models import Experiment
from btc5_v3.edge.costs import FeeModel
from btc5_v3.analytics.models import ResearchObservation
from btc5_v3.execution.models import ExecutionConfig, ExitPolicy
from btc5_v3.execution.engine import simulate
from btc5_v3.risk.models import RiskConfig, HealthEvidence
from btc5_v3.risk.engine import PRECEDENCE, collateral_bound
from btc5_v3.risk.demo import candidate, book, outcome, healthy, approve, run_demo, TD, START
from btc5_v3.storage.database import Database
from btc5_v3.storage.risk_repository import RiskRepository, RISK_TABLES
from btc5_v3.storage.analytics_repository import RESEARCH_CONTRACT

D = Decimal
CODE = 'b'*40
EXP = 'risk-test'


def liberal(**kwargs):
    values = dict(max_position_notional=D(1000), max_position_fraction=D(1), max_total_open_exposure=D(1000),
                  max_total_open_exposure_fraction=D(1), max_pending_exposure=D(1000), max_market_exposure=D(1000),
                  max_daily_simulated_loss=D(1000), max_drawdown=D(1), max_consecutive_losses=100)
    values.update(kwargs)
    return RiskConfig(**values)


def setup(root, config=None):
    db = Database(StorageConfig(root, 'runtime/v3/risk.sqlite'))
    repo = RiskRepository(db)
    repo.register(Experiment(EXP, CODE, 'synthetic-risk-v1', 42, START, digest(RESEARCH_CONTRACT)))
    run = repo.create_run(EXP, CODE, config or liberal(), TD)
    return db, repo, run


@pytest.fixture
def env(tmp_path):
    db, repo, run = setup(tmp_path)
    yield db, repo, run
    db.connection.close()


def decision(result): return result['risk_decision']
def rid(result): return decision(result)['risk_decision_id']


def loss(repo, run, *, market='loss', at=TD, shares='100', ask='.50', payout=0):
    o = candidate(market=market, at=at, shares=shares, ask=ask)
    a = approve(repo, run, o)
    books = [book(o, at+250, bid=str(D(ask)-D('.02')), ask=ask)]
    t = o.data()['snapshot']['expiry']+1000
    r = repo.execute(run, rid(a), books, outcome(o, payout), cutoff=t)
    return o, a, books, t, r


def test_config_immutable_deterministic_hash():
    c = RiskConfig()
    assert RiskConfig(**json.loads(canonical(asdict(c)))).hash == c.hash
    assert replace(c, max_position_notional=D(101)).hash != c.hash
    with pytest.raises(FrozenInstanceError): c.starting_capital = D(9)


@pytest.mark.parametrize('field,value', [('starting_capital','NaN'), ('starting_capital',-1),
    ('max_drawdown',2), ('max_position_fraction',0), ('minimum_share_unit',0),
    ('loss_day_timezone','Asia/Shanghai'), ('reservation_timeout',True), ('require_data_health',1),
    ('pause_behavior','ALL_ORDERS'), ('equity_basis','MID'), ('version','unknown')])
def test_invalid_config(field, value):
    with pytest.raises(ValueError): RiskConfig(**{field:value})


def test_scenario_a_reduce_180_to_100(tmp_path):
    db, repo, run = setup(tmp_path, RiskConfig())
    a = approve(repo, run, candidate(shares='180'))
    assert decision(a)['action'] == 'REDUCE'
    assert decision(a)['approved_notional'] == '100'
    assert decision(a)['primary_reason'] == 'POSITION_LIMIT'
    assert a['state_after']['reserved_cash'] == '100'
    assert a['state_after']['equity'] == '1000'
    db.connection.close()


@pytest.mark.parametrize('limit,reason', [('max_position_notional','POSITION_LIMIT'),
    ('max_market_exposure','MARKET_EXPOSURE_LIMIT'), ('max_total_open_exposure','TOTAL_EXPOSURE_LIMIT'),
    ('max_pending_exposure','PENDING_EXPOSURE_LIMIT')])
def test_each_absolute_limit(tmp_path, limit, reason):
    db, repo, run = setup(tmp_path, liberal(**{limit:D(40)}))
    a = decision(approve(repo, run, candidate(shares='100')))
    assert a['approved_shares'] == '40' and a['primary_reason'] == reason
    db.connection.close()


@pytest.mark.parametrize('limit,reason', [('max_position_fraction','POSITION_LIMIT'),
    ('max_total_open_exposure_fraction','TOTAL_EXPOSURE_LIMIT')])
def test_each_fraction_limit(tmp_path, limit, reason):
    db, repo, run = setup(tmp_path, liberal(**{limit:D('.05')}))
    a = decision(approve(repo, run, candidate()))
    assert a['approved_shares'] == '50' and a['primary_reason'] == reason
    db.connection.close()


def test_scenario_b_cash_reservation_and_duplicate(env):
    db, repo, _ = env
    run = repo.create_run(EXP, CODE, liberal(starting_capital=D(100)), TD)
    original = candidate(shares='80'); a = approve(repo, run, original)
    assert approve(repo, run, original) == a
    b = approve(repo, run, candidate(market='second', shares='50'))
    assert decision(b)['approved_shares'] == '20'
    assert decision(b)['primary_reason'] == 'INSUFFICIENT_CAPITAL'
    assert b['state_after']['available_cash'] == '0'
    assert db.connection.execute('SELECT count(*) FROM risk_decisions').fetchone()[0] == 2


def test_competing_writers_atomic(tmp_path):
    db, repo, run = setup(tmp_path, liberal(starting_capital=D(100)))
    db.connection.close(); barrier = threading.Barrier(2)
    def worker(market):
        with Database(StorageConfig(tmp_path, 'runtime/v3/risk.sqlite')) as connection:
            r = RiskRepository(connection); barrier.wait()
            return decision(approve(r, run, candidate(market=market, shares='80')))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, ['a','b']))
    assert sorted(D(x['approved_shares']) for x in results) == [20,80]
    with Database(StorageConfig(tmp_path, 'runtime/v3/risk.sqlite')) as connection:
        assert RiskRepository(connection).state(run, at=TD).data()['available_cash'] == '0'


def test_concurrent_duplicate_no_double_reserve(tmp_path):
    db, repo, run = setup(tmp_path); db.connection.close(); barrier = threading.Barrier(2)
    def worker(_):
        with Database(StorageConfig(tmp_path, 'runtime/v3/risk.sqlite')) as conn:
            r=RiskRepository(conn); barrier.wait(); return approve(r, run, candidate())
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(worker, range(2)))
    assert results[0] == results[1]


def test_fixed_reason_precedence(env):
    _, repo, run = env
    repo.control(run, 'pause', 'PAUSE', at=TD)
    a = repo.evaluate(run, candidate(), at=TD, health=replace(healthy(TD),provider_healthy=False,source_matches=False))
    assert decision(a)['primary_reason'] == 'MANUALLY_PAUSED'
    assert decision(a)['all_reasons'] == [x for x in PRECEDENCE if x in decision(a)['all_reasons']]
    assert decision(a)['approved_shares'] == '0' and a['reservation'] is None


def test_scenario_j_no_trade_has_no_reservation(env):
    db, repo, run=env
    a=approve(repo, run, candidate(ask='.96'))
    assert decision(a)['primary_reason']=='UPSTREAM_NO_TRADE' and a['reservation'] is None
    with pytest.raises(ValueError,match='requires approved'): repo.execute(run,rid(a),[],cutoff=TD+500)
    assert db.connection.execute('SELECT count(*) FROM capital_reservations').fetchone()[0]==0


def test_floor_and_minimum_cash(tmp_path):
    db,repo,run=setup(tmp_path,liberal(starting_capital=D(100),minimum_available_cash=D(21),minimum_share_unit=D(10)))
    a=approve(repo,run,candidate(shares='100'))
    assert decision(a)['approved_shares']=='70'
    b=approve(repo,run,candidate(market='b',shares='10'))
    assert decision(b)['action']=='REJECT'
    assert b['state_after']['available_cash']=='30'
    db.connection.close()


def test_both_sides_same_market_gross_limit(tmp_path):
    db,repo,run=setup(tmp_path,liberal(max_market_exposure=D(100)))
    approve(repo,run,candidate(shares='80',attempt='yes'))
    b=approve(repo,run,candidate(shares='50',side='NO',attempt='no'))
    assert decision(b)['approved_shares']=='20'
    assert b['state_after']['pending_by_side']=={'YES':'80','NO':'20'}
    db.connection.close()


def test_existing_inventory_plus_pending_market_limit(tmp_path):
    db,repo,run=setup(tmp_path,liberal(max_market_exposure=D(100)))
    o=candidate();a=approve(repo,run,o)
    repo.execute(run,rid(a),[book(o,TD+250)],cutoff=TD+250)
    b=approve(repo,run,candidate(at=TD+250,attempt='second',shares='100'))
    assert decision(b)['approved_shares']=='50'
    assert b['state_after']['open_exposure']=='50' and b['state_after']['pending_exposure']=='50'
    db.connection.close()


def test_scenario_c_consumption_and_unused_release(env):
    _,repo,run=env;o=candidate();a=approve(repo,run,o)
    r=repo.execute(run,rid(a),[book(o,TD+250,ask='.75',bid='.73',quantity='80')],cutoff=TD+250)
    assert r['reservation']['consumed_collateral']=='60'
    assert r['reservation']['released_collateral']=='40'
    assert [x['status'] for x in r['reservation_changes']]==['PARTIALLY_CONSUMED','CONSUMED']
    assert r['state_after']['cash']=='940' and r['state_after']['open_exposure']=='60'
    assert r['state_after']['equity']=='1000' and r['state_after']['reserved_cash']=='0'


def test_no_fill_releases_and_pending_keeps(env):
    _,repo,run=env;o=candidate();a=approve(repo,run,o)
    p=repo.execute(run,rid(a),[],cutoff=TD+100)
    assert p['reservation']['status']=='ACTIVE' and p['state_after']['reserved_cash']=='100'
    r=repo.execute(run,rid(a),[],cutoff=TD+5250)
    assert r['reservation']['status']=='RELEASED' and r['state_after']['reserved_cash']=='0'


def test_timeout_expire_and_cannot_execute_after(env):
    _,repo,run=env;o=candidate();a=approve(repo,run,o)
    with pytest.raises(ValueError): repo.expire(run,rid(a),at=TD+9999)
    r=repo.expire(run,rid(a),at=TD+10000)
    assert r['reservation']['status']=='EXPIRED' and r['state_after']['available_cash']=='1000'
    with pytest.raises(ValueError): repo.execute(run,rid(a),[book(o,TD+250)],cutoff=TD+10001)


@pytest.mark.parametrize('fee', [FeeModel(rate=D('.02'),collateral_per_share=D('.01')), FeeModel(denomination='SHARES',rate=D('.10'))])
def test_m5_fee_ledger_is_sole_cash_source(env,fee):
    _,repo,run=env;o=candidate(shares='90');ec=ExecutionConfig(entry_fee=fee,exit_fee=FeeModel(rate=D('.01')),settlement_fee=FeeModel(rate=D('.02')))
    a=approve(repo,run,o,execution_config=ec)
    books=[book(o,TD+250,ask='.99',bid='.97')];out=outcome(o,1);t=out.available_at
    r=repo.execute(run,rid(a),books,out,cutoff=t)
    standalone=simulate(o,books,out,replace(ec,requested_shares=D(decision(a)['approved_shares'])),ExitPolicy(),
                        experiment_id=EXP,code_git=CODE,cutoff=t,created_at=t).data()
    assert r['execution']==standalone
    assert D(r['state_after']['cash'])==1000+D(standalone['accounting']['net_simulated_pnl'])
    assert r['state_after']['realized_pnl']==standalone['accounting']['net_simulated_pnl']


@pytest.mark.parametrize('name',['exit_fee','settlement_fee'])
def test_negative_proceeds_fee_contract_rejected_before_reserve(env,name):
    db,repo,run=env
    with pytest.raises(ValueError,match='negative'):
        approve(repo,run,candidate(),execution_config=ExecutionConfig(**{name:FeeModel(collateral_per_share=D('.01'))}))
    assert db.connection.execute('SELECT count(*) FROM risk_events').fetchone()[0]==0


def test_scenario_d_daily_loss_rejects_new_but_settles_existing(tmp_path):
    db,repo,run=setup(tmp_path,liberal(max_daily_simulated_loss=D(50)))
    first=candidate(market='first');second=candidate(market='second')
    a=approve(repo,run,first);b=approve(repo,run,second)
    ab=[book(first,TD+250)];bb=[book(second,TD+250)]
    repo.execute(run,rid(a),ab,cutoff=TD+250);repo.execute(run,rid(b),bb,cutoff=TD+250)
    t=outcome(first).available_at
    repo.execute(run,rid(a),ab,outcome(first),cutoff=t)
    blocked=approve(repo,run,candidate(market='blocked',at=t))
    assert 'DAILY_LOSS_LIMIT' in decision(blocked)['all_reasons']
    done=repo.execute(run,rid(b),bb,outcome(second,1,available_at=t+1),cutoff=t+1)
    assert done['execution']['accounting']['completed']
    db.connection.close()


def test_scenario_e_drawdown_from_1000_to_850(tmp_path):
    db,repo,run=setup(tmp_path,liberal(max_drawdown=D('.1')))
    _,_,_,t,r=loss(repo,run,shares='300')
    assert r['state_after']['equity']=='850' and r['state_after']['drawdown']=='0.15'
    a=approve(repo,run,candidate(market='next',at=t))
    assert decision(a)['primary_reason']=='MAX_DRAWDOWN_REACHED'
    db.connection.close()


def test_scenario_f_only_completed_negative_positions_count(tmp_path):
    db,repo,run=setup(tmp_path,liberal(max_consecutive_losses=3))
    for i in range(3):
        at=TD+i*300000
        if i: repo.control(run,'refresh'+str(i),'RECONCILE',at=at)
        _,_,_,t,r=loss(repo,run,market='m'+str(i),at=at)
        assert r['state_after']['consecutive_losses']==i+1
    a=approve(repo,run,candidate(market='blocked',at=t))
    assert 'CONSECUTIVE_LOSS_LIMIT' in decision(a)['all_reasons']
    db.connection.close()


def test_unresolved_not_loss(env):
    _,repo,run=env;o=candidate();a=approve(repo,run,o)
    r=repo.execute(run,rid(a),[book(o,TD+250)],cutoff=TD+250)
    assert r['state_after']['consecutive_losses']==0 and r['state_after']['daily_pnl']=='0'


def test_zero_completed_result_resets_streak(env):
    _,repo,run=env
    loss(repo,run,market='loss')
    at=TD+300000;repo.control(run,'refresh','RECONCILE',at=at)
    _,_,_,_,r=loss(repo,run,market='flat',at=at,payout='.5')
    assert r['state_after']['consecutive_losses']==0


@pytest.mark.parametrize('change', [dict(source_at=None), dict(heartbeat_at=None), dict(source_at=TD-4000),
    dict(heartbeat_at=TD-6000), dict(validation_failures=3), dict(source_matches=False),
    dict(source_at=TD+1), dict(available_at=TD+1)])
def test_data_kill_reasons(env,change):
    _,repo,run=env
    a=repo.evaluate(run,candidate(),at=TD,health=replace(healthy(TD),**change))
    assert 'DATA_KILL_SWITCH' in decision(a)['all_reasons']
    assert a['reservation'] is None


def test_missing_health_fails_closed(env):
    _,repo,run=env
    a=repo.evaluate(run,candidate(),at=TD)
    assert decision(a)['primary_reason']=='DATA_KILL_SWITCH'


def test_provider_pause_clear_and_manual_resume_separate(env):
    _,repo,run=env
    repo.control(run,'manual','PAUSE',at=TD)
    repo.control(run,'bad-provider','HEALTH',at=TD,health=replace(healthy(TD),provider_healthy=False))
    r=repo.control(run,'resume','RESUME',at=TD)
    assert r['state_after']['control_states']==['PAUSED_PROVIDER']
    r=repo.control(run,'healthy','HEALTH',at=TD+1,health=healthy(TD+1))
    assert r['state_after']['control_states']==['ACTIVE']
    assert any(e['action']=='CLEAR' and e['reason']=='PROVIDER_KILL_SWITCH' for e in r['control_events'])


def test_scenario_g_kill_allows_existing_exit(env):
    _,repo,run=env;o=candidate();a=approve(repo,run,o,policy=ExitPolicy('BID_REBOUND',D('.20')))
    books=[book(o,TD+250)]
    repo.execute(run,rid(a),books,cutoff=TD+250)
    repo.control(run,'bad-feed','HEALTH',at=TD+500,health=replace(healthy(TD+500),source_matches=False))
    books += [book(o,TD+1000,seq=3,bid='.80',ask='.82'),book(o,TD+1250,seq=4,bid='.75',ask='.77')]
    r=repo.execute(run,rid(a),books,cutoff=TD+1250)
    assert r['execution']['accounting']['completed'] and r['state_after']['control_states']==['PAUSED_DATA']


def test_scenario_h_utc_reset_not_drawdown(tmp_path):
    db,repo,run=setup(tmp_path,liberal(max_daily_simulated_loss=D(50),max_drawdown=D('.1')))
    loss(repo,run,shares='300')
    nextday=START+86400000
    r=repo.control(run,'utc-rollover','HEALTH',at=nextday,health=healthy(nextday))
    assert r['state_after']['daily_pnl']=='0'
    assert r['state_after']['control_states']==['PAUSED_DRAWDOWN']
    a=approve(repo,run,candidate(market='nextday',at=nextday))
    assert 'MAX_DRAWDOWN_REACHED' in decision(a)['all_reasons']
    db.connection.close()


def test_scenario_i_future_loss_does_not_change_past(env):
    _,repo,run=env;o=candidate();a=approve(repo,run,o)
    before=repo.state(run,at=TD)
    future=outcome(o,available_at=TD+3600000)
    repo.execute(run,rid(a),[book(o,TD+250)],future,cutoff=future.available_at)
    assert repo.state(run,at=TD)==before
    assert approve(repo,run,o)==a


def test_future_outcome_not_in_current_cash(env):
    _,repo,run=env;o=candidate();a=approve(repo,run,o)
    r=repo.execute(run,rid(a),[book(o,TD+250)],outcome(o),cutoff=TD+250)
    assert r['state_after']['realized_pnl']=='0' and r['state_after']['equity']=='1000'


def test_stale_portfolio_blocks_until_explicit_reconcile(env):
    _,repo,run=env
    repo.control(run,'tick','RECONCILE',at=TD)
    a=approve(repo,run,candidate(at=TD+40000))
    assert decision(a)['primary_reason']=='STALE_PORTFOLIO_STATE'
    repo.control(run,'refresh','RECONCILE',at=TD+80000)
    b=approve(repo,run,candidate(market='new',at=TD+80000))
    assert decision(b)['action']=='APPROVE'


def test_cross_experiment_and_lineage_failure(env):
    db,repo,run=env
    with pytest.raises(ValueError): approve(repo,run,candidate(exp='foreign'))
    x=candidate().data();x['decision']['edge_id']='c'*64
    with pytest.raises(ValueError): approve(repo,run,ResearchObservation(canonical(x)))
    x=candidate().data();x['decision']['executable_shares']='200'
    with pytest.raises(ValueError): approve(repo,run,ResearchObservation(canonical(x)))
    assert db.connection.execute('SELECT count(*) FROM risk_events').fetchone()[0]==0


def test_cannot_supply_quantity_or_shift_latency(env):
    _,repo,run=env;o=candidate()
    with pytest.raises(ValueError): approve(repo,run,o,execution_config=ExecutionConfig(requested_shares=D(1)))
    with pytest.raises(ValueError): repo.evaluate(run,o,at=TD+1,health=healthy(TD+1))
    with pytest.raises(ValueError): approve(repo,run,o,execution_config=ExecutionConfig(maximum_wait_for_next_book_ms=20000))


def test_retry_conflict_does_not_change_cash(env):
    _,repo,run=env;o=candidate();a=approve(repo,run,o)
    with pytest.raises(ValueError,match='conflicting'):
        approve(repo,run,o,execution_config=ExecutionConfig(decision_to_order_latency_ms=500))
    assert repo.state(run,at=TD).data()['reserved_cash']=='100'


def test_m5_prefix_rewrite_rejected_and_rolls_back(env):
    _,repo,run=env;o=candidate();a=approve(repo,run,o)
    repo.execute(run,rid(a),[book(o,TD+250)],cutoff=TD+250)
    before=repo.state(run,at=TD+250)
    with pytest.raises(ValueError,match='prefix rewrite'):
        repo.execute(run,rid(a),[book(o,TD+250,ask='.55')],cutoff=TD+500)
    assert repo.state(run,at=TD+250)==before


def test_late_money_cannot_rewrite_prior_permissions(env):
    _,repo,run=env;o=candidate();a=approve(repo,run,o)
    repo.control(run,'advance','RECONCILE',at=TD+500)
    with pytest.raises(ValueError,match='backdated'):
        repo.execute(run,rid(a),[book(o,TD+250)],cutoff=TD+1000)


def test_atomic_insert_failure_rolls_back_all(env):
    db,repo,run=env
    db.connection.execute("CREATE TRIGGER fail_reservation BEFORE INSERT ON capital_reservations BEGIN SELECT RAISE(ABORT,'test failure'); END")
    with pytest.raises(sqlite3.IntegrityError): approve(repo,run,candidate())
    for t in RISK_TABLES[1:]: assert db.connection.execute('SELECT count(*) FROM '+t).fetchone()[0]==0


@pytest.mark.parametrize('table',RISK_TABLES)
def test_immutable_rows_and_replace(env,table):
    db,repo,run=env;approve(repo,run,candidate())
    with pytest.raises(sqlite3.IntegrityError): db.connection.execute('DELETE FROM '+table)
    db.connection.rollback()
    with pytest.raises(sqlite3.IntegrityError): db.connection.execute('INSERT OR REPLACE INTO '+table+' SELECT * FROM '+table)
    db.connection.rollback()


@pytest.mark.parametrize('table',RISK_TABLES)
def test_corruption_readback_failure(env,table):
    db,repo,run=env;approve(repo,run,candidate())
    db.connection.execute('DROP TRIGGER '+table+'_immutable_update')
    field='output_json' if table=='risk_events' else 'payload_json'
    db.connection.execute('UPDATE '+table+' SET '+field+"='{}'")
    db.connection.commit()
    with pytest.raises((ValueError,KeyError)): repo.state(run,at=TD)


def test_missing_projection_fails(env):
    db,repo,run=env;approve(repo,run,candidate())
    db.connection.execute('DROP TRIGGER capital_reservations_immutable_delete')
    db.connection.execute('DELETE FROM capital_reservations');db.connection.commit()
    with pytest.raises(ValueError,match='projection'): repo.state(run,at=TD)


def test_restart_replays_exactly(tmp_path):
    db,repo,run=setup(tmp_path);o=candidate();a=approve(repo,run,o)
    repo.execute(run,rid(a),[book(o,TD+250)],cutoff=TD+250)
    expected=repo.state(run,at=TD+250);db.connection.close()
    with Database(StorageConfig(tmp_path,'runtime/v3/risk.sqlite')) as db2:
        r=RiskRepository(db2)
        assert r.state(run,at=TD+250)==expected and approve(r,run,o)==a


def test_ambient_decimal_context_does_not_change_results(tmp_path):
    with localcontext() as c:
        c.prec=8
        db,repo,run=setup(tmp_path);a=approve(repo,run,candidate());db.connection.close()
    with Database(StorageConfig(tmp_path,'runtime/v3/risk.sqlite')) as db:
        assert approve(RiskRepository(db),run,candidate())==a


def test_full_synthetic_demo_and_repeat(tmp_path):
    first=run_demo(tmp_path,CODE)
    assert len(first['cases'])==6 and first==run_demo(tmp_path,CODE)
    case={r['case']:r['report'] for r in first['cases']}
    for value in case.values():
        assert len(value['original_candidates'])==value['funnel']['m3_candidates']
        assert all(x['original']['decision']['decision_id'] for x in value['original_candidates'])
    assert case['daily-pause-exit']['funnel']['risk_rejected']==1
    assert case['drawdown']['capital']['equity']==D(850)
    assert 'M3' not in first['mode']


def test_pause_revokes_pending_permission(env):
    _,repo,run=env;o=candidate();a=approve(repo,run,o)
    repo.execute(run,rid(a),[],cutoff=TD+100)
    paused=repo.control(run,'pause','PAUSE',at=TD+200)
    assert paused['state_after']['reserved_cash']=='0'
    assert paused['reservation_changes'][0]['release_reason']=='RISK_PAUSE'
    with pytest.raises(ValueError,match='closed entry'):
        repo.execute(run,rid(a),[book(o,TD+250)],cutoff=TD+250)
    repo.control(run,'resume','RESUME',at=TD+250)
    with pytest.raises(ValueError): repo.execute(run,rid(a),[book(o,TD+500)],cutoff=TD+500)


def test_entry_rechecks_health_without_changing_fill(env):
    _,repo,run=env;o=candidate();a=approve(repo,run,o)
    with pytest.raises(ValueError,match='blocks new entry'):
        repo.execute(run,rid(a),[book(o,TD+4000)],cutoff=TD+4000)
    repo.control(run,'refresh-feed','HEALTH',at=TD+4000,health=healthy(TD+4000))
    r=repo.execute(run,rid(a),[book(o,TD+4000)],cutoff=TD+4000)
    assert r['execution']['fills'][0]['at']==TD+4000


def test_daily_loss_latches_after_recovery(tmp_path):
    db,repo,run=setup(tmp_path,liberal(max_daily_simulated_loss=D(50)))
    a_o=candidate(market='loser');b_o=candidate(market='winner')
    a=approve(repo,run,a_o);b=approve(repo,run,b_o)
    a_b=[book(a_o,TD+250)];b_b=[book(b_o,TD+250)]
    repo.execute(run,rid(a),a_b,cutoff=TD+250);repo.execute(run,rid(b),b_b,cutoff=TD+250)
    t=outcome(a_o).available_at
    repo.execute(run,rid(a),a_b,outcome(a_o),cutoff=t)
    r=repo.execute(run,rid(b),b_b,outcome(b_o,1,available_at=t+1),cutoff=t+1)
    assert r['state_after']['daily_pnl']=='0' and 'PAUSED_DAILY_LOSS' in r['state_after']['control_states']
    db.connection.close()


def test_partial_exit_realized_cost_basis_and_loss_streak(env):
    _,repo,run=env;o=candidate(shares='3');ec=ExecutionConfig(exit_fee=FeeModel(denomination='SHARES',rate=D('.1')))
    a=approve(repo,run,o,execution_config=ec,policy=ExitPolicy('BID_REBOUND',D('.20')))
    books=[book(o,TD+250,ask='.51',bid='.49'),book(o,TD+1000,seq=3,bid='.80',ask='.82'),
           book(o,TD+1250,seq=4,bid='.75',ask='.77',quantity='1')]
    r=repo.execute(run,rid(a),books,cutoff=TD+1250)
    assert r['execution']['accounting']['remaining_shares']=='1.9'
    assert r['state_after']['consecutive_losses']==0
    t=outcome(o).available_at
    end=repo.execute(run,rid(a),books,outcome(o),cutoff=t)
    assert end['state_after']['realized_pnl']==end['execution']['accounting']['net_simulated_pnl']


def test_full_entry_share_fee_is_completed_loss(env):
    _,repo,run=env;o=candidate();a=approve(repo,run,o,execution_config=ExecutionConfig(entry_fee=FeeModel(denomination='SHARES',rate=D(1))))
    r=repo.execute(run,rid(a),[book(o,TD+250)],cutoff=TD+250)
    assert r['state_after']['equity']=='950' and r['state_after']['consecutive_losses']==1


def test_no_input_mutation_and_reconciliation_idempotent(env):
    db,repo,run=env;o=candidate();b=book(o,TD+250);before=(o.payload_json,b.snapshot_json)
    a=approve(repo,run,o);r=repo.execute(run,rid(a),[b],cutoff=TD+250)
    count=db.connection.execute('SELECT count(*) FROM risk_events').fetchone()[0]
    assert repo.execute(run,rid(a),[b],cutoff=TD+250)==r
    assert db.connection.execute('SELECT count(*) FROM risk_events').fetchone()[0]==count
    assert (o.payload_json,b.snapshot_json)==before


def test_cross_run_execution_reference_rejected(env):
    _,repo,run=env;a=approve(repo,run,candidate())
    other=repo.create_run(EXP,CODE,liberal(starting_capital=D(2000)),TD)
    with pytest.raises(ValueError): repo.execute(other,rid(a),[],cutoff=TD+250)


def test_cross_experiment_book_rejected(env):
    _,repo,run=env;a=approve(repo,run,candidate())
    with pytest.raises(ValueError): repo.execute(run,rid(a),[book(candidate(exp='foreign'),TD+250)],cutoff=TD+250)
