"""Offline M5: causal books, explicit inventory, failure-inclusive counterfactuals."""
from dataclasses import asdict,replace,FrozenInstanceError
from decimal import Decimal,localcontext
import json
import sqlite3

import pytest

from btc5_v3.encoding import canonical,digest
from btc5_v3.config.models import StorageConfig
from btc5_v3.edge.costs import FeeModel
from btc5_v3.path.models import MarketPathPoint
from btc5_v3.execution.models import ExecutionConfig,ExitPolicy,LATENCY_GRID,SIZE_GRID,REBOUND_GRID,policy_grid
from btc5_v3.execution.depth import walk_depth
from btc5_v3.execution.engine import simulate
from btc5_v3.execution.demo import candidate,snapshot,resolved,TD,START,EXPIRY,CUTOFF,run_demo
from btc5_v3.execution.report import metrics,study_report
from btc5_v3.experiments.models import Experiment
from btc5_v3.storage.database import Database
from btc5_v3.storage.execution_repository import ExecutionRepository,TABLES,migrate_execution
from btc5_v3.storage.analytics_repository import RESEARCH_CONTRACT
from btc5_v3.storage.path_repository import PathRepository

D=Decimal
EXP='execution-test'
CODE='b'*40
CFG=ExecutionConfig()
HOLD=ExitPolicy()
REBOUND=ExitPolicy('BID_REBOUND',D('.20'))


def book(delay,*,bid='.10',ask='.12',bid_qty='100',ask_qty='100',seq=None,**kw):
    return MarketPathPoint.from_snapshot(snapshot(EXP,'m',delay+2 if seq is None else seq,TD+delay,
        bids=((bid,bid_qty),),asks=((ask,ask_qty),),**kw))


def run(books=(),*,original=None,outcome='default',config=CFG,policy=HOLD,cutoff=CUTOFF):
    return simulate(original or candidate(),books,resolved() if outcome=='default' else outcome,config,policy,
                    experiment_id=EXP,code_git=CODE,cutoff=cutoff,created_at=cutoff)


def data(books=(),**kw):return run(books,**kw).data()


def levels(prices,quantities,*,reverse=False):
    return [dict(price=D(p),quantity=D(q),liquidity_id='lot-'+str(i),origin_side='YES_BID' if reverse else 'YES_ASK',derived=False)
            for i,(p,q) in enumerate(zip(prices,quantities))]


def test_depth_walk_exact_required():
    f=walk_depth(levels(['.50','.55','.60'],[10,20,30]),D(40),direction='BUY',consumed={})
    assert [x['shares'] for x in f.legs]==[10,20,10] and f.notional==22 and f.vwap==D('.55')
    assert f.filled_shares==40 and f.unfilled_shares==0


def test_full_entry_50_multilevel():
    s=snapshot(EXP,'m',2,TD+250,bids=(('.60','200'),),asks=(('.61','20'),('.62','30'),('.64','100')))
    r=data([MarketPathPoint.from_snapshot(s)],config=replace(CFG,requested_shares=D(50)))
    f=r['fills'][0]
    assert r['entry_status']=='FULL_FILL' and D(f['vwap'])==D('.616')
    assert [D(x['shares']) for x in f['legs']]==[20,30]


def test_partial_entry_only_filled_position():
    r=data([book(250,ask_qty='60')])
    assert r['entry_status']=='PARTIAL_FILL'
    assert r['positions'][0]['filled_shares_net']=='60' and r['fills'][0]['unfilled_shares']=='40'
    assert any(x['kind']=='IOC_REMAINDER_CANCELLED' for x in r['order_events'])


@pytest.mark.parametrize('signal,delayed',[('.20','.35'),('.50','.40')])
def test_adverse_and_favorable_latency_use_later_book(signal,delayed):
    r=data([book(100,ask=signal,bid=str(D(signal)-D('.02'))),book(250,ask=delayed,bid=str(D(delayed)-D('.02')))],original=candidate(ask=signal))
    assert D(r['fills'][0]['vwap'])==D(delayed)
    assert D(r['fills'][0]['slippage_vs_decision_ask'])==D(delayed)-D(signal)
    assert r['fills'][0]['artificial_latency_cost_charged']=='0'


