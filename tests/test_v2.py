import asyncio
from copy import deepcopy
from threading import Event
import json
import numpy as np
import pandas as pd
import pytest
from btc5.config import load_config
from btc5.micro import micro_frame,live_micro,MICRO_COLUMNS
from btc5.v2research import split,audit,analyze
from btc5.market import MockQuoteProvider,ReplayQuoteProvider,LiveProvider
from btc5.execution import prepare,execute,fill_sell,adverse_slippage
from btc5.inference import SingleFlight,recheck
from btc5.paper_v2 import simulate
from btc5.database import Database
from btc5.venue import candidate


def seconds(n=120):
    return pd.DataFrame({'timestamp':np.arange(n)*1000,'close':100+np.arange(n)*.1,
                         'volume':np.ones(n),'buy_volume':np.ones(n)*.6})


def test_micro_causal_future_perturbation_and_live_parity():
    s=seconds();original=micro_frame(s)
    changed=s.copy();changed.loc[changed.timestamp>90000,['close','volume','buy_volume']]*=3
    pd.testing.assert_frame_equal(original.iloc[:91],micro_frame(changed).iloc[:91])
    live=live_micro(s.to_dict('records'),90999)
    assert live['return_10s']==pytest.approx(109/108-1)
    assert live==original.iloc[90][MICRO_COLUMNS].to_dict()
    broken=s.drop(index=70)
    with pytest.raises(ValueError,match='GAPPED'):
        live_micro(broken.to_dict('records'),90999)


def test_four_way_partition_cycle_disjoint_and_boundary_reject():
    f=pd.DataFrame([{'cycle_id':c*300000,'timestamp':c*300000+t} for c in range(40) for t in (4999,59999,294999)])
    p=split(f);a=audit(p)
    assert sum(v['cycles'] for v in a.values())==40
    assert all(len(part)%3==0 for part in p.values())
    p['test']=pd.concat([p['test'],p['train'].iloc[:1]])
    with pytest.raises(ValueError,match='leakage'):audit(p)
    bad=f.copy();bad.loc[0,'timestamp']=300000
    with pytest.raises(ValueError):split(bad)


def test_confidence_coverage_and_event_dedupe():
    f=pd.DataFrame({'cycle_id':[0,0,300000,300000],'timestamp':[5,10,300005,300010],
        'label':[1,1,0,0],'distance_standardized':[1,1,-1,-1],
        'distance_percentage':[.01,.01,-.01,-.01],'remaining_seconds':[295,290,295,290]})
    a=analyze(f,np.array([.7,.8,.5,.1]))
    row=next(r for r in a['thresholds'] if r['threshold']==.7)
    assert row['coverage']==.75 and row['trades']==2 and row['samples']==3
    assert row['event_accuracy']==1


def context(at=180000):
    return {'timestamp':at,'cycle_id':0,'cycle_open':100,'distance_remaining_z':0}


def signal(at=180000):
    return {'timestamp':at,'cycle_id':0,'cycle_open':100,'direction':'UP','probability':.9}


def test_mock_is_deterministic_causal_and_marked():
    p=MockQuoteProvider({})
    assert p.quote(180000,context())==p.quote(180000,context())
    assert p.quote(180000,context())['source']=='SIMULATED QUOTE'
    assert p.quote(179999,context()) is None
    assert p.quote(300000,context()) is None


def test_replay_uses_past_receipt_and_rejects_future_source():
    mock=MockQuoteProvider({});a=mock.quote(180000,context());b=mock.quote(180500,context())
    replay=ReplayQuoteProvider([a,b])
    assert replay.quote(179999) is None
    assert replay.quote(180499)['source_at']==180000
    assert replay.quote(180500)['source_at']==180500
    b['source_at']=180501
    with pytest.raises(ValueError):ReplayQuoteProvider([b])


def test_csv_quote_import_roundtrip(tmp_path):
    p=tmp_path/'q.csv';depth={'bids':[[.4,10]],'asks':[[.42,10]]}
    pd.DataFrame([dict(timestamp=180000,bid=.4,ask=.42,depth=json.dumps(depth),fee_bps=200,feed='BINANCE',cycle_open=100)]).to_csv(p,index=False)
    book=ReplayQuoteProvider.from_file(p).quote(180001)
    assert book['best_ask']==.42 and book['market']['start_price']==100


@pytest.mark.parametrize('key',['PREDICTFUN_API_KEY','PREDICT_API_KEY'])
def test_absent_keys_disable_live(monkeypatch,key):
    monkeypatch.delenv('PREDICTFUN_API_KEY',raising=False);monkeypatch.delenv('PREDICT_API_KEY',raising=False)
    assert LiveProvider(load_config()['predictfun']).quote(180000) is None


def test_singleflight_timeout_does_not_release_running_worker():
    async def run():
        gate=Event();errors=[];results=[];flight=SingleFlight(.02)
        def slow():gate.wait(2);return 1
        assert flight.submit(slow,results.append,errors.append)
        assert not flight.submit(lambda:2,results.append,errors.append)
        await asyncio.sleep(.06)
        assert errors==['INFERENCE_TIMEOUT'] and flight.busy and results==[]
        assert not flight.submit(lambda:3,results.append,errors.append)
        gate.set()
        for _ in range(100):
            if not flight.busy:break
            await asyncio.sleep(.005)
        assert not flight.busy and results==[]
        assert flight.submit(lambda:4,results.append,errors.append)
        for _ in range(100):
            if results:break
            await asyncio.sleep(.005)
        assert results==[4];flight.close()
    asyncio.run(run())


