"""Read-only observation regression. All databases are isolated synthetic fixtures."""
from dataclasses import replace,FrozenInstanceError
from decimal import Decimal
from pathlib import Path
import hashlib,json,sqlite3

import pytest

from btc5_v3.encoding import canonical,digest
from btc5_v3.config.models import StorageConfig
from btc5_v3.experiments.models import Experiment
from btc5_v3.storage.database import Database
from btc5_v3.storage.risk_repository import RiskRepository
from btc5_v3.storage.analytics_repository import RESEARCH_CONTRACT
from btc5_v3.risk.models import RiskConfig
from btc5_v3.risk.demo import candidate,book,outcome,healthy,approve,TD,START
from btc5_v3.execution.models import ExitPolicy
from btc5_v3.monitoring.models import ViewFilter
from btc5_v3.monitoring.service import MonitoringService

D=Decimal
EXP='monitoring-test';CODE='b'*40
VIEWER=dict(git_sha=CODE,branch='v3-dev',working_tree='CLEAN')


@pytest.fixture
def env(tmp_path):
    db=Database(StorageConfig(tmp_path,'runtime/v3/monitoring.sqlite'));repo=RiskRepository(db)
    repo.register(Experiment(EXP,CODE,'m7-synthetic-v1',42,START,digest(RESEARCH_CONTRACT)))
    run=repo.create_run(EXP,CODE,RiskConfig(),TD)
    service=MonitoringService(tmp_path,'runtime/v3/monitoring.sqlite')
    yield db,repo,run,service
    db.connection.close()


def observe(env,at=TD,**filters):
    return env[3].view(env[2],ViewFilter(at,**filters),viewer=VIEWER)


def original(market='m',**kwargs):return candidate(EXP,market,**kwargs)
def grant(env,o=None,**kwargs):return approve(env[1],env[2],o or original(),**kwargs)['risk_decision']['risk_decision_id']


def test_read_only_initial_service_and_full_chain(env):
    o=original();rid=grant(env,o)
    a=observe(env).data()
    assert not a['diagnostics'],a['diagnostics']
    assert a['overview']['capital']['reserved_cash']=='100'
    env[1].execute(env[2],rid,[book(o,TD+250)],cutoff=TD+250)
    v=observe(env,TD+250).data()
    assert not v['diagnostics'],v['diagnostics']
    assert v['overview']['reconciliation']=='RECONCILED'
    assert v['overview']['capital']['cash']=='950'
    assert v['overview']['capital']['open_exposure']=='50'
    assert v['positions'][0]['position_status']=='OPEN'
    assert v['executions'][0]['attempted_size']=='100'
    assert v['provenance']['evidence_mode']=='SYNTHETIC'
    assert {x['category'] for x in v['timeline']} >= {'prediction','candidate','permission','reservation','execution','position','ledger'}


def test_reduction_and_precise_reasons(env):
    grant(env,original(shares='180'))
    p=observe(env).data()['permissions'][0]
    assert p['permission']=='REDUCE' and p['requested_size']=='180' and p['approved_size']=='100'
    assert p['reason']=='POSITION_LIMIT' and 'SIZE_REDUCED' in p['all_reasons']
    assert p['m3_evidence']['decision_id']==p['source_m3_decision_id']


def test_partial_spend_60_release_40(env):
    o=original();rid=grant(env,o)
    env[1].execute(env[2],rid,[book(o,TD+250,ask='.75',bid='.73',quantity='80')],cutoff=TD+250)
    v=observe(env,TD+250).data()
    assert not v['diagnostics'],v['diagnostics']
    assert v['reservations'][0]['consumed_collateral']=='60'
    assert v['reservations'][0]['released_collateral']=='40'
    assert [x['status'] for x in v['reservation_history']]==['ACTIVE','PARTIALLY_CONSUMED','CONSUMED']
    assert v['positions'][0]['position_status']=='PARTIAL'
    assert v['overview']['capital']['equity']=='1000'