def test_signal_snapshot_never_fills_even_zero_latency():
    original=candidate();s=MarketPathPoint(canonical(original.data()['snapshot']))
    r=data([s],original=original,config=replace(CFG,decision_to_order_latency_ms=0))
    assert r['entry_status']=='NO_FILL' and not r['fills']


def test_m2_artificial_latency_estimate_not_charged_twice():
    r=data([book(250,ask='.35',bid='.33')],original=candidate(ask='.20',edge_latency_cost=D('.03')))
    assert r['accounting']['gross_entry_cost']=='35' and r['accounting']['net_simulated_pnl']=='-35'
    assert r['execution_diagnostics']['artificial_latency_cost_charged']=='0'


def test_no_causal_book_and_pending_not_premature_timeout():
    r=data([])
    assert r['entry_status']=='NO_FILL' and any(e.get('reason')=='NO_CAUSAL_BOOK' for e in r['order_events'])
    assert r['accounting']['net_simulated_pnl']=='0' and r['accounting']['exit_advantage']=='0'
    r=data([],cutoff=TD+100)
    assert r['entry_status']=='PENDING_CAUSAL_BOOK' and not any(e['kind']=='ORDER_NO_FILL' for e in r['order_events'])


def test_book_requires_source_and_available_after_ready():
    r=data([book(250,source_at=TD+100),book(500,source_at=TD+500)])
    assert r['fills'][0]['at']==TD+500


def test_first_stale_quote_skipped_then_next_valid():
    r=data([book(250,available_at=TD+4000),book(4500)])
    assert r['fills'][0]['at']==TD+4500
    assert r['book_selection_audit'][0]['rejected_books'][0]['reasons']==['STALE_SOURCE','STALE_RECEIPT']


def test_max_wait_is_enforced():
    assert data([book(5251)])['entry_status']=='NO_FILL'
    assert data([book(5250)])['entry_status']=='FULL_FILL'


def test_same_ms_sequence_deterministic():
    a=book(250,ask='.2',bid='.18',seq=3);b=book(250,ask='.3',bid='.28',seq=2)
    first=run([a,b]);second=run([b,a])
    assert first==second and first.data()['fills'][0]['vwap']=='0.3'


def test_availability_orders_not_sql_or_source_order():
    a=book(250,available_at=TD+500,ask='.2',bid='.18');b=book(300,ask='.3',bid='.28')
    assert data([a,b])['fills'][0]['vwap']=='0.3'


def test_m3_no_trade_produces_no_intent():
    r=data([book(250)],original=candidate(stale=True))
    assert r['entry_status']=='M3_REJECTED' and r['orders']==[] and r['ledger_entries']==[]


def test_report_retains_m3_refusal_without_selected_side():
    original=candidate(ask='.96');r=run([book(250)],original=original)
    assert r.data()['side'] is None and not r.data()['orders']
    report=study_report([dict(case='rejected',dimension='EXIT_POLICY',value='HOLD',original=original.data(),
        result=r.data(),execution_id=r.execution_id)],experiment_id=EXP,code_git=CODE)
    assert report['rows'][0]['side']=='UNSPECIFIED' and report['rows'][0]['initial_price_bucket'] is None
    assert report['grouped_results'][0]['funnel']['m3_rejected']==1


def test_size_cannot_override_m3_permission():
    r=data([book(250)],original=candidate(approved_size='10'),config=replace(CFG,requested_shares=D(50)))
    assert r['entry_status']=='SIZE_NOT_AUTHORIZED_BY_M3' and not r['orders']


def test_derived_no_correct_ask_and_bid():
    r=data([book(250,side='NO'),book(1000,bid='.6',ask='.62',side='NO'),book(1250,bid='.4',ask='.42',side='NO')],
        original=candidate(side='NO'),policy=REBOUND,outcome=resolved(payout=1))
    assert r['fills'][0]['vwap']=='0.12' and r['fills'][1]['vwap']=='0.4'
    assert all(x['derived'] for f in r['fills'] for x in f['legs'])
    assert r['accounting']['hold_to_settlement_pnl']=='-12'


