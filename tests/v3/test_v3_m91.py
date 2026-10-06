"""M9.1 causal collection regressions; temporary synthetic studies only."""
from dataclasses import replace
import json
import socket
import sqlite3
import pytest

from btc5_v3.encoding import digest, canonical
from btc5_v3.binding_collection.demo import setup, proof, config, complete, MockPredictor, MockSource, Clock
from btc5_v3.binding_collection.schema import definition
from btc5_v3.binding_collection.collector import Collector
from btc5_v3.binding_collection.store import BindingStudy, BindingWriter
from btc5_v3.prospective.store import read
from btc5_v3.research_adapter.binding_dataset import load_binding_synthetic


def feed(c, source):
    c.state(source.state()); c.reference(source.reference()); c.book(source.book())


def finish(study, clock, *, settlement=True):
    with BindingWriter(study,proof,clock) as w:
        c=Collector(w,MockPredictor(config()))
        if settlement:
            clock.at=601000; c.settlement(MockSource(clock).settlement('mock-market'))
        clock.at=900000; index=w.seal()
    return load_binding_synthetic(study,now=clock(),expected_root=index['dataset_root_hash'])


def test_complete_synthetic_ready_and_unchanged_source(tmp_path):
    s,result=complete(tmp_path)
    assert result.readiness=='REPLAY_READY' and result.origin=='SYNTHETIC_TEST'
    before={p.name:p.read_bytes() for p in s.folder.iterdir()}
    assert load_binding_synthetic(s,now=900000,expected_root=result.dataset_root_hash)==result
    assert before=={p.name:p.read_bytes() for p in s.folder.iterdir()}
    r=result.dataset.records()[0]
    assert r['prediction']['available_at'] < r['outcome']['resolution_at'] <= r['outcome']['available_at']
    assert r['binding_provenance']['root']==result.dataset_root_hash
    from btc5_v3.validation.replay import validate
    assert validate(result.dataset,cutoff=900000,code_git='c'*40)['status']=='PASS'


def test_prediction_fields_are_actual_and_bound(tmp_path):
    s,clock,source,model=setup(tmp_path)
    with BindingWriter(s,proof,clock) as w:
        c=Collector(w,model); feed(c,source); p=c.predict('mock-market')
        assert p['generated_at']==clock() and p['available_at']==clock()
        assert p['model_config_hash']==config().model_config_hash
        assert p['config_hash']==config().hash and len(p['input_snapshot_hash'])==64
        assert p['target_horizon_ms']==p['tte_ms']==300000
        assert len([e for e in s.events() if e['kind']=='HEARTBEAT'])==1


def test_missing_settlement_is_not_ready(tmp_path):
    s,t,source,model=setup(tmp_path)
    with BindingWriter(s,proof,t) as w:
        c=Collector(w,model); c.step(source); t.at+=1000; c.step(source)
    r=finish(s,t,settlement=False)
    assert r.readiness=='NOT_READY' and r.reasons==('MISSING_OR_DUPLICATE_SETTLEMENT',)


@pytest.mark.parametrize('kind', ['wrong_market','rule','mapping','missing_definition','unhealthy','changed_definition'])
def test_identity_and_mapping_fail_closed(tmp_path,kind):
    s,t,source,model=setup(tmp_path)
    with BindingWriter(s,proof,t) as w:
        c=Collector(w,model); state=source.state()
        if kind=='wrong_market':
            c.state(state); b=source.book(); b['market_id']='other'
            assert c.book(b)['status']=='REJECTED'; return
        if kind=='rule':state['rule_hash']='wrong'
        if kind=='mapping':state['mapping']={'YES':'UNKNOWN','NO':'DOWN'}
        if kind=='missing_definition':state.pop('definition')
        if kind=='unhealthy':state['source_health']='UNKNOWN'
        if kind=='changed_definition':
            c.state(state); t.at+=1; state=source.state(); state['definition']['condition_id']='changed'
        assert c.state(state)['status']=='REJECTED'
        assert any(e['kind']=='REJECTED' for e in s.events())