def test_future_fill_settlement_health_and_reject_do_not_change_past(env):
    o=original();rid=grant(env,o);past=observe(env)
    env[1].execute(env[2],rid,[book(o,TD+250)],cutoff=TD+250)
    open_view=observe(env,TD+250)
    t=outcome(o).available_at
    env[1].execute(env[2],rid,[book(o,TD+250)],outcome(o),cutoff=t)
    grant(env,original('rejected',at=t))
    env[1].control(env[2],'later-health','HEALTH',at=t+1,health=replace(healthy(t+1),provider_healthy=False))
    assert observe(env)==past and observe(env,TD+250)==open_view
    later=observe(env,t+1).data()
    assert later['positions'][0]['position_status']=='SETTLED'
    assert later['overview']['capital']['cash']=='950'
    assert any(x['permission']=='REJECT' for x in later['permissions'])


def test_query_connections_deny_all_writes(env):
    q=env[3].queries
    with q._reader() as c:
        for sql in ("INSERT INTO experiments VALUES ('a','b','{}','{}')",'UPDATE risk_runs SET id=id',
                    'DELETE FROM risk_runs','CREATE TABLE forbidden(x)','PRAGMA user_version=8',
                    "ATTACH DATABASE ':memory:' AS other",'PRAGMA query_only=OFF'):
            with pytest.raises(sqlite3.Error):c.execute(sql)
    assert not any(hasattr(q,x) for x in ('insert','update','delete','execute','migrate','write','create_run'))


def test_primary_hash_and_rows_unchanged_by_refresh(env):
    db,_,_,_=env;grant(env)
    db.connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    before=db.path.read_bytes();schema=db.connection.execute('PRAGMA user_version').fetchone()[0]
    rows=db.connection.execute('SELECT count(*) FROM risk_events').fetchone()[0]
    first=observe(env);assert first==observe(env)
    assert db.path.read_bytes()==before
    assert db.connection.execute('PRAGMA user_version').fetchone()[0]==schema
    assert db.connection.execute('SELECT count(*) FROM risk_events').fetchone()[0]==rows


def test_blind_table_is_never_read(env):
    db,_,_,service=env;grant(env);before=observe(env)
    db.connection.execute('CREATE TABLE blind_performance (pnl TEXT, win_rate TEXT, edge TEXT)')
    db.connection.execute("INSERT INTO blind_performance VALUES ('fixture-private','fixture-private','fixture-private')");db.connection.commit()
    assert observe(env)==before
    db.connection.execute("UPDATE blind_performance SET pnl='different-private'");db.connection.commit()
    assert observe(env)==before
    with service.queries._reader() as c:
        with pytest.raises(sqlite3.Error):c.execute('SELECT * FROM blind_performance')
    assert 'fixture-private' not in observe(env).payload_json


def test_no_domain_engine_called_on_refresh(env,monkeypatch):
    grant(env)
    def forbidden(*args,**kwargs):raise AssertionError('domain engine called')
    monkeypatch.setattr('btc5_v3.execution.engine.simulate',forbidden)
    monkeypatch.setattr('btc5_v3.risk.engine.apply_event',forbidden)
    monkeypatch.setattr('btc5_v3.storage.risk_repository.RiskRepository.__init__',forbidden)
    assert observe(env).data()['permissions'][0]['permission']=='APPROVE'


def test_filters_and_immutable_restart(env):
    grant(env,original('one'));grant(env,original('two'))
    v=observe(env,market_id='one',page_size=1)
    assert len(v.data()['permissions'])==1 and v.data()['permissions'][0]['market_id']=='one'
    assert v.data()['overview']['capital']['reserved_cash']=='200'
    with pytest.raises(FrozenInstanceError):v.payload_json='{}'
    changed=v.data();changed['overview']={};assert v.data()['overview']
    q=env[3].queries;fresh=MonitoringService(q.root,q.database)
    assert fresh.view(env[2],ViewFilter(TD,market_id='one',page_size=1),viewer=VIEWER)==v


def test_unknown_and_absent_db_never_created(tmp_path):
    s=MonitoringService(tmp_path,'runtime/v3/absent.sqlite')
    v=s.view('missing',ViewFilter(TD),viewer=VIEWER).data()
    assert v['overview']['capital'] is None and v['overview']['overall_health']=='UNKNOWN'
    assert not (tmp_path/'runtime').exists()


