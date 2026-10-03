"""Synthetic-only operational evidence invariants; no market network or performance."""
import json
import sqlite3
from pathlib import Path
import pytest
from btc5_v3.encoding import canonical, digest
from btc5_v3.prospective.models import definition, safe_payload
from btc5_v3.prospective.identity import APPROVED, identity
from btc5_v3.prospective.sources import source_spec, Binance
from btc5_v3.prospective.store import Study, Writer, rows, read, lock
from btc5_v3.prospective.adapter import load_sealed


class Clock:
    def __init__(self, at=300000):self.at=at
    def __call__(self):return self.at


def proof():
    return dict(baseline_git_sha=APPROVED,collector_git_sha='a'*40,branch='synthetic-test',
                model_hash=digest('synthetic'),baseline_config_hash=digest('configuration'))


def setup(root, name='case', end=7500000):
    s=Study(root,name)
    s.create(definition(name,name+'-dataset',1,300000,end,source_spec('synthetic'),proof(),'SYNTHETIC_TEST'))
    s.arm(2,proof())
    return s,Clock()


def emit(w,c,key='one',**kw):
    args=dict(source='synthetic',event_key=key,source_at=c(),received_at=c(),payload={'price':'100'})
    args.update(kw)
    return w.observation(**args)


def sealed(root):
    s,c=setup(root,end=600000)
    with Writer(s,proof,c) as w:
        w.heartbeat();emit(w,c)
        c.at=600000;w.seal()
    return s,c


@pytest.mark.parametrize('start,end,created',[(300000,600000,300000),(300001,600000,1),(300000,600001,1),(300000,0,1)])
def test_future_aligned_window(start,end,created):
    with pytest.raises(ValueError):definition('s','d',created,start,end,source_spec('synthetic'),proof())


def test_arm_immutable_future_and_wrong_baseline(tmp_path):
    s,c=setup(tmp_path)
    old=s.path('manifest.json').read_bytes()
    with pytest.raises(ValueError):s.arm(3,proof())
    assert s.path('manifest.json').read_bytes()==old
    with pytest.raises(ValueError):
        with Writer(s,lambda:dict(proof(),baseline_git_sha='b'*40),c):pass
    assert s.status(c())['state']=='INTERRUPTED'


@pytest.mark.parametrize('at',[299999,7500000,7500001])
def test_outside_window(tmp_path,at):
    s,c=setup(tmp_path);c.at=at
    with Writer(s,proof,c) as w:
        with pytest.raises(ValueError):emit(w,c)


def test_segments_restart_dedup_and_conflict(tmp_path):
    s,c=setup(tmp_path)
    with Writer(s,proof,c) as w:
        assert emit(w,c)
        assert not emit(w,c)
        with pytest.raises(ValueError,match='CONFLICT'):emit(w,c,payload={'price':'101'})
        c.at=3600000;emit(w,c,'two');w.heartbeat()
    c.at+=120000
    with Writer(s,proof,c) as w:
        assert not emit(w,c,'one',source_at=300000)
        emit(w,c,'three');w.finalize()
    assert s.verify()['segments']==3
    assert s.status(c())['observations']==3
    assert any(g['type']=='UNKNOWN' for g in s.status(c())['gaps'])


def test_source_outage_distinct_from_collector(tmp_path):
    s,c=setup(tmp_path)
    with Writer(s,proof,c) as w:
        w.source_failure();w.heartbeat()
        c.at+=30000;w.heartbeat()
        c.at+=30000;emit(w,c);w.heartbeat()
    result=s.status(c())
    assert result['observations']==1
    assert [g['type'] for g in result['gaps'] if g['source']=='synthetic']==['SOURCE_CONNECTION_FAILURE']
    assert result['source_health']=='OK'


def test_failure_interval_survives_restart(tmp_path):
    s,c=setup(tmp_path)
    with Writer(s,proof,c) as w:w.source_failure();w.heartbeat()
    c.at+=100000
    with Writer(s,proof,c) as w:emit(w,c)
    assert any(g['duration_ms']==100000 and g['type']=='SOURCE_CONNECTION_FAILURE' for g in s.status(c())['gaps'])


