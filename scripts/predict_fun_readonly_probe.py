"""Manual, bounded public metadata probe. No study or trading imports."""
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import quote
import uuid

import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://api.predict.fun'
LIMIT = 2 * 1024 * 1024
FIELDS = set('success data id title question description categorySlug slug startsAt endsAt '
             'createdAt publishedAt status tradingStatus marketVariant variantData variantDetails '
             'crypto type priceFeedProvider priceFeedId priceFeedSymbol startPrice endPrice '
             'conditionId oracleQuestionId resolverAddress resolution resolutionProvider outcomes '
             'name label indexSet onChainId settledAt resolvedAt finalizedAt isFinal finality '
             'updatedAt timestamp tsMs markets categories cursor '
             'settled_at resolved_at finalized_at is_final resolutionTime resolutionTimestamp '
             'settlementTime settlementTimestamp'.split())


class ProbeError(Exception):
    pass


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2).encode('utf-8')


def sanitized(value, key, depth=0):
    if depth > 16:
        raise ProbeError('RESPONSE_DEPTH_LIMIT')
    if isinstance(value, dict):
        return {k: sanitized(v, key, depth+1) for k, v in value.items() if k in FIELDS}
    if isinstance(value, list):
        if len(value) > 100:
            raise ProbeError('RESPONSE_LIST_LIMIT')
        return [sanitized(v, key, depth+1) for v in value]
    if isinstance(value, str):
        if len(value) > 20000:
            raise ProbeError('RESPONSE_TEXT_LIMIT')
        for secret in (key, quote(key, safe='')):
            value = value.replace(secret, '[REDACTED]')
        value = re.sub(r'(?i)pred_sk_[a-z0-9_-]+', '[REDACTED]', value)
        value = re.sub(r'(?i)(?:bearer\s+\S+|(?:api[_-]?key|secret|password|authorization|cookie)\s*[:=]\s*\S+)',
                       '[REDACTED]', value)
        value = re.sub(r'https?://[^\s/:@]+:[^\s/@]+@', 'https://[REDACTED]@', value)
        value = re.sub(r'(?:gh[pousr]_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+)', '[REDACTED]', value)
        if re.search(r'(?i)PRIVATE KEY|["\'](?:api[_-]?key|secret|password|authorization|cookie)["\']\s*:', value):
            return '[REDACTED_SENSITIVE_TEXT]'
        return value
    if value is None or type(value) in (int, float, bool):
        return value
    raise ProbeError('RESPONSE_TYPE')


def safe_route(path, params):
    if path == '/v1/markets':
        return params in ({'first':50, 'status':s, 'marketVariant':'CRYPTO_UP_DOWN'}
                          for s in ('OPEN', 'RESOLVED'))
    return not params and bool(re.fullmatch(r'/v1/(?:markets/[0-9]{1,20}|categories/[A-Za-z0-9_-]{1,180})', path))


class Client:
    allowed_route = staticmethod(safe_route)
    max_requests = 12

    def __init__(self, key, session=None, clock=None, pause=None):
        self.key = key
        self.http = session or requests.Session()
        self.http.trust_env = False  # No inherited proxy, netrc credentials or ambient auth.
        self.clock = clock or (lambda: int(time.time()*1000))
        self.pause = pause or time.sleep
        self.count = 0

    def get(self, path, params=None):
        params = params or {}
        if not self.allowed_route(path, params):
            raise ProbeError('ROUTE_NOT_ALLOWED')
        if self.count >= self.max_requests:
            raise ProbeError('REQUEST_BUDGET_EXHAUSTED')
        if self.count:
            self.pause(1)
        self.count += 1
        started = self.clock()
        self.http.cookies.clear()
        try:
            with self.http.get(BASE+path, params=params, headers={'x-api-key':self.key},
                               timeout=(5, 15), allow_redirects=False, stream=True) as response:
                status = response.status_code
                if status != 200:
                    raise ProbeError({401:'AUTH_REJECTED',403:'ACCESS_REJECTED',429:'RATE_LIMITED'}.get(status, 'HTTP_REJECTED'))
                body = bytearray()
                for chunk in response.iter_content(65536):
                    body.extend(chunk)
                    if len(body) > LIMIT:
                        raise ProbeError('RESPONSE_SIZE_LIMIT')
                    if self.clock()-started > 30000:
                        raise ProbeError('RESPONSE_TIME_LIMIT')
                received = self.clock()
                raw = json.loads(body)
                if not isinstance(raw, dict) or raw.get('success') is not True or 'data' not in raw:
                    raise ProbeError('RESPONSE_SCHEMA')
                clean = sanitized(raw, self.key)
                clean_bytes = encode(clean)
                if self.key.encode() in clean_bytes:
                    raise ProbeError('SANITIZATION_REJECTED')
                # Only numeric rate-limit metadata; never cookies/auth/Location headers.
                safe_headers = {k.lower():v for k,v in response.headers.items()
                                if re.fullmatch(r'(?:x-)?ratelimit-(?:limit|remaining|reset)', k.lower())
                                and re.fullmatch(r'[0-9]{1,16}', v) and self.key not in v}
                return clean, dict(method='GET', endpoint=path, request_at=started,
                    received_at=received, available_at=self.clock(), http_status=status,
                    rate_limit_headers=safe_headers, raw_response_sha256=hashlib.sha256(body).hexdigest(),
                    sanitized_sha256=hashlib.sha256(clean_bytes).hexdigest(),
                    payload_is_sanitized=True, scope='CONTRACT_AUDIT_NOT_STUDY')
        except ProbeError:
            raise
        except Exception:
            raise ProbeError('TRANSPORT_OR_RESPONSE_FAILURE') from None
        finally:
            self.http.cookies.clear()