def test_physical_liquidity_cannot_be_consumed_twice():
    s=snapshot(EXP,'m',2,TD+250,asks=(('.6','10'),))
    consumed={};a=walk_depth(s.yes_asks,7,direction='BUY',consumed=consumed)
    b=walk_depth(s.no_bids,7,direction='SELL',consumed=consumed)
    assert a.filled_shares==7 and b.filled_shares==3 and b.unfilled_shares==4
    assert sum(consumed.values())==10


def test_exit_latency_reversal_disappears():
    r=data([book(250),book(1000,bid='.70',ask='.72'),book(1250,bid='.35',ask='.37')],policy=REBOUND)
    assert r['fills'][1]['vwap']=='0.35'
    assert r['exit_attempts'][0]['trigger_bid']=='0.7' and r['exit_attempts'][0]['execution_bid']=='0.35'
    assert r['fills'][1]['at']==TD+1250


@pytest.mark.parametrize('payout,advantage',[(0,D(60)),(1,D(-40))])
def test_temporary_rebound_and_hold_can_win_more(payout,advantage):
    r=data([book(250,ask='.10',bid='.08'),book(1000,bid='.60',ask='.62'),book(1250,bid='.60',ask='.62')],policy=REBOUND,outcome=resolved(payout=payout))
    assert D(r['accounting']['net_simulated_pnl'])==50 and D(r['accounting']['exit_advantage'])==advantage


def test_exit_depth_walk_90_of_100_then_settle_10():
    s=snapshot(EXP,'m',3,TD+1250,bids=(('.80','20'),('.77','30'),('.70','40')),asks=(('.82','100'),))
    r=data([book(250),book(1000,bid='.80',ask='.82'),MarketPathPoint.from_snapshot(s)],policy=REBOUND,outcome=resolved(payout='.5'))
    assert r['exit_attempts'][0]['status']=='PARTIAL_EXIT'
    assert r['exit_attempts'][0]['remaining_shares']=='10'
    assert r['settlements'][0]['shares']=='10' and r['settlements'][0]['net_proceeds']=='5'
    assert r['accounting']['remaining_shares']=='0'


def test_multiple_partial_exits_30_40_then_settle_30():
    books=[book(250),book(1000,bid='.6',ask='.62'),book(1250,bid='.55',ask='.57',bid_qty='30'),
           book(1500,bid='.6',ask='.62'),book(1750,bid='.55',ask='.57',bid_qty='40')]
    r=data(books,policy=REBOUND,outcome=resolved(payout='.5'))
    assert [x['remaining_shares'] for x in r['exit_attempts']]==['70','30']
    assert r['settlements'][0]['shares']=='30'
    a=r['accounting'];assert D(a['initial_net_shares'])==D(a['exited_inventory_shares'])+D(a['settled_inventory_shares'])


def test_mid_jump_tiny_bid_depth_partial_not_chart_profit():
    r=data([book(250),book(1000,bid='.60',ask='.99'),book(1250,bid='.60',ask='.99',bid_qty='.000001')],policy=REBOUND)
    assert r['exit_attempts'][0]['status']=='PARTIAL_EXIT'
    assert r['fills'][1]['filled_shares_gross']=='0.000001'


def test_rebound_trigger_but_no_fresh_exit_book_retained():
    r=data([book(250),book(1000,bid='.60',ask='.62'),book(1250,bid='.60',ask='.62',source_at=TD+1000)],policy=REBOUND)
    m=metrics(r)
    assert m['triggered']==m['attempted']==m['failed_exits']==1
    assert m['fresh_execution_books']==0 and r['accounting']['exit_advantage']=='0'


def test_stale_trigger_is_counted_not_silently_deleted():
    r=data([book(250),book(5000,bid='.60',ask='.62',source_at=TD+1000)],policy=REBOUND)
    assert metrics(r)['stale_trigger_observations']==1 and metrics(r)['triggered']==0


