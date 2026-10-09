"""Public Dashboard contracts exercised without venue or external network calls."""
from copy import deepcopy
from email.message import Message
from email.utils import formatdate
from http.client import HTTPConnection
from io import BytesIO
import json
from pathlib import Path
import threading
from urllib.error import HTTPError, URLError

import pytest

from btc5_v3.realtime_dashboard.feed import (
    BASE, CYCLE, MINUTE, FeedError, NoRedirect, PublicFeed, SyntheticFeed,
    parse_candles, parse_trade, price, timestamp,
)
from btc5_v3.realtime_dashboard.service import DashboardService, backoff
from btc5_v3.realtime_dashboard.server import make_server, offline_report


class Clock:
    wall = 1_800_000_000.0
    monotonic = 1000.0

    def advance(self, seconds):
        self.wall += seconds
        self.monotonic += seconds


class FakeOpener:
    def __init__(self, result=b'[]', error=None):
        self.result, self.error, self.calls = result, error, []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.error:
            raise self.error
        return BytesIO(self.result)


def candle(at, interval=MINUTE):
    return [at, '100', '102', '99', '101', '1', at+interval-1, '100', 2]


def service():
    clock = Clock()
    feed = SyntheticFeed(clock=lambda: clock.wall)
    return DashboardService(feed, clock=lambda: clock.wall,
                            monotonic=lambda: clock.monotonic), clock


@pytest.mark.parametrize('value', [True, -1, 1.0, '100', None])
def test_timestamp_rejects_ambiguous_values(value):
    with pytest.raises(FeedError, match='INVALID_TIMESTAMP'):
        timestamp(value)


@pytest.mark.parametrize('value', [True, 0, -1, 'NaN', 'inf', '-inf', None, 'bad'])
def test_price_rejects_nonfinite_nonpositive_values(value):
    with pytest.raises(FeedError, match='INVALID_PRICE'):
        price(value)


@pytest.mark.parametrize('raw', [None, {}, [], [{}, {}], [{}], ['bad']])
def test_malformed_trade_rejected(raw):
    with pytest.raises(FeedError):
        parse_trade(raw, 10000)


def test_trade_timestamp_price_latency_and_no_mutation():
    raw = [dict(time=9900, price='123.5')]
    saved = deepcopy(raw)
    assert parse_trade(raw, 10000) == dict(price=123.5, source_at=9900,
                                         received_at=10000, transport_ms=100)
    assert raw == saved
    with pytest.raises(FeedError, match='CLOCK_SKEW'):
        parse_trade([dict(time=12001, price=100)], 10000)


def test_transport_only_allowlisted_get_without_credentials(monkeypatch):
    monkeypatch.setenv('PREDICT_FUN_API_KEY', 'synthetic-unused-value')
    opener = FakeOpener(b'[{"time":1,"price":"100"}]')
    feed = PublicFeed(opener=opener)
    feed.trade()
    request, timeout = opener.calls[0]
    assert request.get_method() == 'GET'
    assert request.full_url == BASE+'/api/v3/trades?symbol=BTCUSDT&limit=1'
    assert timeout == 8
    assert set(k.lower() for k, _ in request.header_items()) == {'user-agent', 'accept'}
    assert request.data is None
    assert 'synthetic-unused-value' not in repr(request.__dict__)


@pytest.mark.parametrize('path,params', [
    ('/api/v3/order', {'symbol': 'BTCUSDT'}),
    ('/api/v3/account', {'symbol': 'BTCUSDT'}),
    ('https://example.invalid/api/v3/trades', {'symbol': 'BTCUSDT'}),
    ('/api/v3/trades', {'symbol': 'ETHUSDT'}),
    ('/api/v3/trades', {'symbol': 'BTCUSDT', 'apiKey': 'synthetic'}),
])
def test_forbidden_requests_fail_before_transport(path, params):
    opener = FakeOpener()
    with pytest.raises(FeedError):
        PublicFeed(opener=opener).get(path, params)
    assert not opener.calls


def test_redirect_rejected():
    with pytest.raises(FeedError, match='REDIRECT_REJECTED'):
        NoRedirect().redirect_request(None, None, 302, None, None, 'https://example.invalid')


@pytest.mark.parametrize('retry,expected', [('180', 180), ('1', 60), ('NaN', 60), ('bad', 60)])
def test_429_enforces_shared_endpoint_cooldown(retry, expected):
    clock = Clock()
    headers = Message()
    headers['Retry-After'] = retry
    opener = FakeOpener(error=HTTPError(BASE, 429, 'rate limit', headers, None))
    feed = PublicFeed(opener=opener, clock=lambda: clock.wall)
    with pytest.raises(FeedError) as first:
        feed.trade()
    assert first.value.retry_after == expected
    with pytest.raises(FeedError, match='RATE_LIMIT'):
        feed.reference(0)
    assert len(opener.calls) == 1
    clock.advance(expected)
    opener.error = None
    assert feed.trade() == []
    assert len(opener.calls) == 2