@pytest.mark.parametrize('part', ['reference','state','book'])
def test_stale_input_rejects_prediction(tmp_path,part):
    s,t,source,model=setup(tmp_path)
    with BindingWriter(s,proof,t) as w:
        c=Collector(w,model); feed(c,source); t.at+=2001
        if part!='state':c.state(source.state())
        if part!='reference':c.reference(source.reference())
        if part!='book':c.book(source.book())
        assert c.predict('mock-market')['status']=='REJECTED'
        assert model.calls==0


@pytest.mark.parametrize('bad', [[],None,[['NaN','1']],[['.4','0']],[['1','1']],[['.8','1']],[['.4']],[[True,'1']]])
def test_malformed_book_is_retained_as_rejected(tmp_path,bad):
    s,t,source,model=setup(tmp_path)
    with BindingWriter(s,proof,t) as w:
        c=Collector(w,model); c.state(source.state()); b=source.book(); b['yes_bids']=bad
        assert c.book(b)['status']=='REJECTED'
        assert not any(e['kind']=='BOOK' for e in s.events())
        rejected=[e['payload'] for e in s.events() if e['kind']=='REJECTED'][-1]
        assert rejected['safe_payload'] and rejected['payload_hash']==digest(rejected['safe_payload'])


def test_good_book_after_bad_same_ms_is_allowed(tmp_path):
    s,t,source,model=setup(tmp_path)
    with BindingWriter(s,proof,t) as w:
        c=Collector(w,model); c.state(source.state()); c.reference(source.reference())
        b=source.book(); b['yes_bids']=[]; c.book(b)
        c.book(source.book())
        assert 'generated_at' in c.predict('mock-market')


def test_later_bad_book_cannot_fall_back_to_old_book(tmp_path):
    s,t,source,model=setup(tmp_path)
    with BindingWriter(s,proof,t) as w:
        c=Collector(w,model); feed(c,source); b=source.book(); b['yes_bids']=[]; c.book(b)
        assert c.predict('mock-market')['status']=='REJECTED'


def test_predictor_cannot_supply_backdated_timestamp(tmp_path):
    s,t,source,model=setup(tmp_path)
    model.predict=lambda inputs:dict(p_up='.7',p_down='.3',generated_at=100)
    with BindingWriter(s,proof,t) as w:
        c=Collector(w,model); feed(c,source)
        assert c.predict('mock-market')['status']=='REJECTED'
        assert not any(e['kind']=='PREDICTION' for e in s.events())


def test_inference_finishing_after_expiry_rejected(tmp_path):
    s,t,source,model=setup(tmp_path)
    def slow(inputs): t.at=600000; return {'p_up':'.7','p_down':'.3'}
    model.predict=slow
    with BindingWriter(s,proof,t) as w:
        c=Collector(w,model); feed(c,source)
        assert c.predict('mock-market')['status']=='REJECTED'
        assert not any(e['kind']=='PREDICTION' for e in s.events())


@pytest.mark.parametrize('kind',['early','future','wrong_market','wrong_rule','wrong_source'])
def test_settlement_binding_and_order_rejected(tmp_path,kind):
    s,t,source,model=setup(tmp_path)
    with BindingWriter(s,proof,t) as w:
        c=Collector(w,model); c.step(source); t.at=601000
        out=source.settlement('mock-market')
        if kind=='early':out['settled_at']=299999
        if kind=='future':out['settled_at']=t()+1
        if kind=='wrong_market':out['market_id']='other'
        if kind=='wrong_rule':out['rule_hash']='wrong'
        if kind=='wrong_source':out['source']='btc-price-inference'
        assert c.settlement(out)['status']=='REJECTED'
        assert not any(e['kind']=='SETTLEMENT' for e in s.events())