def test_bid_trigger_not_mid_and_no_future_max_rule():
    r=data([book(250),book(1000,bid='.20',ask='.98'),book(1250,bid='.20',ask='.98')],policy=REBOUND)
    assert not r['exit_attempts']
    with pytest.raises(ValueError):ExitPolicy('FUTURE_MAX')


@pytest.mark.parametrize('allow,count',[(False,1),(True,2)])
def test_zero_exit_latency_requires_explicit_same_book_opt_in(allow,count):
    r=data([book(250),book(1000,bid='.6',ask='.62')],config=replace(CFG,exit_latency_ms=0,allow_same_book_zero_exit_latency=allow),policy=REBOUND)
    assert len(r['fills'])==count


def test_fixed_tte_clock_trigger_not_future_peak():
    later=MarketPathPoint.from_snapshot(snapshot(EXP,'m',99,EXPIRY-60000+250,bids=(('.3','100'),),asks=(('.32','100'),)))
    r=data([book(250),later],policy=ExitPolicy('FIXED_TTE',tte_ms=60000))
    assert r['exit_attempts'][0]['trigger_at']==EXPIRY-60000 and r['fills'][1]['vwap']=='0.3'


@pytest.mark.parametrize('payout',['0','.5','1'])
def test_split_and_binary_settlement(payout):
    r=data([book(250)],outcome=resolved(payout=payout))
    assert D(r['accounting']['net_simulated_pnl'])==100*D(payout)-12
    assert r['accounting']['remaining_shares']=='0'


def test_unresolved_remaining_pnl_null_but_cash_flow_visible():
    r=data([book(250)],outcome=None)
    assert r['accounting']['net_simulated_pnl'] is None and r['accounting']['remaining_shares']=='100'
    assert r['accounting']['realized_cash_flow']=='-12'


def test_future_outcome_not_used_before_available():
    r=data([book(250)],cutoff=EXPIRY)
    assert not r['settlements'] and r['accounting']['net_simulated_pnl'] is None


def test_collateral_fees_three_stages_no_double_count():
    fee=FeeModel(rate=D('.01'));cfg=replace(CFG,entry_fee=fee,exit_fee=fee,settlement_fee=fee)
    r=data([book(250),book(1000,bid='.6',ask='.62'),book(1250,bid='.5',ask='.52',bid_qty='40')],config=cfg,policy=REBOUND,outcome=resolved(payout='.5'))
    a=r['accounting']
    assert D(a['total_fees']['collateral'])==D('.12')+D('.20')+D('.30')
    assert D(a['net_simulated_pnl'])==D('37.38')
    assert D(a['gross_pnl'])-D(a['total_fees']['collateral'])==D(a['net_simulated_pnl'])


def test_share_fee_entry_exit_settlement_conservation():
    fee=FeeModel(denomination='SHARES',rate=D('.1'));cfg=replace(CFG,entry_fee=fee,exit_fee=fee,settlement_fee=fee)
    r=data([book(250),book(1000,bid='.6',ask='.62'),book(1250,bid='.5',ask='.52',bid_qty='40')],config=cfg,policy=REBOUND,outcome=resolved(payout=1))
    assert r['positions'][0]['filled_shares_net']=='90'
    assert r['exit_attempts'][0]['remaining_shares']=='46'
    assert r['settlements'][0]['fee_shares']=='4.6'
    assert r['accounting']['total_fees']['collateral']=='0'
    assert D(r['accounting']['net_simulated_pnl'])==D('49.4')


def test_share_fee_full_depth_rounding_does_not_oversell():
    fee=FeeModel(denomination='SHARES',rate=D('.03'))
    r=data([book(250),book(1000,bid='.6',ask='.62'),book(1250,bid='.5',ask='.52',bid_qty='1000')],config=replace(CFG,exit_fee=fee),policy=REBOUND,outcome=resolved(payout=1))
    assert r['accounting']['share_conservation'] and r['accounting']['remaining_shares']=='0'
    assert D(r['fills'][1]['inventory_removed'])<=100


