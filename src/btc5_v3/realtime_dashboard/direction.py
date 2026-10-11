"""Read-only frozen Binance model adapter; no venue, ledger, or order integration."""
import hashlib
import io
import math
from pathlib import Path
import threading
import time

from .feed import CYCLE, MINUTE, FeedError, parse_candles

MODEL_HASH = '5b4a46e5394c095848cc3191b9f1f8cb4de7366fc1ed496c88baf0561ce6749f'
MODEL_VERSION = 'v2-9e452c59ebf7'


def signal(probability, *, supported, remaining_ms):
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError('INVALID_PROBABILITY')
    if not supported:
        return 'WAIT', 'OUTSIDE_TRAINED_TIME_SUPPORT'
    if not 30000 <= remaining_ms <= 180000:
        return 'WAIT', 'OUTSIDE_RESEARCH_TTE'
    if probability >= .70:
        return 'UP', 'UP_PROBABILITY_AT_LEAST_70_PERCENT'
    if probability <= .30:
        return 'DOWN', 'NON_UP_PROBABILITY_AT_LEAST_70_PERCENT'
    return 'WAIT', 'PROBABILITY_BELOW_DISPLAY_THRESHOLD'


def features_from_rows(minutes, seconds, asof):
    from btc5.data import Candle
    from btc5.features import compute
    from btc5.micro import live_micro
    minute = asof // MINUTE * MINUTE
    cycle = asof // CYCLE * CYCLE
    def parse(rows, interval, start, end):
        parse_candles(rows, interval, start, end, closed_before=asof+1, allow_empty=True)
        values = []
        for r in sorted(rows, key=lambda r:r[0]):
            volume, buy = float(r[5]), float(r[9])
            if not math.isfinite(volume) or not math.isfinite(buy) or not 0 <= buy <= volume:
                raise ValueError('INVALID_VOLUME')
            if r[8]==0 and (volume!=0 or buy!=0 or len({float(r[i]) for i in (1,2,3,4)})!=1):
                raise ValueError('INVALID_EMPTY_CANDLE')
            values.append(dict(timestamp=r[0],open=float(r[1]),high=float(r[2]),low=float(r[3]),
                               close=float(r[4]),volume=volume,buy_volume=buy))
        return values
    m = parse(minutes, MINUTE, minute-95*MINUTE, minute)
    s = parse(seconds, 1000, asof+1-120000, asof+1)
    if len(s)!=120 or any(x['timestamp']!=asof+1-120000+i*1000 for i,x in enumerate(s)):
        raise ValueError('MISSING_SECONDS')
    current = [x for x in s if x['timestamp'] >= minute]
    if not current or current[0]['timestamp'] != minute:
        raise ValueError('MISSING_CURRENT_MINUTE')
    c = Candle(minute,current[0]['open'],max(x['high'] for x in current),min(x['low'] for x in current),
               current[-1]['close'],sum(x['volume'] for x in current),sum(x['buy_volume'] for x in current),False,asof)
    history=[Candle(**x) for x in m]
    opening=c.open if cycle==minute else next((x['open'] for x in m if x['timestamp']==cycle),None)
    if opening is None:
        raise ValueError('MISSING_CYCLE_OPEN')
    f=compute(history,c,asof,opening)
    f.update(live_micro(s,asof))
    return f,c.close,opening


class BinanceDirection:
    def __init__(self, feed, model_path, clock=time.time):
        self.feed,self.clock=feed,clock
        self.lock=threading.Lock()
        self.result=None
        self.reason='MODEL_UNAVAILABLE'
        self.predictor=None
        try:
            data=Path(model_path).read_bytes()
            if hashlib.sha256(data).hexdigest()!=MODEL_HASH:
                self.reason='MODEL_HASH_MISMATCH'
                return
            import joblib
            from btc5.research import Predictor
            from btc5.features import FEATURE_SCHEMA
            artifact=joblib.load(io.BytesIO(data))
            if artifact['version']!=MODEL_VERSION or artifact['schema']!=FEATURE_SCHEMA or artifact['symbol']!='BTCUSDT':
                self.reason='MODEL_CONTRACT_MISMATCH'
                return
            self.predictor=Predictor.__new__(Predictor)
            self.predictor.artifact=artifact
            self.reason='WARMUP'
        except Exception:
            self.reason='MODEL_LOAD_FAILED'

    def now(self):
        return int(self.clock()*1000)

    def poll(self):
        if self.predictor is None or self.feed.mode!='PUBLIC_LIVE':
            return 30
        try:
            asof=self.now()//1000*1000-1
            minute=asof//MINUTE*MINUTE
            minutes=self.feed.get('/api/v3/klines',dict(symbol='BTCUSDT',interval='1m',
                         startTime=minute-95*MINUTE,endTime=minute-1,limit=95,timeZone='0'))
            seconds=self.feed.get('/api/v3/klines',dict(symbol='BTCUSDT',interval='1s',
                         startTime=asof+1-120000,endTime=asof,limit=120,timeZone='0'))
            received=self.now()
            if not 0<=received-asof<=10000:
                raise ValueError('STALE_MODEL_INPUT')
            f,price,opening=features_from_rows(minutes,seconds,asof)
            probability=self.predictor.predict(f,price,asof)
            generated=self.now()
            start=asof//CYCLE*CYCLE
            if generated>=start+CYCLE or not 0<=generated-asof<=10000:
                raise ValueError('CYCLE_CHANGED_OR_INPUT_STALE')
            supported=self.predictor.supported(f['elapsed_seconds'],4)
            side,reason=signal(probability,supported=supported,remaining_ms=start+CYCLE-generated)
            result=dict(signal=side,reason=reason,p_up=probability,p_non_up=1-probability,
                        model_version=MODEL_VERSION,model_hash=MODEL_HASH,source_at=asof,
                        received_at=received,generated_at=generated,cycle_start=start,cycle_end=start+CYCLE,
                        price=price,cycle_open=opening,supported=supported,
                        calibration='FROZEN_MODEL_CALIBRATION_NOT_CURRENT_ACCURACY',
                        target='BINANCE_SPOT_BTCUSDT_UTC_5M_CLOSE_GT_OPEN',down_includes_tie=True)
            with self.lock:
                self.result=result
                self.reason=reason
            return 5
        except Exception as exc:
            reason=exc.code if isinstance(exc,FeedError) else 'MODEL_INPUT_OR_INFERENCE_FAILURE'
            with self.lock:
                self.result=None
                self.reason=reason
            return max(10,exc.retry_after) if isinstance(exc,FeedError) else 10

    def snapshot(self):
        with self.lock:
            if not self.result:
                return dict(signal='WAIT',reason=self.reason,p_up=None,p_non_up=None)
            r=dict(self.result)
        now=self.now()
        if not r['cycle_start']<=now<r['cycle_end'] or not 0<=now-r['source_at']<=10000:
            r.update(signal='WAIT',reason='PREDICTION_STALE_OR_CYCLE_CHANGED',p_up=None,p_non_up=None)
        elif not 30000<=r['cycle_end']-now<=180000:
            r.update(signal='WAIT',reason='OUTSIDE_RESEARCH_TTE')
        return r