def test_no_prediction_once_market_resolved(tmp_path):
    s,t,source,model=setup(tmp_path)
    with BindingWriter(s,proof,t) as w:
        c=Collector(w,model); feed(c,source)
        state=source.state(); state['status']='RESOLVED'; c.state(state)
        assert c.predict('mock-market')['status']=='REJECTED' and model.calls==0


def test_restart_does_not_regenerate_prediction(tmp_path):
    s,t,source,model=setup(tmp_path)
    with BindingWriter(s,proof,t) as w: Collector(w,model).step(source)
    old=[e for e in s.events() if e['kind']=='PREDICTION'][0]
    t.at+=1000
    with BindingWriter(s,proof,t) as w:
        c=Collector(w,model); assert c.predict('mock-market')==old['payload']
    assert model.calls==1
    assert len([e for e in s.events() if e['kind']=='PREDICTION'])==1


@pytest.mark.parametrize('fault_point',['after_commit','after_segment_rename'])
def test_crash_recovery_chain_and_dedup(tmp_path,fault_point):
    s,t,source,model=setup(tmp_path)
    with BindingWriter(s,proof,t) as w:
        c=Collector(w,model); feed(c,source)
        def fault(where):
            if where==fault_point: raise RuntimeError('synthetic crash')
        w.fault=fault
        with pytest.raises(RuntimeError):
            if fault_point=='after_commit':
                # Crash after Prediction commit, rather than preceding heartbeat.
                original=w._write
                def write(kind,payload,**kwargs):
                    if kind=='HEARTBEAT':
                        w.fault=None
                        try:return original(kind,payload,**kwargs)
                        finally:w.fault=fault
                    return original(kind,payload,**kwargs)
                w._write=write
                c.predict('mock-market')
            else:
                w.fault=None; c.predict('mock-market'); w.fault=fault; w.finalize()
    with BindingWriter(s,proof,t) as w:
        assert Collector(w,model).predict('mock-market')['market_id']=='mock-market'
    assert model.calls==1 and s.verify()['valid']


def test_followup_only_calls_settlement_and_timeout_stops(tmp_path):
    s,t,source,model=setup(tmp_path)
    with BindingWriter(s,proof,t) as w:
        c=Collector(w,model); c.step(source); t.at=601000
        def forbidden(): raise AssertionError('followup touched prediction inputs')
        source.state=source.reference=source.book=forbidden
        assert c.step(source)['phase']=='SETTLEMENT_FOLLOWUP'
        t.at=900000
        assert c.step(source)['phase']=='ENDED'
        with pytest.raises(ValueError):c.settlement({})


def test_seal_requires_fixed_followup_end_and_is_immutable(tmp_path):
    s,t,source,model=setup(tmp_path)
    with BindingWriter(s,proof,t) as w:
        c=Collector(w,model); c.step(source); t.at=600000
        with pytest.raises(ValueError,match='FOLLOWUP'):w.seal()
        t.at=900000; w.seal()
    before={p.name:p.read_bytes() for p in s.folder.iterdir()}
    with pytest.raises(ValueError,match='SEALED'):
        with BindingWriter(s,proof,t):pass
    assert before=={p.name:p.read_bytes() for p in s.folder.iterdir()}


@pytest.mark.parametrize('path',['manifest.json','segment-000001.json','sealed.json','journal-000001.sqlite'])
def test_tampering_refuses_ready(tmp_path,path):
    s,r=complete(tmp_path); s.path(path).write_bytes(b'broken')
    result=load_binding_synthetic(s,now=900000,expected_root=r.dataset_root_hash)
    assert result.readiness=='NOT_READY'


def test_wrong_root_refuses_ready(tmp_path):
    s,r=complete(tmp_path)
    assert load_binding_synthetic(s,now=900000,expected_root='b'*64).readiness=='NOT_READY'


def test_real_origin_and_legacy_namespace_refused(tmp_path):
    with pytest.raises(ValueError):BindingStudy(tmp_path,'prospective-001')
    with pytest.raises(ValueError):
        definition('new','new-data',1,300000,600000,900000,proof(),config(),origin='REALTIME')