def test_recheck_independent_data_ages_cycle_and_remaining():
    cfg=load_config();cfg['freshness']['require_trade_flow']=True
    times={'btc':180000,'orderbook':180000,'trade_flow':180000}
    assert recheck(0,180000,180100,times,cfg) is None
    assert recheck(0,180000,300000,times,cfg)=='CYCLE_CHANGED_DURING_INFERENCE'
    assert recheck(0,180000,180100,{**times,'btc':160000},cfg)=='STALE_BTC'
    assert recheck(0,180000,180100,{**times,'orderbook':0},cfg)=='STALE_ORDERBOOK'
    assert recheck(0,180000,180100,{**times,'trade_flow':160000},cfg)=='STALE_TRADE_FLOW'
    assert recheck(0,294000,294100,{k:294000 for k in times},cfg)=='TIME_FILTER_AFTER_INFERENCE'


def test_spread_guard_fixed_volatility_and_bid_exit():
    cfg=load_config()['predictfun'];p=MockQuoteProvider({'mock_spread':.1})
    assert prepare(signal(),p.quote(180000,context()),cfg)[1]=='PREDICTION_SPREAD_TOO_WIDE'
    assert adverse_slippage(.5,{**cfg,'fixed_slippage_bps':10})==pytest.approx(.5005)
    assert adverse_slippage(.5,{**cfg,'slippage_model':'volatility'},.001)==pytest.approx(.5005)
    book=MockQuoteProvider({}).quote(180000,context())
    fill=fill_sell(book,'UP',5,.01,cfg)
    assert fill['gross_proceeds']==pytest.approx(book['best_bid']*5)
    assert fill['net_proceeds']<fill['gross_proceeds']


def test_quote_recheck_during_inference_changed_market_and_stale():
    cfg=load_config()['predictfun'];p=MockQuoteProvider({})
    order,_=prepare(signal(),p.quote(180000,context()),cfg)
    old=p.quote(180000,context());old['received_at']=180600
    assert execute(order,old,cfg)[1]=='NO_POST_LATENCY_BOOK'
    wrong=p.quote(180600,context());wrong['market_id']=10
    assert execute(order,wrong,cfg)[1]=='WRONG_MARKET'
    moved=p.quote(180600,context());moved['up_asks']=[[.99,100]]
    fill,status=execute(order,moved,cfg)
    assert status=='UNFILLED' and fill['spent_usdt']==0


def paper_frame():
    return pd.DataFrame([dict(timestamp=t,cycle_id=0,price=100,label=1,outcome='UP',probability=.9,
        remaining_seconds=(300000-t)/1000,volatility=.001,trend_15m=.01,momentum_5m=1,momentum_1m=1,
        distance_percentage=0.,distance_remaining_z=0.) for t in (180000,185000,190000)])


def test_paper_replay_determinism_dedupe_and_restart(tmp_path):
    cfg=load_config();p=MockQuoteProvider({});policy=cfg['predictfun']
    a=simulate(paper_frame(),p,cfg,policy);b=simulate(paper_frame(),p,cfg,policy)
    assert a==b and a['total_trades']==1
    db=Database(str(tmp_path/'db'))
    simulate(paper_frame(),p,cfg,policy,db,'run1');db.close()
    db=Database(str(tmp_path/'db'))
    assert db.conn.execute('SELECT count(*) FROM paper_positions_v2').fetchone()[0]==1
    assert db.conn.execute('SELECT fill FROM paper_positions_v2').fetchone()[0] is not None
    with pytest.raises(ValueError,match='already'):simulate(paper_frame(),p,cfg,policy,db,'run1')
    db.close()


def test_real_quote_cannot_be_settled_by_btc_label():
    cfg=load_config();m=MockQuoteProvider({})
    p=ReplayQuoteProvider([m.quote(t,context()) for t in (180000,180500,185000)])
    r=simulate(paper_frame(),p,cfg,cfg['predictfun'])
    assert r['total_trades']==1 and r['net_pnl'] is None and r['pending_settlement']==1


def test_rejected_live_inference_cannot_become_venue_candidate():
    pred={'decision':'WAIT','timestamp':180000,'cycle_id':0}
    assert candidate(pred,180100,load_config()) is None


def test_test_labels_cannot_choose_calibration_or_change_fitted_models():
    from btc5.v2research import fit_suite
    rng=np.random.default_rng(10)
    f=pd.DataFrame([{'cycle_id':c*300000,'timestamp':c*300000+t,'label':c%2,
        'outcome':'UP' if c%2 else 'DOWN','price':100.,'distance_percentage':rng.normal(0,.001),
        'distance_standardized':rng.normal(),'distance_remaining_z':rng.normal(),
        'remaining_seconds':(300000-t)/1000} for c in range(80) for t in (60000,120000,180000)])
    parts=split(f);cfg=load_config();cfg['model'].update(n_estimators=3,num_leaves=3,min_child_samples=5)
    ps,ca,_=fit_suite(parts,cfg,False)
    changed=deepcopy(parts);changed['test']['label']=1-changed['test']['label']
    other,cb,_=fit_suite(changed,cfg,False)
    assert {k:v['chosen_calibration'] for k,v in ca.items()}=={k:v['chosen_calibration'] for k,v in cb.items()}
    for name in ps:np.testing.assert_array_equal(ps[name],other[name])
