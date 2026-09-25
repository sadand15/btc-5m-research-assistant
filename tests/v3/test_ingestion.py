"""Synthetic-only contracts. Never import the V2 database or use its runtime."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3

import pytest

from btc5_v3.config.models import StorageConfig, ValidatorConfig
from btc5_v3.experiments.models import Experiment
from btc5_v3.market.models import MarketSnapshot, Reason, temporal_usability
from btc5_v3.market.normalize import raw_event
from btc5_v3.market.validation import validate_market
from btc5_v3.storage.database import Database
from btc5_v3.storage.repository import Repository


@pytest.fixture
def cfg():
    return ValidatorConfig(market_id='synthetic-1', feed='SYNTHETIC', rule_hash='rule-v1')


@pytest.fixture
def payload():
    return dict(market_id='synthetic-1', source_at=1000, expiry=301000,
                market_type='CRYPTO_UP_DOWN', feed='SYNTHETIC', rule_hash='rule-v1',
                outcome_mapping='YES_UP', yes_bids=[['0.40','10'],['0.39','20']],
                yes_asks=[['0.42','12'],['0.43','21']],
                reference_underlying_price='100000', reference_price_at=990)


def raw(payload, **changes):
    args=dict(experiment_id='exp-1', source='synthetic', received_at=1010, sequence=1)
    args.update(changes)
    return raw_event(payload, **args)


@pytest.fixture
def repo(tmp_path,cfg):
    with Database(StorageConfig(project_root=tmp_path/'v3')) as db:
        repository=Repository(db,cfg)
        repository.register(Experiment('exp-1','a'*40,'synthetic-v1',42,900,cfg.hash))
        yield repository


def ingest(repo,payload,**changes):
    args=dict(experiment_id='exp-1',source='synthetic',received_at=1010,sequence=1,evaluation_at=1010)
    args.update(changes)
    return repo.ingest(payload,**args)


def test_valid_snapshot(cfg,payload):
    event=raw(payload);result=validate_market(event,cfg,evaluation_at=1010)
    assert result.status=='VALID' and result.primary_reason is None and result.all_reasons==()
    s=result.snapshot
    assert s.raw_event_id==event.id and s.yes_bid==Decimal('.40') and s.no_ask==Decimal('.60')
    assert s.no_bid==Decimal('.58') and s.yes_mid==Decimal('.41')
    assert s.yes_spread==Decimal('.02') and s.price_unit=='collateral/share'
    with pytest.raises(TypeError):MarketSnapshot()
    with pytest.raises(FrozenInstanceError):s.market_id='other'


@pytest.mark.parametrize('field,value,reason',[
    ('yes_bids',[],Reason.MISSING_BID),('yes_asks',[],Reason.MISSING_ASK),
    ('yes_bids',[[float('nan'),10]],Reason.NON_FINITE),
    ('yes_asks',[[.5,float('inf')]],Reason.NON_FINITE),
    ('yes_bids',[[0,10]],Reason.INVALID_PRICE),('yes_asks',[[1.2,10]],Reason.INVALID_PRICE),
    ('yes_bids',[[.4,0]],Reason.INVALID_QUANTITY),('yes_bids',[[.4,-2]],Reason.INVALID_QUANTITY),
    ('yes_bids',[[.6,10]],Reason.CROSSED_BOOK),
    ('source_at',1011,Reason.FUTURE_SOURCE_TIME),
    ('outcome_mapping','unknown',Reason.UNKNOWN_OUTCOME_MAPPING),
    ('rule_hash','different',Reason.RULE_MISMATCH),('feed','OTHER',Reason.RULE_MISMATCH),
    ('market_type','OTHER',Reason.UNSUPPORTED_MARKET),('market_id','wrong',Reason.WRONG_MARKET),
    ('yes_asks',[[.5]],Reason.INVALID_DEPTH),('source_at',-1,Reason.INVALID_TIMESTAMP),
    ('reference_price_at',1020,Reason.FUTURE_SOURCE_TIME),
])
def test_invalid_preserved_without_snapshot(repo,payload,field,value,reason):
    payload[field]=value
    result=ingest(repo,payload)
    assert result.status=='INVALID' and reason in result.all_reasons and result.snapshot is None
    assert repo.counts()=={'experiments':1,'raw_market_events':1,'market_validation_events':1,'market_snapshots':0}
    stored=repo.raw_events('exp-1')[0]
    assert json.loads(stored.safe_payload) is not None
    json.loads(stored.safe_payload,parse_constant=lambda x:pytest.fail('Nonfinite JSON literal'))


@pytest.mark.parametrize('bad',[b'{broken authorization: private-data',b'not json','[]',{'yes_bids':object()}])
def test_malformed_preserved(repo,bad):
    result=ingest(repo,bad)
    assert result.status=='INVALID' and result.snapshot is None
    assert repo.counts()['raw_market_events']==1


def test_multiple_reasons_stable(cfg,payload):
    payload.update(yes_bids=[],yes_asks=[],rule_hash='wrong')
    a=validate_market(raw(payload),cfg,evaluation_at=1010)
    b=validate_market(raw(payload),cfg,evaluation_at=1010)
    assert a==b and a.primary_reason==a.all_reasons[0]
    assert {Reason.MISSING_BID,Reason.MISSING_ASK,Reason.RULE_MISMATCH}<=set(a.all_reasons)


def test_freshness_separate_from_validity(cfg,payload):
    result=validate_market(raw(payload),cfg,evaluation_at=99999)
    assert result.status=='VALID'
    assert 'NOT_YET_AVAILABLE' in temporal_usability(result.snapshot,decision_at=1020,max_quote_age_ms=20).reasons
    s=validate_market(raw(payload),cfg,evaluation_at=1010).snapshot
    assert temporal_usability(s,decision_at=1020,max_quote_age_ms=20).usable
    old=temporal_usability(s,decision_at=1031,max_quote_age_ms=20)
    assert not old.usable and old.quote_age_ms==21 and 'QUOTE_STALE' in old.reasons
    early=temporal_usability(s,decision_at=1009,max_quote_age_ms=20)
    assert early.quote_age_ms==-1 and not early.usable
    assert not temporal_usability(s,decision_at=s.expiry,max_quote_age_ms=999999).usable


def test_negative_age_and_explicit_clock_tolerance(cfg,payload):
    assert Reason.NEGATIVE_QUOTE_AGE in validate_market(raw(payload),cfg,evaluation_at=1009).all_reasons
    payload['source_at']=1012
    tolerant=ValidatorConfig(market_id=cfg.market_id,feed=cfg.feed,rule_hash=cfg.rule_hash,clock_skew_tolerance_ms=2)
    s=validate_market(raw(payload),tolerant,evaluation_at=1010).snapshot
    assert s.source_at-s.received_at==2 and s.clock_skew_tolerance_ms==2
    assert cfg.hash!=tolerant.hash


def test_no_liquidity_double_count(cfg,payload):
    s=validate_market(raw(payload),cfg,evaluation_at=1010).snapshot
    assert s.no_derived and not s.liquidity_independent
    assert {x.liquidity_id for x in s.no_asks}=={x.liquidity_id for x in s.yes_bids}
    assert {x.liquidity_id for x in s.no_bids}=={x.liquidity_id for x in s.yes_asks}
    assert len(s.liquidity_groups)==len(s.yes_bids)+len(s.yes_asks)
    assert all(x.derived and x.origin_side=='YES_BID' for x in s.no_asks)


def test_normalization_merges_prices(cfg,payload):
    payload['yes_bids']=[['.39','2'],['.4','3'],['.40','4']]
    s=validate_market(raw(payload),cfg,evaluation_at=1010).snapshot
    assert [(l.price,l.quantity) for l in s.yes_bids]==[(Decimal('.4'),Decimal(7)),(Decimal('.39'),Decimal(2))]


def test_idempotency_and_conflicting_retry(repo,payload):
    first=ingest(repo,payload,event_key='upstream-1')
    retry=ingest(repo,payload,event_key='upstream-1',received_at=1020,sequence=2,evaluation_at=1020)
    assert first==retry and retry.snapshot.received_at==1010
    assert repo.counts()==dict(experiments=1,raw_market_events=1,market_validation_events=1,market_snapshots=1)
    payload['yes_bids'][0][0]='.41'
    with pytest.raises(ValueError,match='conflict'):ingest(repo,payload,event_key='upstream-1')


def test_same_millisecond_order_and_no_future_access(repo,payload):
    ingest(repo,payload,sequence=2)
    ingest(repo,payload,sequence=1)
    ingest(repo,payload,sequence=3,received_at=1020,evaluation_at=1020)
    events=repo.raw_events('exp-1',as_of=1010)
    assert [e.sequence for e in events]==[1,2]
    assert len(repo.raw_events('exp-1',as_of=1009))==0


def test_secrets_not_persisted(repo,payload):
    secrets=['credential-'+str(i)+'-do-not-persist' for i in range(4)]
    payload.update(Authorization=secrets[0],headers={'x-api-key':secrets[1]},Cookie=secrets[2],metadata={'secret':secrets[3]})
    result=ingest(repo,payload,transport_metadata={'Authorization':secrets[0]})
    assert result.status=='VALID'
    event=repo.raw_events('exp-1')[0]
    assert event.redaction_status=='REDACTED'
    dump='\n'.join(repo.db.connection.iterdump())
    assert all(s not in dump for s in secrets)
    assert 'Authorization' not in dump and 'x-api-key' not in dump


def test_bad_numeric_cannot_hide_credentials(repo,payload):
    secret='synthetic-'+('x'*24)  # Generated test marker, never a real credential.
    payload['yes_bids'][0][0]=secret
    assert ingest(repo,payload).status=='INVALID'
    assert secret not in '\n'.join(repo.db.connection.iterdump())


def test_crash_between_raw_and_validation_recoverable(repo,payload,monkeypatch):
    import btc5_v3.storage.repository as module
    original=module.validate_market
    def fail(*a,**kw):raise RuntimeError('injected validator failure')
    monkeypatch.setattr(module,'validate_market',fail)
    with pytest.raises(RuntimeError):ingest(repo,payload)
    assert repo.counts()['raw_market_events']==1 and repo.counts()['market_snapshots']==0
    monkeypatch.setattr(module,'validate_market',original)
    assert ingest(repo,payload).status=='VALID'
    assert repo.counts()['raw_market_events']==1


def test_experiment_immutable_and_missing_fk(repo,payload,cfg):
    with pytest.raises(ValueError,match='conflict'):
        repo.register(Experiment('exp-1','b'*40,'synthetic-v1',42,900,cfg.hash))
    with pytest.raises(ValueError,match='experiment'):
        ingest(repo,payload,experiment_id='not-registered')
    assert repo.db.connection.execute('PRAGMA foreign_keys').fetchone()[0]==1
    assert repo.db.connection.execute('PRAGMA journal_mode').fetchone()[0]=='wal'


def test_corrupt_snapshot_read_rejected(repo,payload):
    result=ingest(repo,payload)
    repo.db.connection.execute("UPDATE market_snapshots SET snapshot_json='{}'")
    repo.db.connection.commit()
    with pytest.raises(ValueError,match='integrity'):repo.get_snapshot(result.snapshot.snapshot_id)


def test_reproducible_after_reopen(tmp_path,cfg,payload):
    config=StorageConfig(project_root=tmp_path/'v3')
    with Database(config) as db:
        r=Repository(db,cfg);r.register(Experiment('exp-1','a'*40,'synthetic-v1',42,900,cfg.hash))
        first=ingest(r,payload)
    with Database(config) as db:
        r=Repository(db,cfg)
        assert r.get_snapshot(first.snapshot.snapshot_id)==first.snapshot
        assert ingest(r,payload)==first


def test_database_collision_rejected_before_open(tmp_path):
    original=tmp_path/'v2.sqlite';original.write_bytes(b'protected-sentinel')
    with pytest.raises(ValueError):Database(StorageConfig(project_root=tmp_path/'v3',database=original,protected_databases=(original,)))
    assert original.read_bytes()==b'protected-sentinel'


@pytest.mark.parametrize('alias_type',['symlink','hardlink'])
def test_database_alias_collision(tmp_path,alias_type):
    original=tmp_path/'v2.sqlite';original.write_bytes(b'protected-sentinel')
    root=tmp_path/'v3';folder=root/'runtime/v3';folder.mkdir(parents=True)
    alias=folder/'research.sqlite'
    try:
        if alias_type=='symlink':alias.symlink_to(original)
        else:os.link(original,alias)
    except OSError:pytest.skip('OS does not permit this filesystem alias')
    with pytest.raises(ValueError):Database(StorageConfig(project_root=root,protected_databases=(original,)))
    assert original.read_bytes()==b'protected-sentinel'


def test_runtime_directory_alias_rejected(tmp_path):
    root=tmp_path/'v3';root.mkdir();target=tmp_path/'shared';target.mkdir()
    try:(root/'runtime').symlink_to(target,target_is_directory=True)
    except OSError:pytest.skip('OS does not permit directory symlink')
    with pytest.raises(ValueError):Database(StorageConfig(project_root=root))
    assert list(target.iterdir())==[]


def test_identical_safe_payload_hash(payload):
    a=raw(payload);b=raw(dict(reversed(list(payload.items()))))
    assert a.payload_hash==b.payload_hash and a.safe_payload==b.safe_payload


def test_atomic_validation_snapshot_transaction(repo,payload):
    repo.db.connection.execute("CREATE TRIGGER fail_snapshot BEFORE INSERT ON market_snapshots BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):ingest(repo,payload)
    assert repo.counts()==dict(experiments=1,raw_market_events=1,market_validation_events=0,market_snapshots=0)
    repo.db.connection.execute('DROP TRIGGER fail_snapshot')
    assert ingest(repo,payload).status=='VALID'


def test_foreign_key_and_invalid_validation_cannot_create_snapshot(repo,payload,cfg):
    payload['yes_bids']=[]
    invalid=ingest(repo,payload)
    with pytest.raises(sqlite3.IntegrityError):
        with repo.db.connection as conn:
            conn.execute('INSERT INTO market_snapshots VALUES (?,?,?,?,?,?)',
                         ('fake','exp-1',invalid.raw_event_id,invalid.validation_id,'{}','fake'))
    repo.register(Experiment('exp-2','a'*40,'synthetic-v1',42,900,cfg.hash))
    with pytest.raises(sqlite3.IntegrityError):
        with repo.db.connection as conn:
            conn.execute('INSERT INTO market_validation_events VALUES (?,?,?,?,?,?,?,?,?)',
                         ('fake','exp-2',invalid.raw_event_id,'VALID',None,'[]','v',1010,'ctx'))


def test_concurrent_duplicate_ingestion(tmp_path,cfg,payload):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    config=StorageConfig(project_root=tmp_path/'v3')
    with Database(config) as db:
        Repository(db,cfg).register(Experiment('exp-1','a'*40,'synthetic-v1',42,900,cfg.hash))
    barrier=Barrier(2)
    def worker(_):
        barrier.wait(timeout=10)
        with Database(config) as db:
            return ingest(Repository(db,cfg),payload)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(worker,range(2)))
    assert results[0]==results[1]
    with Database(config) as db:
        assert Repository(db,cfg).counts()==dict(experiments=1,raw_market_events=1,market_validation_events=1,market_snapshots=1)


def test_sequence_cutoff_and_immutable_revalidation(repo,payload):
    original=ingest(repo,payload,sequence=1)
    ingest(repo,payload,sequence=2)
    assert [e.sequence for e in repo.raw_events('exp-1',as_of=1010,through_sequence=1)]==[1]
    assert ingest(repo,payload,sequence=1,evaluation_at=2000)==original


def test_decimal_context_does_not_change_replay(cfg,payload):
    from decimal import localcontext
    payload['yes_bids']=[['0.401234567890123456','10']]
    a=validate_market(raw(payload),cfg,evaluation_at=1010).snapshot
    with localcontext() as ctx:
        ctx.prec=2
        b=validate_market(raw(payload),cfg,evaluation_at=1010).snapshot
        assert b==a and b.yes_mid==a.yes_mid and b.yes_spread==a.yes_spread


@pytest.mark.parametrize('value',[10**5000, True, '1e9999'],ids=['huge_integer','boolean','huge_exponent'])
def test_extreme_numeric_input_is_preserved_invalid(repo,payload,value):
    payload['yes_bids'][0][0]=value
    assert ingest(repo,payload).status=='INVALID'
    assert repo.counts()['raw_market_events']==1


def test_nonfinite_is_symbolic_not_stored_numeric(repo,payload):
    payload['yes_bids'][0][0]=float('nan')
    ingest(repo,payload)
    stored=repo.raw_events('exp-1')[0]
    assert '[NON_FINITE]' in stored.safe_payload and 'NaN' not in stored.safe_payload


@pytest.mark.skipif(os.name!='nt',reason='Windows junction semantics')
def test_windows_junction_collision(tmp_path):
    import subprocess
    root=tmp_path/'v3';root.mkdir();target=tmp_path/'shared';target.mkdir()
    alias=root/'runtime'
    result=subprocess.run(['cmd','/c','mklink','/J',str(alias),str(target)],capture_output=True)
    assert result.returncode==0,'junction creation failed'
    try:
        with pytest.raises(ValueError):Database(StorageConfig(project_root=root))
        assert list(target.iterdir())==[]
    finally:os.rmdir(alias)


def test_synthetic_demo_idempotent(tmp_path):
    from btc5_v3.demo import run_demo
    first=run_demo(tmp_path/'v3','a'*40)
    second=run_demo(tmp_path/'v3','a'*40)
    assert first==second
    assert first['counts']==dict(experiments=1,raw_market_events=2,market_validation_events=2,market_snapshots=1)
    assert [e['status'] for e in first['events']]==['VALID','INVALID']
    assert first['events'][1]['reasons']==(Reason.CROSSED_BOOK,)


def test_explicit_recording_and_availability_times(repo,payload):
    result=ingest(repo,payload,recorded_at=1012,evaluation_at=1013)
    assert repo.raw_events('exp-1')[0].recorded_at==1012
    assert result.snapshot.received_at==1010 and result.snapshot.available_at==1013


def test_validation_cannot_precede_raw_persistence(repo,payload):
    result=ingest(repo,payload,recorded_at=1012,evaluation_at=1011)
    assert result.status=='INVALID' and Reason.INVALID_TIMESTAMP in result.all_reasons
    assert repo.counts()['raw_market_events']==1 and repo.counts()['market_snapshots']==0


def test_demo_refuses_dirty_git_identity(tmp_path,monkeypatch):
    import subprocess
    import sys
    from btc5_v3.demo import main
    subprocess.run(['git','init','--quiet',str(tmp_path)],check=True,capture_output=True)
    (tmp_path/'uncommitted.txt').write_text('synthetic change')
    monkeypatch.setattr(sys,'argv',['demo','--project-root',str(tmp_path)])
    with pytest.raises(ValueError,match='Commit changes'):main()
    assert not (tmp_path/'runtime').exists()


def test_existing_database_open_does_not_rewrite_schema(tmp_path,monkeypatch):
    import btc5_v3.storage.database as module
    config=StorageConfig(project_root=tmp_path/'v3')
    with Database(config):pass
    statements=[];connect=sqlite3.connect
    def traced(*args,**kwargs):
        conn=connect(*args,**kwargs);conn.set_trace_callback(statements.append);return conn
    monkeypatch.setattr(module.sqlite3,'connect',traced)
    with Database(config):pass
    assert not any(s.upper().startswith(('CREATE','BEGIN','INSERT','UPDATE','DELETE')) for s in statements)
    assert not any(s.upper().startswith('PRAGMA USER_VERSION=') for s in statements)