def test_stale_not_healthy_and_no_fake_midnight_reset(env):
    grant(env)
    v=observe(env,TD+40000).data()
    assert v['overview']['overall_health']=='STALE'
    assert v['overview']['last_known_event_at']==TD
    assert v['overview']['capital']['reserved_cash']=='100'
    assert v['provenance']['source_branch']=='UNKNOWN'


def rewrite_event(env,change):
    """Synthetic adversarial fixture with consistent hashes, not a production repair API."""
    db,_,run,_=env;c=db.connection
    from btc5_v3.storage.risk_repository import projections
    for table in ('risk_events','risk_decisions','capital_reservations','portfolio_snapshots'):
        c.execute('DROP TRIGGER '+table+'_immutable_update')
    previous=digest(json.loads(c.execute('SELECT payload_json FROM risk_runs WHERE id=?',(run,)).fetchone()[0]))
    for row in c.execute('SELECT * FROM risk_events WHERE run_id=? ORDER BY sequence',(run,)).fetchall():
        inputs=json.loads(row['inputs_json']);output=json.loads(row['output_json']);change(row,inputs,output)
        h=digest([previous,row['id'],row['sequence'],row['kind'],inputs,output])
        c.execute('UPDATE risk_events SET inputs_json=?,output_json=?,previous_hash=?,event_hash=? WHERE id=?',
                  (canonical(inputs),canonical(output),previous,h,row['id']))
        for table,values in projections(row['id'],row['kind'],output).items():
            for identity,payload,ph in values:
                c.execute('UPDATE '+table+' SET payload_json=?,payload_hash=? WHERE id=?',(payload,ph,identity))
        previous=h
    c.commit()


@pytest.mark.parametrize('table',('risk_runs','risk_events','risk_decisions','capital_reservations','portfolio_snapshots'))
def test_corrupt_row_diagnostic_not_crash(env,table):
    grant(env);c=env[0].connection
    c.execute('DROP TRIGGER '+table+'_immutable_update')
    field='output_json' if table=='risk_events' else 'payload_json'
    c.execute('UPDATE '+table+' SET '+field+"='{}'");c.commit()
    view=observe(env).data()
    assert view['diagnostics'] and view['overview']['capital'] is None
    assert view['overview']['reconciliation']=='CORRUPTED'


def test_missing_projection_foreign_reference_diagnostic(env):
    grant(env);c=env[0].connection
    c.execute('DROP TRIGGER capital_reservations_immutable_delete')
    c.execute('DELETE FROM capital_reservations');c.commit()
    assert any(x['source']=='capital_reservations' for x in observe(env).data()['diagnostics'])


@pytest.mark.parametrize('target',('reservation','permission','risk'))
def test_unknown_enum_does_not_become_healthy(env,target):
    grant(env)
    def change(row,i,o):
        if target=='reservation':o['reservation']['status']='UNRECOGNIZED'
        elif target=='permission':o['risk_decision']['action']='UNRECOGNIZED'
        else:o['state_after']['control_states']=['UNRECOGNIZED']
    rewrite_event(env,change)
    view=observe(env).data()
    assert any(x['type']=='UNKNOWN_ENUM' for x in view['diagnostics'])
    assert view['overview']['overall_health']=='DEGRADED'
    assert all(x['status']=='UNKNOWN' for x in view['risk'])


def test_invalid_m5_reference(env):
    o=original();rid=grant(env,o);env[1].execute(env[2],rid,[book(o,TD+250)],cutoff=TD+250)
    def change(row,i,o):
        if row['kind']=='EXECUTE':o['execution']['fills'][0]['order_id']='missing-order'
    rewrite_event(env,change)
    v=observe(env,TD+250).data()
    assert any(x['type']=='INVALID_REFERENCE' for x in v['diagnostics'])
    assert v['overview']['capital'] is None


@pytest.mark.parametrize('target',('ledger','capital','reservation'))
def test_arithmetic_mismatch_not_automatically_repaired(env,target):
    o=original();rid=grant(env,o);env[1].execute(env[2],rid,[book(o,TD+250)],cutoff=TD+250)
    def change(row,i,o):
        if row['kind']=='EXECUTE':
            if target=='ledger':o['execution']['ledger_entries'][0]['amount']='999'
            elif target=='capital':o['state_after']['cash']='999'
            else:o['reservation_changes'][0]['released_collateral']='999'
    rewrite_event(env,change);before=env[0].connection.total_changes
    v=observe(env,TD+250).data()
    assert any(x['type']=='MISMATCH' for x in v['diagnostics'])
    assert v['overview']['capital'] is None and env[0].connection.total_changes==before


