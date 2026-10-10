"""Bounded in-memory display cache; no study/evidence writes or prediction calls."""
from collections import deque
from copy import deepcopy
import threading
import time

from .feed import CYCLE, MINUTE, FeedError, parse_trade

STALE_MS = 15_000


def backoff(failures, minimum=5):
    return min(120, minimum*2**min(max(failures-1, 0), 8))


class DashboardService:
    def __init__(self, feed, clock=time.time, monotonic=time.monotonic):
        self.feed, self.clock, self.monotonic = feed, clock, monotonic
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.threads = []
        self.quote = None
        self.quote_monotonic = None
        self.reference = None
        self.history_points = []
        self.history_at = None
        self.history_error = None
        self.health = dict(status='CONNECTING', reason='WAITING_FOR_FEED', last_success_at=None,
            failures=0, next_retry_at=0, request_ms=None, recoveries=0)
        self.events = deque(maxlen=20)

    def now(self):
        return int(self.clock()*1000)

    def transition(self, state, reason):
        if self.health['status'] != state or self.health['reason'] != reason:
            self.events.appendleft(dict(at=self.now(), status=state, reason=reason))
        self.health.update(status=state, reason=reason)

    def poll_quote(self):
        start = self.monotonic()
        try:
            raw = self.feed.trade()
            quote = parse_trade(raw, self.now())
            with self.lock:
                if self.quote and quote['source_at'] < self.quote['source_at']:
                    raise FeedError('OUT_OF_ORDER_QUOTE')
                if self.now()-quote['source_at'] > STALE_MS:
                    raise FeedError('STALE_SOURCE')
                recovered = self.health['status'] in ('DISCONNECTED', 'DELAYED')
                self.quote, self.quote_monotonic = quote, self.monotonic()
                self.health.update(last_success_at=self.now(), failures=0,
                    next_retry_at=self.now()+5000, request_ms=round((self.monotonic()-start)*1000))
                if recovered:
                    self.health['recoveries'] += 1
                self.transition('RECOVERING' if recovered else 'HEALTHY',
                                'FEED_RECOVERED' if recovered else 'FRESH_TRADE')
            return 5
        except FeedError as exc:
            with self.lock:
                self.health['failures'] += 1
                delay = max(backoff(self.health['failures']), exc.retry_after)
                self.health.update(next_retry_at=self.now()+int(delay*1000),
                    request_ms=round((self.monotonic()-start)*1000))
                self.transition('DELAYED' if exc.code in ('STALE_SOURCE', 'CLOCK_SKEW',
                    'OUT_OF_ORDER_QUOTE') else 'DISCONNECTED', exc.code)
            return delay

    def poll_history(self):
        try:
            rows = self.feed.history(self.now())
            with self.lock:
                self.history_points, self.history_at = rows, self.now()
                self.history_error = None
            return True
        except FeedError as exc:
            with self.lock:
                self.history_error = exc.code
            return False

    def poll_reference(self):
        start = self.now()//CYCLE*CYCLE
        with self.lock:
            if self.reference and self.reference['at'] == start:
                return True
        try:
            ref = self.feed.reference(start)
            with self.lock:
                self.reference = dict(ref, received_at=self.now())
            return True
        except FeedError:
            return False

    def snapshot(self):
        with self.lock:
            now = self.now()
            cycle_start = now//CYCLE*CYCLE
            q = deepcopy(self.quote)
            if q:
                elapsed = max(0, int((self.monotonic()-self.quote_monotonic)*1000))
                q['receipt_age_ms'] = max(elapsed, now-q['received_at'])
                q['source_age_ms'] = max(now-q['source_at'], q['transport_ms']+elapsed)
                if now < q['received_at']-2000:
                    self.transition('DELAYED', 'CLOCK_SKEW')
                elif max(q['source_age_ms'], q['receipt_age_ms']) > STALE_MS:
                    if self.health['status'] not in ('DISCONNECTED', 'DELAYED'):
                        self.transition('DELAYED', 'STALE_SOURCE')
            ref = self.reference if self.reference and self.reference['at'] == cycle_start else None
            end = now//MINUTE*MINUTE
            points = [dict(at=p['at'], price=p['price']) for p in self.history_points
                      if end-1440*MINUTE <= p['start_at'] < end]
            error = self.history_error
            if self.history_at is not None and (now-self.history_at > 120_000 or now < self.history_at-2000):
                error = error or 'HISTORY_STALE'
            hist_status = ('ERROR' if error else 'LOADING' if self.history_at is None
                           else 'READY' if len(points) == 1440 else 'PARTIAL')
            return dict(version='1.0', server_at=now, source='Binance Spot', symbol='BTCUSDT',
                mode=self.feed.mode, health=deepcopy(self.health), quote=q,
                live_price=q['price'] if q and self.health['status'] in ('HEALTHY', 'RECOVERING') else None,
                stale_after_ms=STALE_MS,
                cycle=dict(start_at=cycle_start, end_at=cycle_start+CYCLE,
                    remaining_ms=cycle_start+CYCLE-now,
                    reference_price=ref['price'] if ref else None,
                    reference_at=ref['at'] if ref else None,
                    reference_received_at=ref['received_at'] if ref else None,
                    reference_definition='Binance Spot BTCUSDT UTC 5m candle open (first trade)'),
                history=dict(points=points, as_of=self.history_at, status=hist_status,
                    expected=1440, observed=len(points), missing=1440-len(points),
                    coverage=len(points)/1440, error=error),
                research=dict(status='REAL_DATA_NOT_READY', compatibility='TARGET_MISMATCH',
                              prediction_available=False),
                decision=dict(signal='WAIT', state='NOT_EVALUATED',
                    reasons=['REAL_VENUE_BINDING_REQUIRED', 'TARGET_MISMATCH',
                             'PREDICTION_NOT_AVAILABLE'],
                    valid_until=None, p_up=None, p_down=None, p_tie=None,
                    market_id=None, generated_at=None),
                events=list(self.events),
                reports=dict(m92='/reports/m92', m102='/reports/m102', methods='/docs/methods'))

    def _loop(self, task, base):
        failures = 0
        while not self.stop_event.is_set():
            try:
                result = task()
                if type(result) is bool:
                    failures = 0 if result else failures+1
                    delay = base if result else backoff(failures, base)
                else:
                    delay = result
            except Exception:
                # Exception details can contain proxy credentials: retain only a fixed code.
                failures += 1
                delay = backoff(failures, base)
                with self.lock:
                    if task == self.poll_quote:
                        self.transition('DISCONNECTED', 'INTERNAL_FEED_ERROR')
                    elif task == self.poll_history:
                        self.history_error = 'INTERNAL_FEED_ERROR'
            self.stop_event.wait(delay)

    def start(self):
        if self.threads:
            return
        for task, base in ((self.poll_quote, 5), (self.poll_history, 60), (self.poll_reference, 5)):
            thread = threading.Thread(target=self._loop, args=(task, base), daemon=True)
            thread.start()
            self.threads.append(thread)

    def stop(self):
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=0.2)
