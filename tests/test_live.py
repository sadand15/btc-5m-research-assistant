from dataclasses import replace
import asyncio
import json
import pytest
from btc5.config import load_config
from btc5.data import Candle, MINUTE, CYCLE
from btc5.database import Database
from btc5.live import LiveEngine


class FixedPredictor:
    version = 'TEST_ONLY'

    def predict(self, features, price, timestamp):
        return .9

    def supported(self, elapsed, tolerance):
        return True


def event(c, timestamp):
    return {'E': timestamp, 'k': {'t': c.timestamp, 'o': str(c.open), 'h': str(c.high),
        'l': str(c.low), 'c': str(c.close), 'v': str(c.volume), 'V': str(c.buy_volume), 'x': c.closed}}


def setup(tmp_path):
    cfg = load_config()
    cfg['paper_trading']['execution_mode']='legacy'
    cfg['storage']['database'] = str(tmp_path / 'live.db')
    cfg['entry'].update(require_book=False, min_volatility=0)
    db = Database(cfg['storage']['database'])
    engine = LiveEngine(cfg, db, FixedPredictor())
    for i in range(122):
        engine.book.update(Candle(i*MINUTE, 100+i, 102+i, 99+i, 101+i, 10, 5, True, (i+1)*MINUTE))
    return cfg, db, engine


def test_live_snapshot_entry_dedupe_stale_and_final_settlement(tmp_path):
    cfg, db, engine = setup(tmp_path)
    c = Candle(122*MINUTE, 222, 224, 221, 223, 10, 5, False, 0)
    at = c.timestamp + 59000
    engine.now = lambda: at + 50
    engine.handle_kline(event(c, at))
    assert db.conn.execute('SELECT count(*) FROM trades').fetchone()[0] == 1
    engine.handle_kline(event(c, at))
    assert db.conn.execute('SELECT count(*) FROM predictions').fetchone()[0] == 1
    engine.now = lambda: at + 60000
    engine.handle_kline(event(replace(c, closed=True), at+999))
    assert db.conn.execute('SELECT count(*) FROM trades').fetchone()[0] == 1
    for i in (123, 124):
        bar = Candle(i*MINUTE, 100+i, 102+i, 99+i, 101+i, 10, 5, True, 0)
        engine.now = lambda i=i: (i+1)*MINUTE+100
        engine.handle_kline(event(bar, (i+1)*MINUTE+5))
    assert db.conn.execute('SELECT result FROM trades').fetchone()[0] == 'WIN'
    latest = db.conn.execute('SELECT features FROM predictions ORDER BY timestamp DESC LIMIT 1').fetchone()[0]
    assert 'orderbook' in json.loads(latest)
    db.close()


def test_repair_fetches_older_warmup_gap_and_settles_pending(tmp_path):
    cfg, db, engine = setup(tmp_path)
    del engine.book.minutes[30*MINUTE]
    assert engine.paper.enter(23*MINUTE, 20*MINUTE, 'UP', 124, .9,
                              {'remaining_seconds': 120}, 'TEST_ONLY')
    class Source:
        def server_time(self):
            return 122*MINUTE+10000

        def download(self, start, end):
            assert start <= 30*MINUTE
            return [Candle(i*MINUTE, 100+i, 102+i, 99+i, 101+i, 10, 5, True, (i+1)*MINUTE)
                    for i in range(start//MINUTE, end//MINUTE)]
    engine.history = Source()
    asyncio.run(engine.repair())
    assert 30*MINUTE in engine.book.minutes
    assert db.conn.execute('SELECT result FROM trades').fetchone()[0] == 'WIN'
    db.close()


def test_websocket_reconnect_after_failure(tmp_path, monkeypatch):
    import btc5.live as module
    _, db, engine = setup(tmp_path)
    calls = []
    async def repair():
        calls.append('repair')
    engine.repair = repair
    class Connection:
        async def __aenter__(self):
            if calls.count('connect') == 1:
                raise ConnectionError('test disconnect')
            raise asyncio.CancelledError()
        async def __aexit__(self, *args):
            pass
    def connect(*args, **kwargs):
        calls.append('connect')
        return Connection()
    async def sleep(seconds):
        calls.append('backoff')
    monkeypatch.setattr(module, 'connect', connect)
    monkeypatch.setattr(module.asyncio, 'sleep', sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(engine.run())
    assert calls == ['repair', 'connect', 'backoff', 'repair', 'connect']
    assert json.loads(db.conn.execute("SELECT value FROM state WHERE key='connection'").fetchone()[0]) == 'STOPPED'
    db.close()