@pytest.mark.parametrize('change',({'provider_healthy':'unknown'}, {'source_at':TD+1}, {'available_at':TD+1}, {'validation_failures':None}))
def test_malformed_health_becomes_unknown(env,change):
    grant(env)
    def edit(row,i,o):i['health'].update(change)
    rewrite_event(env,edit)
    v=observe(env).data()
    assert any(x['type']=='MALFORMED_HEALTH' for x in v['diagnostics'])
    assert next(x for x in v['health'] if x['component']=='provider')['status']=='UNKNOWN'
    later=observe(env,TD+1000).data()
    assert next(x for x in later['health'] if x['component']=='provider')['status']=='UNKNOWN'


def test_redaction_in_state_and_diagnostics(env):
    grant(env);sentinel='synthetic-'+('x'*30)
    def change(row,i,o):
        o['state_after']['api_key']=sentinel
        o['state_after']['unexpected']={'Authorization':'Bearer '+sentinel,'nested':{'private_key':sentinel}}
        o['state_after']['note']='Bearer '+sentinel
    rewrite_event(env,change)
    result=observe(env)
    assert sentinel not in result.payload_json and '[REDACTED]' in result.payload_json
    assert sentinel not in canonical(result.data()['diagnostics'])


@pytest.mark.parametrize('value',('[]','null','{"x":NaN}','{"x":{"x":1}}'))
def test_malformed_payload_never_throws(env,value):
    grant(env);c=env[0].connection;c.execute('DROP TRIGGER risk_events_immutable_update')
    if 'NaN' in value:
        c.execute('PRAGMA ignore_check_constraints=ON')
    c.execute('UPDATE risk_events SET output_json=?',(value,));c.commit()
    assert observe(env).data()['diagnostics']


def test_reservation_release_expiry_and_pause_revision(env):
    a=grant(env,original('a'));b=grant(env,original('b'))
    env[1].execute(env[2],a,[],cutoff=TD+5250)
    # The stale archived health at this point revokes pending b under M6.
    v=observe(env,TD+5250).data()
    assert {x['status'] for x in v['reservations']}=={'RELEASED'}
    assert any(x.get('release_reason')=='RISK_PAUSE' for x in v['reservations'])


def test_expired_status(env):
    rid=grant(env)
    env[1].expire(env[2],rid,at=TD+10000)
    v=observe(env,TD+10000).data()
    assert v['reservations'][0]['status']=='EXPIRED'
    assert v['reservation_history'][0]['status']=='ACTIVE'


def test_pending_open_partial_exit_and_exited(env):
    o=original();rid=grant(env,o,policy=ExitPolicy('BID_REBOUND',D('.20')))
    assert observe(env).data()['positions'][0]['position_status']=='PENDING'
    books=[book(o,TD+250)]
    env[1].execute(env[2],rid,books,cutoff=TD+250)
    assert observe(env,TD+250).data()['positions'][0]['position_status']=='OPEN'
    books += [book(o,TD+1000,seq=3,bid='.80',ask='.82'),book(o,TD+1250,seq=4,bid='.75',ask='.77',quantity='40')]
    env[1].execute(env[2],rid,books,cutoff=TD+1250)
    assert observe(env,TD+1250).data()['positions'][0]['position_status']=='PARTIAL'
    books += [book(o,TD+1500,seq=5,bid='.80',ask='.82'),book(o,TD+1750,seq=6,bid='.75',ask='.77')]
    env[1].execute(env[2],rid,books,cutoff=TD+1750)
    v=observe(env,TD+1750).data()
    assert v['positions'][0]['position_status']=='EXITED' and v['overview']['reconciliation']=='RECONCILED'


def test_yes_no_gross_not_netted(env):
    a=original(side='YES',attempt='yes');b=original(side='NO',attempt='no')
    ar=grant(env,a);br=grant(env,b)
    env[1].execute(env[2],ar,[book(a,TD+250)],cutoff=TD+250)
    env[1].execute(env[2],br,[book(b,TD+250)],cutoff=TD+250)
    v=observe(env,TD+250).data()
    assert len(v['positions'])==2 and {x['side'] for x in v['positions']}=={'YES','NO'}
    assert v['overview']['capital']['open_exposure']=='100'


