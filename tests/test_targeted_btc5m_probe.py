"""Synthetic transport only; never read environment credentials or send a request."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import requests

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
SPEC = importlib.util.spec_from_file_location('predict_fun_readonly_probe', SCRIPTS / 'predict_fun_readonly_probe.py')
base = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base)
sys.modules.setdefault('predict_fun_readonly_probe', base)
SPEC = importlib.util.spec_from_file_location('targeted_probe', SCRIPTS / 'predict_fun_btc5m_probe.py')
target = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(target)
KEY = 'synthetic-' + 'credential-for-tests'
NOW = target.stamp('2026-10-08T00:02:00Z')


@pytest.fixture(autouse=True)
def network_forbidden(monkeypatch):
    def fail(*a, **k):
        pytest.fail('Network forbidden')
    monkeypatch.setattr(requests.Session, 'request', fail)


class Response:
    def __init__(self, data, cursor=None, status=200):
        self.body = base.encode(dict(success=True, data=data, cursor=cursor))
        self.status_code = status
        self.headers = {'Set-Cookie': KEY}
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def iter_content(self, size): yield self.body


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.cookies = SimpleNamespace(clear=lambda: None)
        self.closed = False
    def get(self, url, **kw):
        self.calls.append((url, kw))
        return next(self.responses)
    def close(self): self.closed = True


def market(mid=1, resolved=False):
    outcomes = [dict(name='Up', onChainId=str(mid*10+1), indexSet=1, status='WON' if resolved else None),
                dict(name='Down', onChainId=str(mid*10+2), indexSet=2, status='LOST' if resolved else None)]
    return dict(id=mid, title='Bitcoin Up or Down 5 minutes', categorySlug=f'btc-5m-{mid}',
        description='Synthetic contract: UP > O; ties require review', marketVariant='CRYPTO_UP_DOWN',
        status='RESOLVED' if resolved else 'REGISTERED', tradingStatus='CLOSED' if resolved else 'OPEN',
        resolution=outcomes[0].copy() if resolved else None, outcomes=outcomes)


def category(mid=1, resolved=False):
    return dict(slug=f'btc-5m-{mid}', title='Bitcoin 5 minutes',
        startsAt='2026-10-07T23:55:00Z' if resolved else '2026-10-08T00:00:00Z',
        endsAt='2026-10-08T00:00:00Z' if resolved else '2026-10-08T00:05:00Z',
        status='RESOLVED' if resolved else 'OPEN', markets=[market(mid, resolved)])


def run(tmp_path, responses):
    session = Session(responses)
    report, directory = target.probe(KEY, tmp_path, session, lambda: NOW, lambda _: None)
    return report, directory, session


def test_targeted_pair_and_repeat_are_not_readiness(tmp_path):
    c1, c2 = category(), category(2, True)
    result, directory, session = run(tmp_path, [Response([c1]), Response(c1), Response(market()),
        Response([c2]), Response(c2), Response(market(2, True)), Response(market())])
    assert result['probe_status'] == 'TARGETED_CAPTURE_REQUIRES_CONTRACT_REVIEW'
    assert result['coverage'] == {'CURRENT_OPEN': 1, 'RECENT_WINDOW_OPEN_STATUS': 0, 'RESOLVED': 1}
    assert result['readiness'] == 'NOT_READY' and not result['manifest_allowed']
    assert result['prediction_compatibility'] == 'INSUFFICIENT_EVIDENCE'
    assert not result['study_started'] and not result['same_family_contract_verified']
    assert len(result['lifecycle_snapshots']) == 1 and not result['finality_verified']
    assert result['markets'][1]['first_resolved_evidence']['fixture'] == 'fixture-04.json'
    content = ''.join(p.read_text(encoding='utf-8') for p in directory.iterdir())
    assert KEY not in content and 'Set-Cookie' not in content
    assert session.closed and not session.trust_env
    for url, kw in session.calls:
        assert target.safe_route(url.removeprefix(base.BASE), kw['params'])
        assert not kw['allow_redirects']


@pytest.mark.parametrize('minutes', [15, 60, 1440])
def test_wrong_durations_cannot_consume_candidate_quota(tmp_path, minutes):
    from datetime import datetime, timedelta, timezone
    wrong = category(3)
    wrong['endsAt'] = (datetime(2026, 10, 8, tzinfo=timezone.utc)+timedelta(minutes=minutes)).isoformat()
    assert not target.candidate(wrong)
    c1, c2 = category(), category(2, True)
    result, _, session = run(tmp_path, [Response([wrong], cursor='page2'), Response([c1]), Response(c1),
        Response(market()), Response([c2]), Response(c2), Response(market(2, True)), Response(market())])
    assert result['coverage']['CURRENT_OPEN'] == 1
    assert session.calls[1][1]['params']['after'] == 'page2'
    assert not any(url.endswith('/btc-5m-3') for url, _ in session.calls)


@pytest.mark.parametrize('change,reason', [
    ({'endsAt': '2026-10-08T00:04:59Z'}, 'DURATION_NOT_EXACT_300000_MS'),
    ({'endsAt': None}, 'MISSING_OR_AMBIGUOUS_BOUNDARIES'),
    ({'startsAt': '2026-10-08T00:00:00'}, 'MISSING_OR_AMBIGUOUS_BOUNDARIES'),
    ({'slug': 'other'}, 'CATEGORY_IDENTITY_MISMATCH')])
def test_pair_boundary_rejection(change, reason):
    c = category(); c.update(change)
    assert reason in target.inspect_pair(market(), c, NOW)['reasons']


@pytest.mark.parametrize('mode', ['duplicate_token', 'duplicate_index', 'yes_no', 'missing', 'boolean_index'])
def test_mapping_never_guessed(mode):
    m = market()
    if mode == 'duplicate_token': m['outcomes'][1]['onChainId'] = m['outcomes'][0]['onChainId']
    if mode == 'duplicate_index': m['outcomes'][1]['indexSet'] = 1
    if mode == 'yes_no': m['outcomes'][0]['name'] = 'Yes'; m['outcomes'][1]['name'] = 'No'
    if mode == 'missing': m['outcomes'] = []
    if mode == 'boolean_index': m['outcomes'][0]['indexSet'] = True
    assert 'AMBIGUOUS_OUTCOME_TOKEN_MAPPING' in target.inspect_pair(m, category(), NOW)['reasons']


@pytest.mark.parametrize('mode', ['null', 'wrong_token', 'both_won', 'future_resolved'])
def test_resolution_is_not_inferred(mode):
    m, c = market(2, True), category(2, True)
    if mode == 'null': m['resolution'] = None
    if mode == 'wrong_token': m['resolution']['onChainId'] = '999'
    if mode == 'both_won': m['outcomes'][1]['status'] = 'WON'
    if mode == 'future_resolved': c['startsAt'] = '2026-10-08T00:00:00Z'; c['endsAt'] = '2026-10-08T00:05:00Z'
    assert not target.inspect_pair(m, c, NOW)['accepted']


def test_stale_future_disputed_not_open_coverage():
    m, c = market(), category()
    assert not target.inspect_pair(m, c, NOW-300000)['accepted']
    assert not target.inspect_pair(m, c, NOW+2*target.RECENT_MS)['accepted']
    m['status'] = 'PRICE_DISPUTED'
    assert not target.inspect_pair(m, c, NOW)['accepted']


def test_recent_open_is_separate_and_alignment_does_not_assume_equivalence():
    row = target.inspect_pair(market(), category(), NOW+300000)
    assert row['cohort'] == 'RECENT_WINDOW_OPEN_STATUS'
    c = category(); c.update(startsAt='2026-10-08T00:00:01Z', endsAt='2026-10-08T00:05:01Z')
    row = target.inspect_pair(market(), c, NOW)
    assert row['accepted'] and not row['utc_5m_aligned']
    assert row['prediction_compatibility'] == 'INSUFFICIENT_EVIDENCE'


@pytest.mark.parametrize('path,params', [('/v1/orders', {}), ('/v1/wallet', {}),
    ('/v1/balance', {}), ('/v1/transfer', {}), ('/v1/funding', {}),
    ('/v1/markets/1/orderbook', {}), ('/v1/categories', {'first': 1000}),
    ('/v1/search', {'query': 'wallet'}), ('/v1/categories/a/../wallet', {})])
def test_route_blocked_before_request(path, params):
    session = Session([])
    with pytest.raises(base.ProbeError, match='ROUTE_NOT_ALLOWED'):
        target.Client(KEY, session).get(path, params)
    assert not session.calls


def test_search_fallback_provides_pairs(tmp_path):
    c1, c2 = category(), category(2, True)
    report, _, _ = run(tmp_path, [Response([]), Response([]),
        Response(dict(categories=[c1, c2], markets=[])), Response(c1), Response(market()),
        Response(c2), Response(market(2, True)), Response(market())])
    assert report['probe_status'] == 'TARGETED_CAPTURE_REQUIRES_CONTRACT_REVIEW'


def test_no_results_explicit_incomplete(tmp_path):
    report, _, _ = run(tmp_path, [Response([]), Response([])] +
        [Response(dict(categories=[], markets=[])) for _ in target.SEARCHES])
    assert report['probe_status'] == 'BTC5M_COVERAGE_INCOMPLETE'
    assert report['markets'] == [] and report['readiness'] == 'NOT_READY'


def test_cursor_loop_closed(tmp_path):
    report, _, session = run(tmp_path, [Response([], 'same'), Response([], 'same')])
    assert report['probe_status'] == 'REPEATED_CURSOR' and len(session.calls) == 2


@pytest.mark.parametrize('code', [301, 401, 403, 429, 500])
def test_http_failure_stops_without_fallback(tmp_path, code):
    report, _, session = run(tmp_path, [Response([], status=code)])
    assert report['probe_status'] not in ('TARGETED_CAPTURE_REQUIRES_CONTRACT_REVIEW', 'BTC5M_COVERAGE_INCOMPLETE')
    assert len(session.calls) == 1


def test_no_secret_missing_key_no_write(tmp_path):
    with pytest.raises(base.ProbeError, match='MISSING_CREDENTIAL'):
        target.probe(None, tmp_path)
    assert not list(tmp_path.iterdir())


def test_native_times_retained_but_not_interpreted():
    m = market(2, True); m['settled_at'] = '2026-10-08T00:01:00Z'
    row = target.inspect_pair(base.sanitized(m, KEY), category(2, True), NOW)
    assert row['native_time_fields']['settled_at'] == m['settled_at']
    assert row['native_time_semantics'] == 'UNVERIFIED' and row['first_observed_final_at'] is None


def test_previous_probe_output_and_sealed_evidence_untouched(tmp_path):
    old = tmp_path / 'runtime' / 'sealed-evidence.json'
    old.parent.mkdir(); old.write_bytes(b'untouched')
    responses = lambda: [Response([]), Response([])] + [Response(dict(categories=[], markets=[])) for _ in target.SEARCHES]
    _, first, _ = run(tmp_path, responses())
    data = (first / 'report.json').read_bytes()
    _, second, _ = run(tmp_path, responses())
    assert first != second and data == (first / 'report.json').read_bytes()
    assert old.read_bytes() == b'untouched'