def test_explicit_stop_restart_preserves_gap(tmp_path):
    s,c=setup(tmp_path)
    with Writer(s,proof,c) as w:w.heartbeat();w.stop()
    c.at+=120000
    with Writer(s,proof,c) as w:w.heartbeat()
    assert any(g['type']=='COLLECTOR_DOWN' for g in s.status(c())['gaps'])


@pytest.mark.parametrize('fault_point',['after_commit','after_segment_rename'])
def test_crash_after_commit_or_rename(tmp_path,fault_point):
    s,c=setup(tmp_path)
    def crash(where):
        if where==fault_point:raise RuntimeError('synthetic power loss')
    with pytest.raises(RuntimeError):
        with Writer(s,proof,c,fault=crash) as w:
            emit(w,c);w.finalize()
    with Writer(s,proof,c) as w:
        assert not emit(w,c)
        w.finalize()
    assert s.status(c())['observations']==1
    assert s.verify()['valid']


def test_sqlite_partial_transaction_rollback(tmp_path):
    s,c=setup(tmp_path)
    with Writer(s,proof,c) as w:emit(w,c)
    p=s.path('journal-000001.sqlite')
    db=sqlite3.connect(p);db.execute('INSERT INTO events VALUES(2,?)',('{}',));db.close()
    assert len(rows(p))==1
    with sqlite3.connect(p) as db:
        with pytest.raises(sqlite3.IntegrityError):db.execute('DELETE FROM events')


def test_partial_file_recovery(tmp_path):
    s,c=setup(tmp_path)
    with Writer(s,proof,c) as w:emit(w,c)
    s.path('segment-000001.json.tmp').write_bytes(b'{partial')
    with Writer(s,proof,c):pass
    assert s.verify()['valid']
    assert not list(s.folder.glob('*.tmp'))


@pytest.mark.parametrize('target',['segment','manifest','missing','reordered','journal','seal'])
def test_tamper_detection(tmp_path,target):
    s,c=sealed(tmp_path)
    p=s.path('segment-000001.json')
    if target=='segment':
        value=read(p);value['events'][0]['at']+=1;p.write_text(canonical(value))
    elif target=='missing':p.unlink()
    elif target=='reordered':p.rename(s.path('segment-000002.json'))
    elif target=='manifest':
        p=s.path('manifest.json');value=read(p);value['collection_end']+=300000;p.write_text(canonical(value))
    elif target=='journal':s.path('journal-000001.sqlite').unlink()
    else:
        p=s.path('sealed.json');value=read(p);value['record_count']+=1;p.write_text(canonical(value))
    with pytest.raises((ValueError,FileNotFoundError)):s.verify(require_sealed=True)
    assert s.status(c())['state']=='INVALID'


def test_sealed_all_writes_denied_and_adapter(tmp_path):
    s,c=sealed(tmp_path)
    before={p.name:p.read_bytes() for p in s.folder.iterdir() if p.name!='writer.lock'}
    with pytest.raises(ValueError,match='SEALED'):
        with Writer(s,proof,c):pass
    with pytest.raises(ValueError):s.arm(2,proof())
    candidate=load_sealed(s,c())
    assert candidate.manifest.role=='VALIDATION' and candidate.manifest.evidence_mode=='PROSPECTIVE'
    assert candidate.manifest.collection_origin=='SYNTHETIC_TEST'
    assert len(candidate.records())==1 and candidate.readiness.startswith('NOT_REPLAY_READY')
    from btc5_v3.data_quality.checks import quality_report
    quality=quality_report(candidate,c())
    assert quality['counts']['INVALID']==1
    assert before=={p.name:p.read_bytes() for p in s.folder.iterdir() if p.name!='writer.lock'}


def test_unsealed_and_early_adapter_rejected(tmp_path):
    s,c=setup(tmp_path)
    with pytest.raises(ValueError):load_sealed(s,c())
    s2,c2=sealed(tmp_path/'second')
    with pytest.raises(ValueError):load_sealed(s2,599999)


def test_no_peeking_status(tmp_path):
    s,c=setup(tmp_path)
    with Writer(s,proof,c) as w:
        emit(w,c,payload={'price':'100','prediction':{'probability':'.99','pnl':'999'}})
        w.heartbeat()
    text=canonical(s.status(c()))
    for forbidden in ('probability','pnl','win_rate','accuracy','brier','edge','999'):
        assert forbidden not in text.lower()


