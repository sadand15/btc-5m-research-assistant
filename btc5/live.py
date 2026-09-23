import asyncio
import json
import logging
import random
import time
from websockets.asyncio.client import connect
from btc5.data import Candle, CandleBook, Historical, OrderBook, MINUTE, CYCLE
from btc5.features import compute
from btc5.research import Predictor
from btc5.strategy import PaperEngine, decide

LOG = logging.getLogger(__name__)


class LiveEngine:
    def __init__(self, cfg, db, predictor: Predictor):
        self.cfg, self.db, self.predictor = cfg, db, predictor
        self.history = Historical(cfg)
        self.book, self.depth = CandleBook(), OrderBook()
        self.paper = PaperEngine(db, cfg)
        self.offset_ms = 0
        self.last_prediction = 0
        self.last_repair = 0
        self.last_event = 0

    def now(self):
        return int(time.time() * 1000 + self.offset_ms)

    async def repair(self):
        before = time.time() * 1000
        server = await asyncio.to_thread(self.history.server_time)
        after = time.time() * 1000
        self.offset_ms = server - (before + after) / 2
        now = self.now()
        existing = max(self.book.minutes, default=now - self.cfg['data']['warmup_minutes'] * MINUTE)
        pending = self.db.conn.execute("SELECT MIN(cycle_id) FROM trades WHERE result='PENDING'").fetchone()[0]
        start = min(existing - 2 * MINUTE, pending if pending is not None else existing)
        warm_start = now // MINUTE * MINUTE - self.cfg['data']['warmup_minutes'] * MINUTE
        missing = [t for t in range(warm_start, now // MINUTE * MINUTE, MINUTE) if t not in self.book.minutes]
        if missing:
            start = min(start, missing[0])
        rows = await asyncio.to_thread(self.history.download, start, now // MINUTE * MINUTE)
        self.db.import_minutes(rows)
        for c in rows:
            self.book.update(c)
        for cycle in sorted({c.timestamp // CYCLE * CYCLE for c in rows}):
            c = self.book.aggregate(cycle, 5)
            if c and c.closed:
                for result in self.paper.settle(c):
                    LOG.info('[RESULT] recovered %s', result)
        self.last_repair = self.now()
        self.db.state(clock_offset_ms=self.offset_ms, last_repair=self.last_repair)

    async def run(self):
        for c in self.db.read_minutes(self.now() - self.cfg['data']['warmup_minutes'] * MINUTE):
            self.book.update(c)
        delay = 1.0
        symbol = self.cfg['symbol'].lower()
        url = self.cfg['data']['websocket_url'].rstrip('/') + f'/stream?streams={symbol}@kline_1m/{symbol}@depth20@100ms'
        while True:
            try:
                self.db.state(connection='SYNCING', heartbeat=self.now())
                await self.repair()
                # Reset snapshot sequence at each new connection.
                self.depth = OrderBook()
                async with connect(url, ping_interval=20, ping_timeout=20, open_timeout=20, max_queue=64) as ws:
                    LOG.info('[DATA] BTC websocket connected')
                    self.db.state(connection='CONNECTED', heartbeat=self.now())
                    # Allow the new socket one stale window to deliver its first kline;
                    # a depth packet arriving first must not trigger a reconnect loop.
                    self.last_event = self.now()
                    delay = 1.0
                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=self.cfg['data']['stale_seconds'] + 5)
                        packet = json.loads(raw)
                        data = packet.get('data', packet)
                        stream = packet.get('stream', '')
                        if data.get('e') == 'serverShutdown':
                            raise ConnectionError('Exchange requested reconnect')
                        if 'lastUpdateId' in data:
                            self.depth.update(data, self.now())
                        elif 'kline' in stream or data.get('e') == 'kline':
                            self.handle_kline(data)
                        if self.now() - self.last_repair > MINUTE:
                            await self.repair()
                        if self.last_event and self.now() - self.last_event > self.cfg['data']['stale_seconds'] * 1000:
                            raise ConnectionError('Price stream stale despite other stream activity')
            except asyncio.CancelledError:
                self.db.state(connection='STOPPED', heartbeat=self.now())
                raise
            except Exception as exc:
                LOG.exception('[DATA] disconnected; reconnecting in %.1fs: %s', delay, exc)
                self.db.state(connection='DISCONNECTED', error=str(exc), heartbeat=self.now(), decision='WAIT', reason='STALE_DATA')
                await asyncio.sleep(delay + random.random())
                delay = min(delay * 2, self.cfg['data']['reconnect_max_seconds'])

    def handle_kline(self, data: dict):
        k = data['k']
        event = int(data['E'])
        c = Candle(int(k['t']), float(k['o']), float(k['h']), float(k['l']), float(k['c']),
                   float(k['v']), float(k['V']), bool(k['x']), event)
        if not self.book.update(c):
            return
        self.last_event = max(self.last_event, event)
        derived = [c]
        for n in (5, 15):
            aggregate = self.book.aggregate(c.timestamp // (n * MINUTE) * n * MINUTE, n)
            if aggregate:
                derived.append(aggregate)
                if n == 5:
                    for result in self.paper.settle(aggregate):
                        LOG.info('[RESULT] %s', result)
        self.db.candles(derived)
        if c.closed:
            LOG.info('[CANDLE] new finalized 1m candle %s', c.timestamp)
        now = self.now()
        # Do not enter a cycle after its end, or replay old snapshots as live signals.
        asof = min(event, c.timestamp + MINUTE - 1)
        cycle = c.timestamp // CYCLE * CYCLE
        fresh = (0 <= now - event <= self.cfg['data']['stale_seconds'] * 1000
                 and cycle <= now < cycle + CYCLE)
        if asof - self.last_prediction < self.cfg['data']['prediction_interval_seconds'] * 1000:
            return
        self.last_prediction = asof
        opening = self.book.minutes.get(cycle)
        if not opening:
            self.db.state(decision='WAIT', reason='MISSING_CYCLE_OPEN', heartbeat=now)
            return
        try:
            history = sorted(self.book.minutes.values(), key=lambda x: x.timestamp)
            features = compute(history, c, asof, opening.open)
            probability = self.predictor.predict(features, c.close, asof)
        except ValueError as exc:
            self.db.state(decision='WAIT', reason=str(exc), heartbeat=now)
            LOG.warning('[FEATURE] %s', exc)
            return
        support = self.predictor.supported(features['elapsed_seconds'], self.cfg['entry']['support_tolerance_seconds'])
        depth = self.depth.values if now - self.depth.received_at <= self.cfg['data']['book_stale_seconds'] * 1000 else None
        side, reason = decide(probability, features, depth, self.cfg, support, fresh)
        # Save the observed book with each signal without pretending it was in training.
        snapshot = {**features, 'orderbook': depth}
        entered = self.paper.enter(asof, cycle, side, c.close,
                                   probability if side == 'UP' else 1 - probability, snapshot, self.predictor.version)
        decision = f'SIM BUY {side}' if entered else 'WAIT'
        if side != 'WAIT' and not entered:
            reason = 'ALREADY_ENTERED_OR_DISABLED'
        self.db.prediction(asof, cycle, c.close, probability, snapshot, self.predictor.version, decision, reason, support)
        self.db.state(connection='CONNECTED', heartbeat=now, event_time=event, price=c.close,
            cycle_id=cycle, cycle_open=opening.open, features=features, orderbook=depth,
            up_probability=probability, model_version=self.predictor.version,
            supported=support, decision=decision, reason=reason)
        LOG.info('[FEATURE] updated | [MODEL] UP %.3f DOWN %.3f | [ENTRY] %s %s', probability, 1-probability, decision, reason)
        if entered:
            LOG.info('[TRADE] %s cycle=%s', decision, cycle)
        self.book.prune(c.timestamp - self.cfg['data']['warmup_minutes'] * MINUTE)