def test_manual_pause_and_data_provider_controls(env):
    grant(env)
    env[1].control(env[2],'manual','PAUSE',at=TD+1)
    env[1].control(env[2],'unhealthy','HEALTH',at=TD+2,health=replace(healthy(TD+2),provider_healthy=False,source_matches=False))
    v=observe(env,TD+2).data()
    flags={x['risk_guard'] for x in v['risk'] if x['status']=='PAUSED'}
    assert flags=={'MANUALLY_PAUSED','PAUSED_DATA','PAUSED_PROVIDER'}
    assert all(x['source_event_id'] for x in v['risk'] if x['status']=='PAUSED')


def test_utc_reset_only_when_recorded_and_latch_persists(env):
    db,repo,_,service=env
    cfg=replace(RiskConfig(),max_position_notional=D(300),max_position_fraction=D(1),max_market_exposure=D(500))
    run=repo.create_run(EXP,CODE,cfg,TD);o=original(shares='300')
    rid=approve(repo,run,o)['risk_decision']['risk_decision_id'];t=outcome(o).available_at
    repo.execute(run,rid,[book(o,TD+250)],outcome(o),cutoff=t)
    nextday=START+86400000
    before=service.view(run,ViewFilter(nextday),viewer=VIEWER).data()
    assert next(x for x in before['risk'] if x['risk_guard']=='PAUSED_DAILY_LOSS')['status']=='PAUSED'
    repo.control(run,'utc-day','HEALTH',at=nextday,health=healthy(nextday))
    after=service.view(run,ViewFilter(nextday),viewer=VIEWER).data()
    assert next(x for x in after['risk'] if x['risk_guard']=='PAUSED_DAILY_LOSS')['status']=='INACTIVE'
    assert next(x for x in after['risk'] if x['risk_guard']=='PAUSED_DRAWDOWN')['status']=='LATCHED'
    past=service.view(run,ViewFilter(TD),viewer=VIEWER).data()
    assert all(x['status']=='INACTIVE' for x in past['risk'])


def test_loss_streak_latch_display(env):
    db,repo,_,service=env
    cfg=replace(RiskConfig(),max_daily_simulated_loss=D(1000),max_drawdown=D(1))
    run=repo.create_run(EXP,CODE,cfg,TD)
    for n in range(3):
        at=TD+n*300000
        if n:repo.control(run,'refresh-'+str(n),'RECONCILE',at=at)
        o=original('m'+str(n),at=at);rid=approve(repo,run,o)['risk_decision']['risk_decision_id']
        t=outcome(o).available_at;repo.execute(run,rid,[book(o,at+250)],outcome(o),cutoff=t)
    v=service.view(run,ViewFilter(t),viewer=VIEWER).data()
    guard=next(x for x in v['risk'] if x['risk_guard']=='PAUSED_LOSS_STREAK')
    assert guard['status']=='LATCHED' and guard['current_value']==3 and guard['category']=='Persistent Latch'


def test_archive_budget_is_explicit_incomplete(env):
    grant(env,original('a'));grant(env,original('b'))
    q=env[3].queries
    s=MonitoringService(q.root,q.database,max_events=1)
    v=s.view(env[2],ViewFilter(TD),viewer=VIEWER).data()
    assert any(x['type']=='INCOMPLETE' for x in v['diagnostics'])
    assert v['overview']['capital'] is None and v['overview']['reconciliation']=='INCOMPLETE'


def test_timeline_sorting_and_unique_ledger(env):
    o=original();rid=grant(env,o);books=[book(o,TD+250)]
    env[1].execute(env[2],rid,books,cutoff=TD+250)
    env[1].execute(env[2],rid,books,cutoff=TD+500)
    v=observe(env,TD+500,page_size=200).data()
    keys=[(x['timestamp'],x['sequence'],x['category'],x['source_id']) for x in v['timeline']]
    assert keys==sorted(keys)
    assert len({x['ledger_id'] for x in v['ledger']})==len(v['ledger'])
    assert v['overview']['capital']['cash']=='950'