def test_rate_limit_http_date_and_server_failure_codes():
    clock = Clock()
    headers = Message()
    headers['Retry-After'] = formatdate(clock.wall+180, usegmt=True)
    for status in (418, 429):
        opener = FakeOpener(error=HTTPError(BASE, status, 'ignored', headers, None))
        with pytest.raises(FeedError) as exc:
            PublicFeed(opener=opener, clock=lambda: clock.wall).trade()
        assert exc.value.code == 'RATE_LIMIT'
        assert exc.value.retry_after == 180
    with pytest.raises(FeedError, match='HTTP_503'):
        PublicFeed(opener=FakeOpener(error=HTTPError(BASE, 503, 'ignored', headers, None))).trade()


@pytest.mark.parametrize('payload,code', [(b'not json', 'INVALID_JSON'),
                                        (b'\xff', 'INVALID_JSON'),
                                        (b'x'*2_000_001, 'RESPONSE_TOO_LARGE')],
                         ids=['malformed-json', 'invalid-unicode', 'oversized-response'])
def test_transport_response_fail_closed(payload, code):
    with pytest.raises(FeedError, match=code):
        PublicFeed(opener=FakeOpener(payload)).trade()


def test_transport_error_does_not_expose_details():
    with pytest.raises(FeedError) as exc:
        PublicFeed(opener=FakeOpener(error=URLError('private proxy detail'))).trade()
    assert str(exc.value) == 'CONNECTION_FAILURE'


def test_history_gap_preserved_and_ordering_deterministic():
    raw = [candle(2*MINUTE), candle(0)]
    saved = deepcopy(raw)
    rows = parse_candles(raw, MINUTE, 0, 3*MINUTE, closed_before=3*MINUTE)
    assert [r['start_at'] for r in rows] == [0, 2*MINUTE]
    assert raw == saved


@pytest.mark.parametrize('field,value', [(0, 1), (1, 'NaN'), (2, '99'), (3, '103'),
                                        (4, 'inf'), (6, MINUTE), (8, 0), (8, True)])
def test_malformed_ohlc_or_time_rejected(field, value):
    row = candle(0)
    row[field] = value
    with pytest.raises(FeedError):
        parse_candles([row], MINUTE, 0, MINUTE)


def test_duplicate_and_unclosed_candles_rejected():
    with pytest.raises(FeedError, match='DUPLICATE_CANDLE'):
        parse_candles([candle(0), candle(0)], MINUTE, 0, MINUTE)
    with pytest.raises(FeedError, match='UNFINISHED_CANDLE'):
        parse_candles([candle(0)], MINUTE, 0, MINUTE, closed_before=MINUTE-1)


def test_reference_uses_current_cycle_open_not_current_close():
    opener = FakeOpener(json.dumps([candle(0, CYCLE)]).encode())
    assert PublicFeed(opener=opener).reference(0) == {'price': 100, 'at': 0}
    assert 'interval=5m' in opener.calls[0][0].full_url
    with pytest.raises(FeedError, match='MISSING_REFERENCE'):
        PublicFeed(opener=FakeOpener()).reference(0)


def test_public_history_paginates_only_closed_24_hour_window():
    opener = FakeOpener()
    feed = PublicFeed(opener=opener)
    now = 2000*MINUTE+12345
    assert feed.history(now) == []
    assert len(opener.calls) == 2
    urls = [call[0].full_url for call in opener.calls]
    assert 'startTime=33600000' in urls[0]
    assert 'endTime=93599999' in urls[0]
    assert 'startTime=93600000' in urls[1]
    assert 'endTime=119999999' in urls[1]


def test_offline_hides_live_preserves_last_known_then_recovers():
    app, clock = service()
    assert app.snapshot()['live_price'] is None
    app.poll_quote()
    initial = app.snapshot()
    saved = deepcopy(app.quote)
    assert initial['health']['status'] == 'HEALTHY'
    assert initial['live_price'] is not None
    def fail():
        raise FeedError('CONNECTION_FAILURE')
    app.feed.trade = fail
    assert app.poll_quote() == 5
    offline = app.snapshot()
    assert offline['live_price'] is None
    assert offline['quote']['price'] == initial['live_price']
    assert app.quote == saved
    clock.advance(5)
    app.feed = SyntheticFeed(clock=lambda: clock.wall)
    app.poll_quote()
    assert app.snapshot()['health']['status'] == 'RECOVERING'
    app.poll_quote()
    assert app.snapshot()['health']['status'] == 'HEALTHY'
    assert app.snapshot()['health']['recoveries'] == 1


@pytest.mark.parametrize('offset,reason', [(-16000, 'STALE_SOURCE'), (2001, 'CLOCK_SKEW')])
def test_stale_and_future_quotes_never_live(offset, reason):
    app, clock = service()
    app.feed.trade = lambda: [dict(time=int(clock.wall*1000)+offset, price=100)]
    app.poll_quote()
    state = app.snapshot()
    assert state['live_price'] is None
    assert state['health']['status'] == 'DELAYED'
    assert state['health']['reason'] == reason