@pytest.mark.parametrize('source_at,quality',[(None,'UNKNOWN_SOURCE_TIME'),(299999,'PRE_WINDOW_SOURCE'),(300002,'FUTURE_SOURCE_TIME')])
def test_bad_source_time_diagnostic_only(tmp_path,source_at,quality):
    s,c=setup(tmp_path)
    with Writer(s,proof,c) as w:emit(w,c,source_at=source_at)
    assert s.status(c())['observations']==0
    assert any(e['payload'].get('quality')==quality for e in s.events())


def test_stale_source_and_clock_reversal(tmp_path):
    s,c=setup(tmp_path);c.at=400000
    with Writer(s,proof,c) as w:
        emit(w,c,source_at=300000)
        c.at-=1
        with pytest.raises(ValueError,match='CLOCK'):w.heartbeat()
    assert s.status(c())['observations']==0
    assert s.status(c())['interruptions'][-1]['reason']=='LOCAL_CLOCK_REVERSED'


def test_lock_and_path_isolation(tmp_path):
    s,c=setup(tmp_path)
    with lock(s.path('writer.lock')):
        with pytest.raises(ValueError,match='WRITER'):
            with Writer(s,proof,c):pass
    for name in ('..','.', '../escape','C:drive'):
        with pytest.raises(ValueError):Study(tmp_path,name)


def test_credentials_not_persisted(tmp_path):
    marker='pred_'+'sk_'+'syntheticcredentialneverreal'
    s,c=setup(tmp_path)
    with Writer(s,proof,c) as w:
        emit(w,c,payload={'api_key':marker,'price':marker,'prediction':{'authorization':marker}})
    for p in s.folder.iterdir():assert marker.encode() not in p.read_bytes()


def test_binance_is_latest_get_only():
    class Response:
        status_code=200
        def json(self):return [dict(a=7,T=300000,p='100',q='2')]
    class HTTP:
        def get(self,url,**kwargs):
            assert url=='https://data-api.binance.vision/api/v3/aggTrades'
            assert kwargs['params']=={'symbol':'BTCUSDT','limit':1}
            assert kwargs['allow_redirects'] is False
            return Response()
    result=Binance(Clock(),HTTP()).poll()
    assert result['event_key']=='7' and result['received_at']==300000


def test_locked_domain_sources_still_approved():
    root=Path(__file__).resolve().parents[2]
    actual=identity(root,strict=False)
    assert actual['baseline_git_sha']==APPROVED
    assert len(actual['collector_hash'])==64


def test_unique_dataset_across_studies(tmp_path):
    setup(tmp_path)
    other=Study(tmp_path,'other')
    with pytest.raises(ValueError,match='DATASET_ID'):
        other.create(definition('other','case-dataset',1,300000,600000,source_spec('synthetic'),proof(),'SYNTHETIC_TEST'))


def test_periodic_baseline_check_stops(tmp_path):
    s,c=setup(tmp_path);current=proof()
    with Writer(s,lambda:current,c) as w:
        w.heartbeat();current=dict(current,model_hash=digest('changed'))
        with pytest.raises(ValueError,match='BASELINE'):w.heartbeat()
    assert s.status(c())['state']=='INTERRUPTED'
    with pytest.raises(ValueError,match='TERMINAL'):
        with Writer(s,proof,c):pass


def test_gap_idempotence_and_no_event_tail(tmp_path):
    s,c=setup(tmp_path,end=600000)
    with Writer(s,proof,c) as w:
        w.heartbeat();w.gap(300000,310000,'UNKNOWN');w.gap(300000,310000,'UNKNOWN')
        c.at=600000;w.seal()
    gaps=s.status(c())['gaps']
    assert sum(g['expected_start']==300000 and g['observed_resume']==310000 for g in gaps)==1
    assert any(g['type']=='NO_EXPECTED_EVENT' and g['duration_ms']==300000 for g in gaps)


def test_partial_seal_retry_reconciles_new_diagnostic(tmp_path):
    s,c=setup(tmp_path,end=600000)
    with Writer(s,proof,c) as w:
        emit(w,c);c.at=600000;w.end()
    s.path('sealed.json.tmp').write_bytes(b'{partial')
    with Writer(s,proof,c) as w:w.seal()
    assert s.verify(require_sealed=True)['valid']
    assert list(s.folder.glob('*.quarantined'))