def test_100_percent_entry_share_fee_not_duplicate_cash():
    r=data([book(250)],config=replace(CFG,entry_fee=FeeModel(denomination='SHARES',rate=1)))
    assert r['positions'][0]['filled_shares_net']=='0' and r['accounting']['net_simulated_pnl']=='-12'


def test_ledger_each_event_balances_and_reconciles_cash():
    r=data([book(250),book(1000,bid='.6',ask='.62'),book(1250,bid='.4',ask='.42')],policy=REBOUND)
    entries=r['ledger_entries']
    for key in {(x['event_id'],x['asset']) for x in entries}:
        assert sum(D(x['amount']) for x in entries if (x['event_id'],x['asset'])==key)==0
    assert sum(D(x['amount']) for x in entries if x['asset']=='COLLATERAL' and x['account']=='CASH')==D(r['accounting']['net_simulated_pnl'])


def test_future_quotes_do_not_change_past_business_events_or_intent():
    original=candidate();before=original.payload_json
    a=data([book(250)],original=original,cutoff=TD+2000,policy=REBOUND)
    b=data([book(250),book(10000,bid='.6',ask='.62'),book(10250,bid='.4',ask='.42')],original=original,policy=REBOUND)
    assert a['orders'][0]==b['orders'][0] and a['positions']==b['positions']
    assert a['order_events']==[x for x in b['order_events'] if x['at']<=TD+2000]
    assert original.payload_json==before


def test_changed_future_outcome_does_not_change_fills():
    b=[book(250)];a=data(b,outcome=resolved(payout=0));z=data(b,outcome=resolved(payout=1))
    for field in ('orders','fills','positions'):assert a[field]==z[field]
    assert a['accounting']['net_simulated_pnl']!=z['accounting']['net_simulated_pnl']


@pytest.mark.parametrize('kind',['experiment','market','outcome','duplicate','ambiguous','lineage'])
def test_invalid_references_rejected(kind):
    original=candidate();books=[book(250)];o=resolved()
    if kind=='experiment':books=[MarketPathPoint.from_snapshot(snapshot('other','m',2,TD+250))]
    if kind=='market':books=[MarketPathPoint.from_snapshot(snapshot(EXP,'other',2,TD+250))]
    if kind=='outcome':o=resolved('other')
    if kind=='duplicate':books*=2
    if kind=='ambiguous':books.append(book(250,bid='.2',ask='.22'))
    if kind=='lineage':
        from btc5_v3.analytics.models import ResearchObservation
        v=original.data();v['decision']['input_hash']='bad';original=ResearchObservation(canonical(v))
    with pytest.raises(ValueError):run(books,original=original,outcome=o)


def test_closed_execution_book_rejected():
    r=data([book(250,status='CLOSED')])
    assert r['entry_status']=='NO_FILL' and 'MARKET_NOT_KNOWN_OPEN' in r['book_selection_audit'][0]['rejected_books'][0]['reasons']


def test_config_hash_and_immutable_preregistered_grids():
    assert CFG.hash==ExecutionConfig.from_dict(json.loads(canonical(asdict(CFG)))).hash
    assert replace(CFG,exit_latency_ms=500).hash!=CFG.hash
    assert len(policy_grid())==10
    with pytest.raises(FrozenInstanceError):CFG.exit_latency_ms=1
    with pytest.raises(ValueError):ExitPolicy('BID_REBOUND',D('.17'))


def test_replay_independent_of_ambient_decimal_and_order():
    books=[book(250),book(1000,bid='.6',ask='.62'),book(1250,bid='.35',ask='.37')]
    a=run(books,policy=REBOUND)
    with localcontext() as ctx:
        ctx.prec=5
        assert run(reversed(books),policy=REBOUND)==a


def repo_open(tmp_path):
    db=Database(StorageConfig(tmp_path));repo=ExecutionRepository(db)
    repo.register(Experiment(EXP,CODE,'synthetic-execution-v1',42,START,digest(RESEARCH_CONTRACT)))
    return db,repo