def test_append_only_sqlite_and_no_network(tmp_path,monkeypatch):
    def forbidden(*args,**kwargs): raise AssertionError('no network')
    monkeypatch.setattr(socket,'socket',forbidden)
    s,r=complete(tmp_path)
    with sqlite3.connect(s.path('journal-000001.sqlite')) as db:
        with pytest.raises(sqlite3.IntegrityError):db.execute('DELETE FROM events')


def test_source_payload_does_not_persist_credentials(tmp_path):
    s,t,source,model=setup(tmp_path)
    with BindingWriter(s,proof,t) as w:
        c=Collector(w,model); c.state(source.state()); b=source.book()
        b['Authorization']='sensitive-placeholder-not-a-key'; c.book(b)
        assert 'sensitive-placeholder-not-a-key' not in canonical(s.events())


def test_advancing_clock_preserves_generation_and_append_times(tmp_path):
    s,t,source,model=setup(tmp_path)
    class TickingClock:
        at=300000
        def __call__(self): self.at+=1; return self.at
    ticking=TickingClock(); source=MockSource(ticking)
    with BindingWriter(s,proof,ticking) as w:
        c=Collector(w,model); c.step(source)
        ticking.at+=1000; c.step(source)
        p=next(e for e in s.events() if e['kind']=='PREDICTION')
        assert p['payload']['generated_at'] <= p['payload']['available_at'] < p['at'] < 600000
        ticking.at=601000; c.step(source)
        ticking.at=900000; seal=w.seal()
    result=load_binding_synthetic(s,now=ticking(),expected_root=seal['dataset_root_hash'])
    assert result.readiness=='REPLAY_READY'


@pytest.mark.parametrize('reply',[{'p_up':'NaN','p_down':'.3'},{'p_up':'.8','p_down':'.3'},
    {'p_up':'-0.1','p_down':'1.1'},{'p_up':True,'p_down':False},{'p_up':'.7'},
    {'p_up':'.7','p_down':'.3','outcome':'UP'}])
def test_predictor_outputs_fail_closed(tmp_path,reply):
    s,t,source,model=setup(tmp_path); model.predict=lambda inputs:reply
    with BindingWriter(s,proof,t) as w:
        c=Collector(w,model); feed(c,source)
        assert c.predict('mock-market')['status']=='REJECTED'


@pytest.mark.parametrize('change',['model','market'])
def test_post_inference_binding_recheck(tmp_path,change):
    s,t,source,model=setup(tmp_path)
    with BindingWriter(s,proof,t) as w:
        c=Collector(w,model); feed(c,source)
        def changed(inputs):
            if change=='model': model.binding_hash='b'*64
            else:
                state=source.state(); state['status']='RESOLVED'; c.state(state)
            return {'p_up':'.75','p_down':'.25'}
        model.predict=changed
        assert c.predict('mock-market')['status']=='REJECTED'


def test_followup_tracks_markets_even_without_prediction(tmp_path):
    s,t,source,model=setup(tmp_path)
    with BindingWriter(s,proof,t) as w:
        c=Collector(w,model); c.state(source.state()); t.at=601000
        c.step(source)
        assert len([e for e in s.events() if e['kind']=='SETTLEMENT'])==1
        t.at=900000; root=w.seal()['dataset_root_hash']
    assert load_binding_synthetic(s,now=t(),expected_root=root).reasons==('MISSING_OR_DUPLICATE_PREDICTION',)


def test_first_observed_settlement_is_immutable_on_retry(tmp_path):
    s,t,source,model=setup(tmp_path)
    with BindingWriter(s,proof,t) as w:
        c=Collector(w,model); c.step(source); t.at=601000
        first=c.settlement(source.settlement('mock-market')); t.at+=1000
        second=c.settlement(source.settlement('mock-market'))
        assert first==second and second['first_observed_at']==601000
        assert len([e for e in s.events() if e['kind']=='SETTLEMENT'])==1