def test_same_event_recovers_source_health_without_new_evidence(tmp_path):
    s,c=setup(tmp_path)
    with Writer(s,proof,c) as w:
        emit(w,c);w.source_failure();c.at+=5000
        assert not emit(w,c,source_at=300000)
        w.heartbeat()
    assert s.status(c())['observations']==1 and s.status(c())['source_health']=='OK'


def test_heartbeat_independent_of_slow_source(tmp_path):
    import threading,time
    from btc5_v3.prospective.collector import collect
    s,c=setup(tmp_path);release=threading.Event()
    class Slow:
        def poll(self):
            assert release.wait(5)
            raise ConnectionError('synthetic network failure')
    def sleep(_):
        c.at+=5000
        if c.at>=370000:release.set()
        time.sleep(.002)
    collect(s,proof,clock=c,sleep=sleep,source=Slow(),max_steps=20)
    beats=[e for e in s.events() if e['kind']=='HEARTBEAT']
    assert len(beats)>=3 and beats[1]['at']-beats[0]['at']==30000
    assert s.status(c())['observations']==0


def test_rule_change_interrupts_collector(tmp_path):
    import time
    from btc5_v3.prospective.collector import collect
    from btc5_v3.prospective.sources import RuleChanged
    s,c=setup(tmp_path)
    class Changed:
        def poll(self):raise RuleChanged('RULE_CHANGED')
    def sleep(_):c.at+=1000;time.sleep(.002)
    collect(s,proof,clock=c,sleep=sleep,source=Changed(),max_steps=100)
    assert s.status(c())['state']=='INTERRUPTED'
    assert rows(s.path('registry.sqlite'))[-1]['payload']['reason']=='RULE_CHANGED'


def test_predict_source_pins_rules_get_only():
    from btc5.predictfun import Market
    from btc5_v3.prospective.sources import PredictFun,rule_profile,RuleChanged
    binding=Market(12,300000,600000,True,0,'feed',100,'btc-five-minute')
    raw={'id':12,'description':'fixed rule','marketVariant':'CRYPTO_UP_DOWN','categorySlug':'btc-five-minute',
         'outcomes':[{'indexSet':1,'name':'Up'},{'indexSet':2,'name':'Down'}],'feeRateBps':0}
    category={'startsAt':'1970-01-01T00:05:00Z','endsAt':'1970-01-01T00:10:00Z',
              'variantData':{'priceFeedSymbol':'BTCUSDT','priceFeedProvider':'feed','startPrice':100}}
    class Fake:
        def discover(self,at):return binding,raw,category
        def get(self,path):
            assert path.startswith(('/v1/markets/','/v1/categories/'))
            if path.endswith('/orderbook'):return {'data':{'marketId':12,'updateTimestampMs':300000,'bids':[['.4','10']],'asks':[['.6','10']]}}
            return {'data':category if '/categories/' in path else raw}
    provider=PredictFun(Clock(),rule_profile(binding,raw,category),Fake())
    assert provider.poll()['payload']['quote_type']=='YES_BOOK'
    raw['description']='changed rule'
    with pytest.raises(RuleChanged):provider.poll()


def test_cli_seal_retry_and_status_only(tmp_path,monkeypatch,capsys):
    from btc5_v3.prospective import __main__ as cli
    s,c=sealed(tmp_path);monkeypatch.setattr(cli,'utc_ms',c)
    args=['--project-root',str(tmp_path),'--study','case']
    assert cli.main(args+['seal'])==0
    first=capsys.readouterr().out
    assert cli.main(args+['seal'])==0 and capsys.readouterr().out==first
    assert cli.main(args+['adapter'])==0
    assert 'NOT_REPLAY_READY' in capsys.readouterr().out


def test_manifest_role_rejected_before_payload_read(tmp_path,monkeypatch):
    s,c=sealed(tmp_path)
    p=s.path('manifest.json');m=read(p);m['role']='BLIND';p.write_bytes(canonical(m).encode())
    monkeypatch.setattr(s,'events',lambda:pytest.fail('must not read blind payload'))
    with pytest.raises(ValueError):load_sealed(s,c())


def test_deterministic_demo(tmp_path):
    from btc5_v3.prospective.demo import run_demo
    assert run_demo(tmp_path)==run_demo(tmp_path)