def persist(repo,created=CUTOFF):
    return repo.run(candidate(),[book(250)],resolved(),CFG,HOLD,experiment_id=EXP,code_git=CODE,cutoff=CUTOFF,created_at=created)


def test_repository_idempotent_full_replay_and_reopen(tmp_path):
    db,repo=repo_open(tmp_path);a=persist(repo);assert persist(repo,CUTOFF+1)==a==repo.get_run(a.execution_id)
    assert db.connection.execute('SELECT COUNT(*) FROM execution_runs').fetchone()[0]==1
    assert db.connection.execute('SELECT COUNT(*) FROM market_snapshots').fetchone()[0]==0
    db.connection.close()
    with Database(StorageConfig(tmp_path)) as db:
        assert ExecutionRepository(db).get_run(a.execution_id)==a
        assert len(db.connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())==21


@pytest.mark.parametrize('table',['execution_runs','execution_results',*TABLES])
@pytest.mark.parametrize('operation',['UPDATE','DELETE','REPLACE'])
def test_immutable_execution_tables(tmp_path,table,operation):
    db,repo=repo_open(tmp_path)
    repo.run(candidate(),[book(250),book(1000,bid='.6',ask='.62'),book(1250,bid='.5',ask='.52',bid_qty='40')],resolved(),CFG,REBOUND,
             experiment_id=EXP,code_git=CODE,cutoff=CUTOFF,created_at=CUTOFF)
    statement={'UPDATE':f'UPDATE {table} SET experiment_id=experiment_id','DELETE':f'DELETE FROM {table}',
               'REPLACE':f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}'}[operation]
    with pytest.raises(sqlite3.IntegrityError):
        with db.connection:db.connection.execute(statement)
    db.connection.close()


@pytest.mark.parametrize('table',['execution_runs','execution_results','simulated_fills','simulated_ledger_entries'])
def test_replay_detects_corruption(tmp_path,table):
    db,repo=repo_open(tmp_path);a=persist(repo)
    field='input_hash' if table=='execution_runs' else 'payload_hash'
    with db.connection:
        db.connection.execute(f'DROP TRIGGER {table}_immutable_update')
        db.connection.execute(f"UPDATE {table} SET {field}='bad'")
    with pytest.raises(ValueError):repo.get_run(a.execution_id)
    db.connection.close()


def test_atomic_rollback_all_projections(tmp_path):
    db,repo=repo_open(tmp_path)
    db.connection.execute("CREATE TRIGGER injected BEFORE INSERT ON simulated_ledger_entries BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):persist(repo)
    assert all(db.connection.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]==0 for t in ('execution_runs','execution_results',*TABLES))
    db.connection.close()


def test_migration_rollback(tmp_path):
    with Database(StorageConfig(tmp_path)) as db:
        PathRepository(db);db.connection.execute('CREATE TABLE simulated_fills (id TEXT)')
        with pytest.raises(sqlite3.OperationalError):migrate_execution(db)
        assert db.connection.execute('PRAGMA user_version').fetchone()[0]==5
        assert db.connection.execute("SELECT name FROM sqlite_master WHERE name='execution_runs'").fetchone() is None


def test_synthetic_demo_full_grids_and_no_optimization(tmp_path):
    r=run_demo(tmp_path,CODE)
    assert r['cases']==8 and len(r['rows'])==160
    for case in {x['case'] for x in r['rows']}:
        rows=[x for x in r['rows'] if x['case']==case]
        assert [int(x['value']) for x in rows if x['dimension']=='LATENCY']==list(LATENCY_GRID)
        assert [D(x['value']) for x in rows if x['dimension']=='SIZE']==list(SIZE_GRID)
        assert len([x for x in rows if x['dimension']=='EXIT_POLICY'])==10
    assert any(x['failed_exits'] for x in r['intracycle_reversal_execution_study'])
    text=canonical(r).lower()
    for forbidden in ('best_latency','best_size','optimal_entry','optimal_exit','recommended_strategy'):assert forbidden not in text
    assert (tmp_path/'runtime/v3/m5-report.md').exists()