def test_conflicting_settlement_prevents_ready(tmp_path):
    s,t,source,model=setup(tmp_path)
    with BindingWriter(s,proof,t) as w:
        c=Collector(w,model); c.step(source); t.at+=1000; c.step(source); t.at=601000
        c.settlement(source.settlement('mock-market'))
        conflicting=source.settlement('mock-market'); conflicting['outcome']='DOWN'
        assert c.settlement(conflicting)['status']=='REJECTED'
        t.at=900000; root=w.seal()['dataset_root_hash']
    assert load_binding_synthetic(s,now=t(),expected_root=root).reasons==('SETTLEMENT_REQUIRES_REVIEW',)


def test_hourly_segments_and_missing_cycle_not_ready(tmp_path):
    s=BindingStudy(tmp_path,'long-synthetic')
    s.create(definition('long-synthetic','long-dataset',1,300000,3900000,4200000,proof(),config()))
    s.arm(2,proof()); t=Clock(); source=MockSource(t)
    with BindingWriter(s,proof,t) as w:
        c=Collector(w,MockPredictor(config())); c.state(source.state()); c.reference(source.reference())
        t.at=3600000; c.reference(source.reference())
        assert s.verify()['segments']==1
        t.at=4200000; root=w.seal()['dataset_root_hash']
    assert s.verify(require_sealed=True)['segments']>=2
    assert load_binding_synthetic(s,now=t(),expected_root=root).reasons==('MISSING_MARKET_CYCLE',)


def test_original_namespace_untouched(tmp_path):
    old=tmp_path/'runtime/v3/prospective/prospective-001'
    old.mkdir(parents=True); (old/'sealed.json').write_text('synthetic sentinel')
    complete(tmp_path)
    assert (old/'sealed.json').read_text()=='synthetic sentinel'


def test_followup_deadline_cannot_be_changed(tmp_path):
    s,t,source,model=setup(tmp_path)
    m=s.manifest; m['settlement_followup_end']+=300000
    s.path('manifest.json').write_text(canonical(m))
    with pytest.raises(ValueError):s.verify()


def test_poll_crossing_quote_deadline_does_not_fetch_other_inputs(tmp_path):
    s,t,source,model=setup(tmp_path)
    def state(): t.at=600000; return {}
    def forbidden(): raise AssertionError('input polled during followup')
    source.state=state; source.reference=source.book=forbidden
    with BindingWriter(s,proof,t) as w:
        Collector(w,model).step(source)
        assert not any(e['kind']=='PREDICTION' for e in s.events())
        assert any(e['kind']=='REJECTED' for e in s.events())


def test_source_failure_has_safe_diagnostic_and_no_prediction(tmp_path):
    s,t,source,model=setup(tmp_path)
    def failed(): raise RuntimeError('arbitrary sensitive source error should not be recorded')
    source.reference=failed
    with BindingWriter(s,proof,t) as w:
        Collector(w,model).step(source)
        assert 'arbitrary sensitive' not in canonical(s.events())
        assert not any(e['kind']=='PREDICTION' for e in s.events())
        assert any(e['payload'].get('reason')=='SOURCE_FAILURE' for e in s.events())


def test_settlement_source_outage_can_recover_with_original_window(tmp_path):
    s,t,source,model=setup(tmp_path)
    with BindingWriter(s,proof,t) as w:
        c=Collector(w,model); c.step(source); t.at+=1000; c.step(source); t.at=601000
        original=source.settlement
        def failed(market): raise RuntimeError('transient mock outage')
        source.settlement=failed; c.step(source)
        source.settlement=original; t.at+=1000; c.step(source)
        assert s.status(t())['pending_settlements']==[]
        t.at=900000; root=w.seal()['dataset_root_hash']
    assert load_binding_synthetic(s,now=t(),expected_root=root).readiness=='REPLAY_READY'
