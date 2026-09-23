"""Idempotent minute snapshots and UTC aggregation; never fill missing prices."""
from dataclasses import dataclass, asdict
import logging
import time
import requests

LOG = logging.getLogger(__name__)
MINUTE = 60_000
CYCLE = 300_000


@dataclass(frozen=True)
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    buy_volume: float = 0.0
    closed: bool = True
    event_time: int = 0
    timeframe: str = '1m'

    def __post_init__(self):
        import math
        if self.timestamp < 0 or self.timestamp % MINUTE:
            raise ValueError('Candle timestamp must be UTC minute aligned in milliseconds')
        if not all(math.isfinite(v) for v in (self.open, self.high, self.low, self.close, self.volume, self.buy_volume)):
            raise ValueError('Non-finite candle')
        if self.low <= 0 or self.high < max(self.open, self.close, self.low) or self.low > min(self.open, self.close):
            raise ValueError('Invalid OHLC')
        if self.volume < 0 or not 0 <= self.buy_volume <= self.volume + 1e-8:
            raise ValueError('Invalid volume')


class CandleBook:
    def __init__(self):
        self.minutes: dict[int, Candle] = {}

    def update(self, candle: Candle) -> bool:
        old = self.minutes.get(candle.timestamp)
        if old and (old == candle or (old.closed and not candle.closed) or old.event_time > candle.event_time):
            return False
        self.minutes[candle.timestamp] = candle
        return True

    def aggregate(self, start: int, minutes: int) -> Candle | None:
        rows = [self.minutes.get(start + i * MINUTE) for i in range(minutes)]
        available = [r for r in rows if r is not None]
        # Partial bars require a contiguous prefix starting at the real interval open.
        if not available or available[0].timestamp != start:
            return None
        if any(r.timestamp != start + i * MINUTE for i, r in enumerate(available)):
            return None
        return Candle(start, available[0].open, max(r.high for r in available),
                      min(r.low for r in available), available[-1].close,
                      sum(r.volume for r in available), sum(r.buy_volume for r in available),
                      len(available) == minutes and all(r.closed for r in available),
                      max(r.event_time for r in available), f'{minutes}m')

    def prune(self, before: int):
        self.minutes = {t: c for t, c in self.minutes.items() if t >= before}


class Historical:
    def __init__(self, cfg: dict):
        self.url = cfg['data']['rest_url'].rstrip('/')
        self.symbol = cfg['symbol']
        self.session = requests.Session()

    def get(self, endpoint: str, **params):
        for attempt in range(5):
            try:
                response = self.session.get(self.url + endpoint, params=params, timeout=25)
                if response.status_code in (418, 429):
                    time.sleep(min(float(response.headers.get('Retry-After', 5)), 60))
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError):
                if attempt == 4:
                    raise
                time.sleep(min(2 ** attempt, 16))

    def server_time(self) -> int:
        return int(self.get('/api/v3/time')['serverTime'])

    def download(self, start: int, end: int) -> list[Candle]:
        """[start, end), finalized 1m only; derive 5m/15m locally."""
        start = (start + MINUTE - 1) // MINUTE * MINUTE
        result: dict[int, Candle] = {}
        cursor = start
        while cursor + MINUTE <= end:
            raw = self.get('/api/v3/klines', symbol=self.symbol, interval='1m',
                           startTime=cursor, endTime=end - 1, limit=1000)
            if not raw:
                break
            for r in raw:
                t = int(r[0])
                if start <= t and t + MINUTE <= end:
                    result[t] = Candle(t, *map(float, r[1:6]), float(r[9]), True, t + MINUTE)
            next_cursor = int(raw[-1][0]) + MINUTE
            if next_cursor <= cursor:
                raise RuntimeError('REST pagination did not advance')
            cursor = next_cursor
            LOG.info('[DATA] downloaded %s minute bars', len(result))
            time.sleep(0.08)
        return sorted(result.values(), key=lambda c: c.timestamp)


class OrderBook:
    """Top-20 FULL snapshots; no mixing snapshot and diff-depth protocols."""
    def __init__(self):
        self.update_id = -1
        self.received_at = 0
        self.values: dict[str, float] = {}

    def update(self, data: dict, received_at: int) -> bool:
        uid = int(data['lastUpdateId'])
        if uid <= self.update_id:
            return False
        bids, asks = data['bids'], data['asks']
        if len(bids) < 10 or len(asks) < 10:
            return False
        bid, ask = float(bids[0][0]), float(asks[0][0])
        if bid <= 0 or ask < bid:
            return False
        values = {'bid': bid, 'ask': ask, 'spread': ask - bid,
                  'spread_bps': (ask - bid) / ((ask + bid) / 2) * 10000}
        for n in (5, 10):
            bv, av = sum(float(r[1]) for r in bids[:n]), sum(float(r[1]) for r in asks[:n])
            values.update({f'bid_volume_{n}': bv, f'ask_volume_{n}': av,
                           f'depth_{n}': bv + av, f'obi_{n}': (bv - av) / (bv + av) if bv + av else 0})
        self.update_id, self.received_at, self.values = uid, received_at, values
        return True
