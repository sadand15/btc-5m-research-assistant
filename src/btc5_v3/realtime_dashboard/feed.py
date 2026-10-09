"""Credential-free, allowlisted public market data transport."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPRedirectHandler, Request


BASE = 'https://data-api.binance.vision'
MINUTE = 60_000
CYCLE = 300_000


class FeedError(Exception):
    def __init__(self, code, retry_after=0):
        super().__init__(code)
        self.code, self.retry_after = code, retry_after


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise FeedError('REDIRECT_REJECTED')


def timestamp(value):
    if type(value) is not int or value < 0:
        raise FeedError('INVALID_TIMESTAMP')
    return value


def price(value):
    if isinstance(value, bool):
        raise FeedError('INVALID_PRICE')
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise FeedError('INVALID_PRICE') from None
    if not math.isfinite(number) or number <= 0:
        raise FeedError('INVALID_PRICE')
    return number


def parse_trade(raw, received_at):
    try:
        if not isinstance(raw, list) or len(raw) != 1:
            raise FeedError('INVALID_TRADE')
        row = raw[0]
        at = timestamp(row['time'])
        if at > received_at + 2000:
            raise FeedError('CLOCK_SKEW')
        return dict(price=price(row['price']), source_at=at, received_at=received_at,
                    transport_ms=max(0, received_at-at))
    except (KeyError, TypeError, IndexError):
        raise FeedError('INVALID_TRADE') from None


def parse_candles(raw, interval, start, end, closed_before=None):
    if not isinstance(raw, list):
        raise FeedError('INVALID_CANDLES')
    result = {}
    for row in raw:
        try:
            if not isinstance(row, list) or len(row) < 9:
                raise FeedError('INVALID_CANDLES')
            at, close_at = timestamp(row[0]), timestamp(row[6])
            op, high, low, close = (price(row[i]) for i in range(1, 5))
            if (at % interval or close_at != at+interval-1 or not start <= at < end
                    or not low <= min(op, close) <= max(op, close) <= high
                    or type(row[8]) is not int or row[8] <= 0):
                raise FeedError('INVALID_CANDLES')
            if closed_before is not None and close_at >= closed_before:
                raise FeedError('UNFINISHED_CANDLE')
            point = dict(at=close_at, price=close, open=op, start_at=at)
            if at in result:
                raise FeedError('DUPLICATE_CANDLE')
            result[at] = point
        except (KeyError, TypeError, IndexError):
            raise FeedError('INVALID_CANDLES') from None
    return [result[k] for k in sorted(result)]


class PublicFeed:
    mode = 'PUBLIC_LIVE'

    def __init__(self, opener=None, clock=time.time):
        self.opener = opener or build_opener(NoRedirect())
        self.clock = clock
        self.blocked_until = 0
        self.lock = threading.Lock()

    def get(self, path, params):
        # No user-supplied URL, credential or arbitrary endpoint is accepted.
        if path not in ('/api/v3/trades', '/api/v3/klines') or params.get('symbol') != 'BTCUSDT':
            raise FeedError('ENDPOINT_NOT_ALLOWED')
        if set(params) - {'symbol', 'limit', 'interval', 'startTime', 'endTime', 'timeZone'}:
            raise FeedError('PARAMETER_NOT_ALLOWED')
        with self.lock:
            wait = self.blocked_until-self.clock()
        if wait > 0:
            raise FeedError('RATE_LIMIT', wait)
        req = Request(BASE+path+'?'+urlencode(params), method='GET', headers={
            'User-Agent': 'BTC5-Research-Dashboard/1.0', 'Accept': 'application/json'})
        try:
            with self.opener.open(req, timeout=8) as response:
                data = response.read(2_000_001)
                if len(data) > 2_000_000:
                    raise FeedError('RESPONSE_TOO_LARGE')
                return json.loads(data)
        except HTTPError as exc:
            if exc.code in (418, 429):
                value = exc.headers.get('Retry-After', '60')
                try:
                    retry = float(value)
                    if not math.isfinite(retry):
                        retry = 60
                except ValueError:
                    try:
                        retry = parsedate_to_datetime(value).timestamp()-self.clock()
                    except (ValueError, TypeError, OverflowError):
                        retry = 60
                retry = max(60, retry)
                with self.lock:
                    self.blocked_until = max(self.blocked_until, self.clock()+retry)
                raise FeedError('RATE_LIMIT', retry) from None
            raise FeedError('HTTP_'+str(exc.code)) from None
        except (TimeoutError, URLError, OSError):
            raise FeedError('CONNECTION_FAILURE') from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise FeedError('INVALID_JSON') from None

    def trade(self):
        return self.get('/api/v3/trades', dict(symbol='BTCUSDT', limit=1))

    def history(self, now):
        end = now//MINUTE*MINUTE
        start = end-1440*MINUTE
        rows = []
        for page_start in (start, start+1000*MINUTE):
            page_end = min(end, page_start+1000*MINUTE)
            raw = self.get('/api/v3/klines', dict(symbol='BTCUSDT', interval='1m',
                startTime=page_start, endTime=page_end-1, limit=1000, timeZone='0'))
            rows.extend(parse_candles(raw, MINUTE, page_start, page_end, closed_before=end))
        return rows

    def reference(self, start):
        raw = self.get('/api/v3/klines', dict(symbol='BTCUSDT', interval='5m',
            startTime=start, endTime=start+CYCLE-1, limit=1, timeZone='0'))
        rows = parse_candles(raw, CYCLE, start, start+CYCLE)
        if len(rows) != 1 or rows[0]['start_at'] != start:
            raise FeedError('MISSING_REFERENCE')
        return dict(price=rows[0]['open'], at=start)


class SyntheticFeed:
    """Explicit demo only; never selected as a live feed fallback."""
    mode = 'SYNTHETIC_DEMO'

    def __init__(self, clock=time.time):
        self.clock = clock

    def trade(self):
        now = int(self.clock()*1000)
        return [dict(time=now-100, price=80000+100*math.sin(now/100000))]

    def history(self, now):
        end = now//MINUTE*MINUTE
        return [dict(at=t+MINUTE-1, start_at=t, open=80000,
                     price=80000+200*math.sin(t/1200000))
                for t in range(end-1440*MINUTE, end, MINUTE)]

    def reference(self, start):
        return dict(price=80000, at=start)