def test_monotonic_staleness_survives_wall_clock_rollback():
    app, clock = service()
    app.poll_quote()
    clock.monotonic += 20
    clock.wall -= 1
    state = app.snapshot()
    assert state['quote']['receipt_age_ms'] == 20000
    assert state['live_price'] is None
    assert state['health']['status'] == 'DELAYED'


def test_out_of_order_quote_rejected_without_replacing_last_known():
    app, clock = service()
    app.poll_quote()
    previous = deepcopy(app.quote)
    app.feed.trade = lambda: [dict(time=previous['source_at']-1, price=1)]
    app.poll_quote()
    assert app.snapshot()['health']['reason'] == 'OUT_OF_ORDER_QUOTE'
    assert app.quote == previous


def test_cycle_boundary_expires_previous_reference_and_counts_down():
    app, clock = service()
    clock.wall = 1800000299.999
    app.poll_reference()
    state = app.snapshot()
    assert state['cycle']['remaining_ms'] == 1
    assert state['cycle']['reference_price'] == 80000
    clock.advance(.001)
    state = app.snapshot()
    assert state['cycle']['remaining_ms'] == CYCLE
    assert state['cycle']['reference_price'] is None
    app.poll_reference()
    assert app.snapshot()['cycle']['reference_at'] == 1800000300000


def test_history_quality_gaps_errors_and_staleness():
    app, clock = service()
    assert app.snapshot()['history']['status'] == 'LOADING'
    app.poll_history()
    assert app.snapshot()['history']['coverage'] == 1
    app.history_points.pop(100)
    state = app.snapshot()['history']
    assert state['status'] == 'PARTIAL'
    assert state['missing'] == 1
    def fail(_):
        raise FeedError('HTTP_500')
    app.feed.history = fail
    assert app.poll_history() is False
    assert app.snapshot()['history']['error'] == 'HTTP_500'
    app.history_error = None
    clock.advance(121)
    assert app.snapshot()['history']['error'] == 'HISTORY_STALE'


def test_exponential_retry_is_bounded_and_retry_after_honored():
    assert [backoff(i) for i in range(1, 9)] == [5, 10, 20, 40, 80, 120, 120, 120]
    app, _ = service()
    def fail():
        raise FeedError('RATE_LIMIT', 240)
    app.feed.trade = fail
    assert app.poll_quote() == 240


def test_unexpected_worker_exception_sanitized_and_no_live_fallback():
    app, _ = service()
    app.poll_quote()
    def fail():
        raise RuntimeError('private transport detail must never reach API')
    app.feed.trade = fail
    delays = []
    def stop_after_iteration(delay):
        delays.append(delay)
        app.stop_event.set()
    app.stop_event.wait = stop_after_iteration
    app._loop(app.poll_quote, 5)
    state = app.snapshot()
    assert state['health']['reason'] == 'INTERNAL_FEED_ERROR'
    assert state['live_price'] is None
    assert 'private transport detail' not in json.dumps(state)
    assert delays == [5]


@pytest.fixture
def local_server(tmp_path):
    app, _ = service()
    app.poll_quote()
    server = make_server(app, tmp_path, port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    yield server, tmp_path
    server.shutdown()
    server.server_close()
    worker.join(timeout=2)


def request(server, method, route, headers=None):
    client = HTTPConnection(*server.server_address, timeout=5)
    try:
        client.request(method, route, headers=headers or {})
        response = client.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        client.close()


def test_http_loopback_research_state_no_cors_or_secret(local_server):
    server, root = local_server
    assert server.server_address[0] == '127.0.0.1'
    code, headers, body = request(server, 'GET', '/api/state')
    assert code == 200
    state = json.loads(body)
    assert state['research'] == dict(status='REAL_DATA_NOT_READY',
                                    compatibility='TARGET_MISMATCH', prediction_available=False)
    assert 'p_up' not in state and 'p_down' not in state
    assert headers['Cache-Control'] == 'no-store'
    assert 'Access-Control-Allow-Origin' not in headers
    assert "connect-src 'self'" in headers['Content-Security-Policy']
    assert list(root.iterdir()) == []


@pytest.mark.parametrize('method,route,headers,status', [
    ('POST', '/api/state', {}, 501),
    ('GET', '/api/state', {'Host': 'attacker.invalid'}, 403),
    ('GET', '/../../README.md', {}, 404),
    ('GET', '/wallet', {}, 404),
    ('GET', '/api/order', {}, 404),
])
def test_http_rejects_mutation_external_host_arbitrary_routes(local_server, method, route, headers, status):
    assert request(local_server[0], method, route, headers)[0] == status


def test_offline_reports_deterministic_without_file_writes(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Dashboard reports must not write to disk')
    monkeypatch.setattr(Path, 'write_text', forbidden)
    monkeypatch.setattr(Path, 'write_bytes', forbidden)
    offline_report.cache_clear()
    for name in ('m92', 'm102'):
        first = offline_report(name)
        offline_report.cache_clear()
        assert offline_report(name) == first
        assert 'REAL_DATA_NOT_READY' in first
        assert 'SYNTHETIC' in first