def output_directory(root):
    root = Path(root).resolve()
    parent = root
    for name in ('runtime', 'venue-contract-probes'):
        parent = parent / name
        if parent.is_symlink() or parent.is_junction() or parent.resolve() != parent:
            raise ProbeError('OUTPUT_ALIAS_REJECTED')
        parent.mkdir(exist_ok=True)
    directory = parent / uuid.uuid4().hex
    directory.mkdir()
    return directory


def write_new(path, value):
    with path.open('xb') as stream:
        stream.write(encode(value))


def probe(key, root=ROOT, session=None, clock=None, pause=None):
    if not isinstance(key, str) or not key.strip():
        raise ProbeError('MISSING_CREDENTIAL')
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,256}', key):
        raise ProbeError('INVALID_CREDENTIAL_FORMAT')
    directory = output_directory(root)
    client = Client(key, session, clock, pause)
    report = dict(readiness='NOT_READY', probe_status='INCOMPLETE', request_count=0,
                  fixtures=[], markets=[], study_started=False,
                  prediction_compatibility='NOT_EVALUATED', finality_verified=False,
                  limitations=['Bounded first-page discovery; absence is not proof of nonexistence',
                               'Point snapshots do not prove transitions or finality',
                               'Sanitized payloads are not byte-identical raw evidence'])

    def capture(path, params=None):
        payload, metadata = client.get(path, params)
        name = f'fixture-{len(report["fixtures"])+1:02}.json'
        write_new(directory/name, dict(metadata=metadata, payload=payload))
        report['fixtures'].append(name)
        return payload['data'], metadata

    try:
        selected = set()
        for state, maximum in [('OPEN',1), ('RESOLVED',2)]:
            listing, _ = capture('/v1/markets', {'first':50,'status':state,'marketVariant':'CRYPTO_UP_DOWN'})
            if not isinstance(listing, list):
                raise ProbeError('LIST_SCHEMA')
            found = 0
            attempts = 0
            for item in listing:
                if not isinstance(item, dict) or not re.search(r'\b(?:BTC|Bitcoin)\b',
                        str(item.get('title',''))+' '+str(item.get('question','')), re.I):
                    continue
                market_id = str(item.get('id',''))
                if market_id in selected or not re.fullmatch('[0-9]{1,20}', market_id):
                    continue
                if found >= maximum or attempts >= maximum:
                    break
                attempts += 1
                market, meta = capture('/v1/markets/'+market_id)
                if not isinstance(market, dict) or str(market.get('id')) != market_id:
                    raise ProbeError('MARKET_IDENTITY_MISMATCH')
                slug = market.get('categorySlug','')
                if not isinstance(slug,str) or not re.fullmatch('[A-Za-z0-9_-]{1,180}',slug):
                    raise ProbeError('CATEGORY_IDENTITY_INVALID')
                category, _ = capture('/v1/categories/'+slug)
                if not isinstance(category,dict) or category.get('slug') != slug:
                    raise ProbeError('CATEGORY_IDENTITY_MISMATCH')
                from datetime import datetime
                def stamp(value):
                    dt = datetime.fromisoformat(value.replace('Z','+00:00'))
                    if dt.tzinfo is None:
                        raise ValueError('timezone required')
                    return int(dt.timestamp()*1000)
                try:
                    start, end = stamp(category['startsAt']), stamp(category['endsAt'])
                    five_minute = end-start == 300000 and start % 300000 == 0
                except (ValueError,KeyError,TypeError,AttributeError):
                    five_minute = False
                selected.add(market_id)
                report['markets'].append(dict(market_id=market_id, five_minute=five_minute,
                    observed_status=market.get('status'), observed_trading_status=market.get('tradingStatus'),
                    first_observed_resolved_at=meta['received_at'] if market.get('status')=='RESOLVED' else None,
                    first_observed_final_at=None, available_at=meta['available_at'],
                    native_settled_at=None, native_timestamp_interpretation='NOT_VERIFIED'))
                found += int(five_minute)
        report['probe_status'] = 'CAPTURED_REQUIRES_CONTRACT_REVIEW'
    except ProbeError as exc:
        report['probe_status'] = str(exc)
    except Exception:
        report['probe_status'] = 'SCHEMA_OR_OUTPUT_FAILURE'
    finally:
        client.http.close()
    report['request_count'] = client.count
    # A run's local first receipt is not a global first observation across runs.
    report['observation_time_scope'] = 'THIS_PROBE_RUN_ONLY'
    write_new(directory/'report.json', report)
    return report, directory


def main():
    try:
        report, directory = probe(os.environ.get('PREDICT_FUN_API_KEY'))
        print(json.dumps(dict(probe_status=report['probe_status'], readiness='NOT_READY',
                              requests=report['request_count'], fixtures=len(report['fixtures']),
                              output=str(directory.relative_to(ROOT)))))
        return 0 if report['probe_status']=='CAPTURED_REQUIRES_CONTRACT_REVIEW' else 2
    except ProbeError as exc:
        reason = str(exc) if str(exc) in ('MISSING_CREDENTIAL', 'INVALID_CREDENTIAL_FORMAT',
                                         'OUTPUT_ALIAS_REJECTED') else 'FAILED_CLOSED'
        print(json.dumps({'probe_status':reason, 'readiness':'NOT_READY'}))
        return 2
    except Exception:
        # Never render request objects, exception messages or credential-bearing values.
        print('{"probe_status":"FAILED_CLOSED","readiness":"NOT_READY"}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