@pytest.mark.parametrize('field',('market_id','candidate_id','permission','reason','reservation_id','execution_id','position_status','health_state','risk_guard','category'))
def test_filters_do_not_write_or_alter_totals(env,field):
    o=original();rid=grant(env,o);env[1].execute(env[2],rid,[book(o,TD+250)],cutoff=TD+250)
    base=observe(env,TD+250).data();before=env[0].connection.total_changes
    changed=observe(env,TD+250,**{field:'no-match'}).data()
    assert changed['overview']==base['overview']
    assert env[0].connection.total_changes==before


def test_range_and_pagination(env):
    grant(env,original('a'));grant(env,original('b'))
    first=observe(env,page_size=1).data();second=observe(env,page_size=1,page=1).data()
    assert first['permissions'][0]['candidate_id']!=second['permissions'][0]['candidate_id']
    assert not observe(env,start_at=TD+1).data()['permissions']
    assert not observe(env,end_at=TD-1).data()['permissions']


def test_demo_deterministic_and_all_evidence(tmp_path):
    from btc5_v3.monitoring.demo import run_demo
    first=run_demo(tmp_path,CODE);assert first==run_demo(tmp_path,CODE)
    assert len(first['cases'])==6 and first['primary_db_unchanged']
    for case in first['cases']:
        v=case['view'];assert v['permissions'] and v['executions'] and v['ledger'] and v['timeline'] and v['provenance']
        assert v['overview']['reconciliation']=='RECONCILED'


