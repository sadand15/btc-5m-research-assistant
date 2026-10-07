"""Offline transport fixtures only; no real credential lookup or network access."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

SPEC = importlib.util.spec_from_file_location('readonly_probe',
    Path(__file__).resolve().parents[1] / 'scripts/predict_fun_readonly_probe.py')
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
KEY = 'test-' + 'credential-' + 'not-real'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Real network forbidden in probe tests')
    monkeypatch.setattr(requests.Session, 'request', forbidden)


class Response:
    def __init__(self, data=None, status=200, body=None):
        self.body = body if body is not None else json.dumps({'success':True,'data':data}).encode()
        self.status_code = status
        self.headers = {'Set-Cookie':KEY, 'Authorization':KEY, 'X-RateLimit-Limit':'240',
                        'X-RateLimit-Remaining':KEY}

    def __enter__(self): return self
    def __exit__(self, *args): return False
    def iter_content(self, size):
        for start in range(0,len(self.body),size):
            yield self.body[start:start+size]


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.cookies = SimpleNamespace(clear=lambda: None)
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url,kwargs))
        return next(self.responses)

    def close(self): self.closed = True


def market(i, status):
    return dict(id=i,title='BTC Up or Down',categorySlug=f'btc-{i}',
                marketVariant='CRYPTO_UP_DOWN',status=status,tradingStatus='OPEN',
                description='Public rules '+KEY,secret=KEY,authorization=KEY,
                outcomes=[dict(name='Up', indexSet=1, onChainId='public-token-id')],
                resolution={'indexSet':1,'status':'WON'} if status=='RESOLVED' else None)


def category(i):
    return dict(slug=f'btc-{i}',startsAt='2026-10-07T00:00:00Z',endsAt='2026-10-07T00:05:00Z')


def test_complete_capture_sanitized_no_study(tmp_path):
    protected = tmp_path/'runtime'/'forward'/'sealed.json'
    protected.parent.mkdir(parents=True)
    protected.write_bytes(b'unchanged')
    session = Session([Response([market(1,'OPEN')]),Response(market(1,'OPEN')),Response(category(1)),
                       Response([market(2,'RESOLVED')]),Response(market(2,'RESOLVED')),Response(category(2))])
    report, directory = probe.probe(KEY, tmp_path, session, clock=lambda:1000, pause=lambda _:None)
    assert report['probe_status']=='CAPTURED_REQUIRES_CONTRACT_REVIEW'
    assert report['readiness']=='NOT_READY' and not report['study_started']
    assert report['request_count']==6 and len(report['markets'])==2
    assert all(m['five_minute'] for m in report['markets'])
    assert report['markets'][1]['first_observed_resolved_at']==1000
    assert report['markets'][1]['first_observed_final_at'] is None
    assert report['markets'][1]['native_settled_at'] is None
    assert protected.read_bytes()==b'unchanged'
    assert session.closed and session.trust_env is False
    content=''.join(p.read_text() for p in directory.iterdir())
    assert KEY not in content and 'Set-Cookie' not in content and 'Authorization' not in content
    assert 'public-token-id' in content and '[REDACTED]' in content
    for url, args in session.calls:
        assert url.startswith(probe.BASE+'/v1/')
        assert args['allow_redirects'] is False and args['stream'] is True
        assert args['headers']=={'x-api-key':KEY}
    fixture=json.loads((directory/'fixture-01.json').read_text())
    assert fixture['metadata']['rate_limit_headers']=={'x-ratelimit-limit':'240'}


@pytest.mark.parametrize('path', ['/v1/orders','/v1/orders/1','/v1/markets/1/orders',
    '/v1/wallet','/v1/balance','/v1/cancel','/v1/transfer','/v1/funding',
    '/v1/markets/1/../orders','https://evil.invalid/v1/markets','/v1/categories/a?wallet=1'])
def test_forbidden_route_never_sent(path):
    session=Session([])
    with pytest.raises(probe.ProbeError,match='ROUTE_NOT_ALLOWED'):
        probe.Client(KEY,session).get(path)
    assert not session.calls


@pytest.mark.parametrize('status', [301,302,307,401,403,429,500])
def test_fail_closed_http_no_retry_or_body_leak(tmp_path,status):
    session=Session([Response(status=status,body=KEY.encode())])
    report,directory=probe.probe(KEY,tmp_path,session,pause=lambda _:None)
    assert len(session.calls)==1 and report['fixtures']==[]
    assert KEY not in (directory/'report.json').read_text()
    assert report['probe_status']!='CAPTURED_REQUIRES_CONTRACT_REVIEW'


@pytest.mark.parametrize('key', [None,'','   ','bad\r\nheader'])
def test_missing_or_invalid_key_no_files_or_requests(tmp_path,key):
    session=Session([])
    with pytest.raises(probe.ProbeError):
        probe.probe(key,tmp_path,session)
    assert not list(tmp_path.iterdir()) and not session.calls


def test_missing_env_cli_redacted(monkeypatch,tmp_path,capsys):
    monkeypatch.delenv('PREDICT_FUN_API_KEY',raising=False)
    monkeypatch.setattr(probe,'ROOT',tmp_path)
    assert probe.main()==2
    assert json.loads(capsys.readouterr().out)['probe_status']=='MISSING_CREDENTIAL'
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('body', [b'not JSON', b'{"success":false}', b'{"success":true,"data":NaN}'])
def test_malformed_response_no_fixture(tmp_path,body):
    report,directory=probe.probe(KEY,tmp_path,Session([Response(body=body)]))
    assert report['fixtures']==[] and report['probe_status']!='CAPTURED_REQUIRES_CONTRACT_REVIEW'


def test_output_alias_rejected_before_network(tmp_path,monkeypatch):
    original=Path.is_junction
    monkeypatch.setattr(Path,'is_junction',lambda p: p.name=='runtime' or original(p))
    session=Session([])
    with pytest.raises(probe.ProbeError,match='OUTPUT_ALIAS_REJECTED'):
        probe.probe(KEY,tmp_path,session)
    assert not session.calls


def test_run_output_is_new_and_never_overwritten(tmp_path):
    first=probe.probe(KEY,tmp_path,Session([Response([]),Response([])]),pause=lambda _:None)[1]
    old=(first/'report.json').read_bytes()
    second=probe.probe(KEY,tmp_path,Session([Response([]),Response([])]),pause=lambda _:None)[1]
    assert first!=second and (first/'report.json').read_bytes()==old


def test_size_and_budget_limits(monkeypatch):
    monkeypatch.setattr(probe,'LIMIT',2)
    session=Session([Response([])])
    client=probe.Client(KEY,session)
    with pytest.raises(probe.ProbeError,match='RESPONSE_SIZE_LIMIT'):
        client.get('/v1/markets/1')
    client.count=12
    with pytest.raises(probe.ProbeError,match='REQUEST_BUDGET_EXHAUSTED'):
        client.get('/v1/markets/1')
    assert len(session.calls)==1


def test_transport_exception_never_rendered(tmp_path):
    class Broken(Session):
        def get(self,*args,**kwargs):
            raise requests.ConnectionError(KEY)
    report,directory=probe.probe(KEY,tmp_path,Broken([]))
    assert report['probe_status']=='TRANSPORT_OR_RESPONSE_FAILURE'
    assert KEY not in (directory/'report.json').read_text()


@pytest.mark.parametrize('params', [{'status':'OPEN','wallet':'yes'}, {'first':1000},
                                   {'url':'https://other.invalid'}])
def test_query_allowlist(params):
    session=Session([])
    with pytest.raises(probe.ProbeError,match='ROUTE_NOT_ALLOWED'):
        probe.Client(KEY,session).get('/v1/markets',params)
    assert not session.calls


def test_sensitive_free_text_and_unknown_fields_removed():
    clean=probe.sanitized({'description':'{"secret":"dummy"}',
                          'cookie':'example-cookie','outcomes':[{'onChainId':'public-id'}]},KEY)
    assert clean['description']=='[REDACTED_SENSITIVE_TEXT]'
    assert 'cookie' not in clean and clean['outcomes'][0]['onChainId']=='public-id'
