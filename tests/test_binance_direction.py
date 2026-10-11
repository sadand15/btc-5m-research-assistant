from pathlib import Path
import math
import pytest
from btc5_v3.realtime_dashboard.direction import signal,features_from_rows,BinanceDirection
from btc5_v3.realtime_dashboard.feed import FeedError

@pytest.mark.parametrize('p,expected',[(.9,'UP'),(.7,'UP'),(.5,'WAIT'),(.3,'DOWN'),(.1,'DOWN')])
def test_signal(p,expected):
    assert signal(p,supported=True,remaining_ms=120000)[0]==expected

@pytest.mark.parametrize('p',[float('nan'),float('inf'),-1,2])
def test_invalid_probability(p):
    with pytest.raises(ValueError):signal(p,supported=True,remaining_ms=120000)

def test_support_and_time_gates():
    assert signal(.99,supported=False,remaining_ms=120000)[0]=='WAIT'
    for t in (0,29999,180001):
        assert signal(.99,supported=True,remaining_ms=t)[0]=='WAIT'

def rows():
    asof=1704067200000+179999
    minute=asof//60000*60000
    def candle(t,step):return [t,'100','101','99','100.5','10',t+step-1,'1000',5,'5','500','0']
    return asof,[candle(t,60000) for t in range(minute-95*60000,minute,60000)], [candle(t,1000) for t in range(asof+1-120000,asof+1,1000)]

def test_causal_inputs():
    asof,m,s=rows()
    f,p,o=features_from_rows(m,s,asof)
    assert p==100.5 and o==100 and f['remaining_seconds']==120.0
    assert all(math.isfinite(v) for v in f.values())
    with pytest.raises((ValueError,FeedError)):
        features_from_rows(m,s[:-1],asof)
    with pytest.raises((ValueError,FeedError)):
        features_from_rows(m[:-1],s,asof)
    with pytest.raises((ValueError,FeedError)):
        features_from_rows(m,s,asof-1000)

def test_untrusted_artifact_never_loaded(tmp_path):
    path=tmp_path/'model';path.write_bytes(b'not a model')
    engine=BinanceDirection(None,path)
    assert engine.snapshot()['reason']=='MODEL_HASH_MISMATCH'
    assert engine.predictor is None

def test_exchange_supplied_empty_second_is_not_missing_or_fabricated():
    asof,m,s=rows()
    s[-1][1:6]=['100.5','100.5','100.5','100.5','0']
    s[-1][8:10]=[0,'0']
    assert features_from_rows(m,s,asof)[1]==100.5
    s[-1][5]='1'
    with pytest.raises(ValueError,match='INVALID_EMPTY'):
        features_from_rows(m,s,asof)

def test_prediction_expires_and_cannot_cross_cycle():
    engine=BinanceDirection(None,Path('nonexistent'),clock=lambda:100)
    engine.result=dict(signal='UP',p_up=.8,p_non_up=.2,source_at=99000,cycle_start=0,cycle_end=150000)
    assert engine.snapshot()['signal']=='UP'
    engine.clock=lambda:111
    assert engine.snapshot()['signal']=='WAIT'
    assert engine.snapshot()['p_up'] is None
    engine.clock=lambda:151
    assert engine.snapshot()['signal']=='WAIT'

def test_failed_refresh_removes_previous_prediction():
    class Feed:
        mode='PUBLIC_LIVE'
        def get(self,*a):raise FeedError('CONNECTION_FAILURE')
    engine=BinanceDirection(Feed(),Path('nonexistent'))
    engine.predictor=object()
    engine.result={'signal':'UP'}
    engine.poll()
    assert engine.snapshot()['signal']=='WAIT'
    assert engine.snapshot()['reason']=='CONNECTION_FAILURE'