def test_dashboard_import_startup_all_pages_and_refresh_read_only(env,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from btc5_v3.monitoring.models import PAGES
    import importlib
    grant(env)
    db,_,_,service=env
    db.connection.execute('PRAGMA wal_checkpoint(TRUNCATE)');before=hashlib.sha256(db.path.read_bytes()).hexdigest()
    module=importlib.import_module('btc5_v3.monitoring.dashboard')
    assert hashlib.sha256(db.path.read_bytes()).hexdigest()==before
    script='from btc5_v3.monitoring.dashboard import main\nmain('+repr(str(service.queries.root))+','+repr(str(service.queries.database))+')'
    app=AppTest.from_string(script,default_timeout=20).run()
    assert not app.exception,app.exception
    for page in PAGES:
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception,app.exception
    buttons=[b.label for b in app.button]
    assert buttons==['Refresh · 只读刷新']
    app.button[0].click().run();assert not app.exception
    assert hashlib.sha256(db.path.read_bytes()).hexdigest()==before


def test_dashboard_missing_archive_does_not_create_files(tmp_path):
    from streamlit.testing.v1 import AppTest
    script='from btc5_v3.monitoring.dashboard import main\nmain('+repr(str(tmp_path))+')'
    app=AppTest.from_string(script).run()
    assert not app.exception and not (tmp_path/'runtime').exists()


def test_missing_execution_identity(env):
    o=original();rid=grant(env,o);env[1].execute(env[2],rid,[book(o,TD+250)],cutoff=TD+250)
    def change(row,i,o):
        if row['kind']=='EXECUTE':o['execution_id']='missing-reference'
    rewrite_event(env,change)
    assert any(x['type']=='INVALID_REFERENCE' for x in observe(env,TD+250).data()['diagnostics'])


def test_missing_provenance_unknown_not_invented(env):
    grant(env);c=env[0].connection
    metadata=json.loads(c.execute('SELECT metadata_json FROM experiments').fetchone()[0]);metadata.pop('data_version')
    c.execute('UPDATE experiments SET metadata_json=?',(canonical(metadata),));c.commit()
    v=observe(env).data()
    assert v['provenance']['source_dataset']=='UNKNOWN'
    assert any(x['type']=='MISSING_PROVENANCE' for x in v['diagnostics'])


def test_redaction_wallet_header_and_url_patterns():
    from btc5_v3.monitoring.diagnostics import redact
    sentinel='test-'+('z'*30)
    data={'mnemonic':sentinel,'seed_phrase':sentinel,'session_token':sentinel,
          'headers':{'Authorization':'Bearer '+sentinel},'note':''.join(('https', '://', 'user:', sentinel, '@example.invalid/path'))}
    assert sentinel not in canonical(redact(data))
    assert canonical(redact(data)).count('[REDACTED]')>=5


def test_query_count_bounded_and_blind_read_authorizer(env,monkeypatch):
    from contextlib import contextmanager
    q=env[3].queries;grant(env,original('a'));grant(env,original('b'))
    calls=[];reader=q._reader
    @contextmanager
    def traced():
        with reader() as c:
            c.set_trace_callback(calls.append)
            yield c
    monkeypatch.setattr(q,'_reader',traced)
    observe(env)
    assert len([x for x in calls if x.lstrip().upper().startswith('SELECT')])==6
    assert all('blind' not in x.lower() for x in calls)


def test_byte_budget_not_silent_truncation(env,monkeypatch):
    grant(env)
    monkeypatch.setattr('btc5_v3.monitoring.queries.MAX_ARCHIVE_BYTES',100)
    v=observe(env).data()
    assert v['overview']['capital'] is None
    assert any(x['type']=='INCOMPLETE' for x in v['diagnostics'])


def test_schema_mismatch_not_migrated(env):
    db,_,_,_=env;grant(env)
    db.connection.execute('PRAGMA user_version=6')
    v=observe(env).data()
    assert v['diagnostics'] and db.connection.execute('PRAGMA user_version').fetchone()[0]==6


def test_unrecognized_evidence_never_becomes_real(env):
    grant(env);c=env[0].connection
    c.execute('UPDATE experiments SET config_json=?',(canonical({'mode':'REAL_OR_BLIND'}),));c.commit()
    v=observe(env).data()
    assert v['evidence_mode']=='UNKNOWN' and not v['permissions']


def test_old_view_ignores_future_corruption(env):
    grant(env);before=observe(env)
    env[1].control(env[2],'future','PAUSE',at=TD+100)
    c=env[0].connection;c.execute('DROP TRIGGER risk_events_immutable_update')
    c.execute("UPDATE risk_events SET output_json='{}' WHERE at>?",(TD,));c.commit()
    assert observe(env)==before


def test_primary_live_wal_reader_sees_latest_without_checkpoint(env):
    grant(env)
    # The writing connection is still open; immutable=1 would miss WAL changes.
    assert observe(env).data()['permissions'][0]['permission']=='APPROVE'


def test_dashboard_full_execution_and_diagnostics_pages(env):
    from streamlit.testing.v1 import AppTest
    o=original();rid=grant(env,o);env[1].execute(env[2],rid,[book(o,TD+250)],cutoff=TD+250)
    q=env[3].queries;script='from btc5_v3.monitoring.dashboard import main\nmain('+repr(str(q.root))+','+repr(str(q.database))+')'
    app=AppTest.from_string(script,default_timeout=20).run()
    for page in ('Positions','Executions','Ledger','Timeline'):
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception and app.dataframe
    c=env[0].connection;c.execute('DROP TRIGGER portfolio_snapshots_immutable_update')
    c.execute("UPDATE portfolio_snapshots SET payload_json='{}'");c.commit()
    app.sidebar.radio[0].set_value('Diagnostics').run()
    assert not app.exception and app.warning


def test_dashboard_headless_http_start(tmp_path):
    import subprocess,sys,socket,time,urllib.request
    entry=Path(__file__).resolve().parents[2]/'src/btc5_v3/monitoring/dashboard.py'
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    command=[sys.executable,'-m','streamlit','run',str(entry),'--server.address=127.0.0.1',
             '--server.port='+str(port),'--server.headless=true','--browser.gatherUsageStats=false',
             '--','--project-root',str(tmp_path)]
    kwargs={'creationflags':subprocess.CREATE_NO_WINDOW} if sys.platform=='win32' else {}
    child=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**kwargs)
    try:
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if child.poll() is not None:pytest.fail('headless dashboard exited')
            try:
                with urllib.request.urlopen('http://127.0.0.1:'+str(port)+'/_stcore/health',timeout=1) as response:
                    if response.read()==b'ok':break
            except OSError:time.sleep(.1)
        else:pytest.fail('headless dashboard did not become healthy')
        assert not (tmp_path/'runtime').exists()
    finally:
        child.terminate()
        try:child.wait(timeout=10)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=10)
