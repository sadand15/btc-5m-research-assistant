"""Bounded, manual BTC 5m contract discovery; never a study or predictor."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re

import predict_fun_readonly_probe as base

ROOT = Path(__file__).resolve().parents[1]
SEARCHES = ('Bitcoin 5 minutes', 'BTC 5 minutes', 'Bitcoin 5m', 'BTC 5m')
MAX_PAGES = 10
MAX_CANDIDATES_PER_STATE = 6
RECENT_MS = 24 * 60 * 60 * 1000
NATIVE_FIELDS = ('settledAt', 'resolvedAt', 'finalizedAt', 'settled_at',
                 'resolved_at', 'finalized_at', 'resolutionTime',
                 'resolutionTimestamp', 'settlementTime', 'settlementTimestamp')


def safe_route(path, params):
    if path == '/v1/categories':
        required = {'first': 50, 'status': params.get('status'), 'marketVariant': 'CRYPTO_UP_DOWN'}
        if params.get('status') not in ('OPEN', 'RESOLVED'):
            return False
        if set(params) not in (set(required), set(required) | {'after'}):
            return False
        if any(params.get(k) != v for k, v in required.items()):
            return False
        return 'after' not in params or bool(isinstance(params['after'], str)
            and re.fullmatch(r'[A-Za-z0-9_+/=.:-]{1,512}', params['after']))
    if path == '/v1/search':
        return params in ({'query': q, 'includeResolved': 'true', 'limit': 50} for q in SEARCHES)
    return not params and bool(re.fullmatch(
        r'/v1/(?:markets/[0-9]{1,20}|categories/[A-Za-z0-9_-]{1,180})', path))


class Client(base.Client):
    allowed_route = staticmethod(safe_route)
    max_requests = 80


def stamp(value):
    if not isinstance(value, str):
        raise ValueError('timestamp must be explicit')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None or dt.microsecond % 1000:
        raise ValueError('timezone and millisecond boundary required')
    return int(dt.timestamp() * 1000)


def btc(value):
    text = ' '.join(str(value.get(k, '')) for k in ('title', 'question', 'slug', 'categorySlug'))
    return bool(re.search(r'\b(?:BTC|Bitcoin)\b', text, re.I))


def candidate(value):
    if not isinstance(value, dict) or not btc(value):
        return False
    try:
        return stamp(value['endsAt']) - stamp(value['startsAt']) == 300000
    except (KeyError, ValueError, TypeError, OverflowError):
        text = ' '.join(str(value.get(k, '')) for k in ('title', 'question', 'slug', 'categorySlug'))
        return bool(re.search(r'(?<![0-9])5[ -]*(?:m\b|min(?:ute)?s?\b)', text, re.I))


def inspect_pair(market, category, now):
    """Structural coverage only. Rules and oracle equivalence still require review."""
    reasons = []
    if not btc(market) or market.get('marketVariant') != 'CRYPTO_UP_DOWN':
        reasons.append('NOT_EXPLICIT_BTC_DIRECTION_MARKET')
    if not market.get('categorySlug') or market.get('categorySlug') != category.get('slug'):
        reasons.append('CATEGORY_IDENTITY_MISMATCH')
    start = end = None
    try:
        start, end = stamp(category['startsAt']), stamp(category['endsAt'])
        if end - start != 300000:
            reasons.append('DURATION_NOT_EXACT_300000_MS')
    except (KeyError, ValueError, TypeError, OverflowError):
        reasons.append('MISSING_OR_AMBIGUOUS_BOUNDARIES')
    for name in ('startsAt', 'endsAt'):
        if name in market and market[name] != category.get(name):
            reasons.append('MARKET_CATEGORY_BOUNDARY_CONFLICT')
    outcomes = market.get('outcomes')
    mapping = {}
    if isinstance(outcomes, list) and len(outcomes) == 2 and all(isinstance(o, dict) for o in outcomes):
        for o in outcomes:
            side = str(o.get('name', '')).upper()
            token = o.get('onChainId')
            index = o.get('indexSet')
            if side in ('UP', 'DOWN') and isinstance(token, str) and re.fullmatch(r'[0-9]{1,100}', token) \
                    and type(index) is int and index > 0 and side not in mapping:
                mapping[side] = dict(token_id=token, index_set=index)
    if set(mapping) != {'UP', 'DOWN'} or len({v['token_id'] for v in mapping.values()}) != 2 \
            or len({v['index_set'] for v in mapping.values()}) != 2:
        reasons.append('AMBIGUOUS_OUTCOME_TOKEN_MAPPING')
    if not isinstance(market.get('description'), str) or not market['description'].strip():
        reasons.append('MISSING_RULE_TEXT')
    resolved = False
    resolution = market.get('resolution')
    if market.get('status') == 'RESOLVED':
        resolved = isinstance(resolution, dict) and isinstance(outcomes, list) and len(outcomes) == 2 and any(
            isinstance(o, dict) and o.get('status') == 'WON'
            and all(resolution.get(k) == o.get(k) for k in ('name', 'indexSet', 'onChainId', 'status'))
            for o in outcomes) and sorted(str(o.get('status')) for o in outcomes if isinstance(o, dict)) == ['LOST', 'WON']
        if not resolved:
            reasons.append('MISSING_OR_CONFLICTING_RESOLUTION')
        if end is not None and now < end:
            reasons.append('RESOLVED_BEFORE_CYCLE_END')
    cohort = None
    if not reasons:
        if resolved:
            cohort = 'RESOLVED'
        elif market.get('status') == 'REGISTERED' and market.get('tradingStatus') == 'OPEN' \
                and resolution is None:
            if start <= now < end:
                cohort = 'CURRENT_OPEN'
            elif end <= now <= end + RECENT_MS:
                cohort = 'RECENT_WINDOW_OPEN_STATUS'
        if cohort is None:
            reasons.append('NOT_CURRENT_RECENT_OPEN_OR_RESOLVED')
    return dict(accepted=not reasons, reasons=sorted(set(reasons)), cohort=cohort,
                market_id=str(market.get('id', '')), start_at=start, end_at=end,
                duration_ms=end-start if start is not None and end is not None else None,
                utc_5m_aligned=start % 300000 == 0 if start is not None else None,
                token_mapping=mapping,
                observed_status=market.get('status'), trading_status=market.get('tradingStatus'),
                native_time_fields={k: market[k] for k in NATIVE_FIELDS if k in market},
                native_time_semantics='UNVERIFIED', first_observed_final_at=None,
                rule_sha256=hashlib.sha256(str(market.get('description', '')).encode()).hexdigest(),
                prediction_compatibility='INSUFFICIENT_EVIDENCE')


def probe(key, root=ROOT, session=None, clock=None, pause=None):
    if not isinstance(key, str) or not key.strip():
        raise base.ProbeError('MISSING_CREDENTIAL')
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,256}', key):
        raise base.ProbeError('INVALID_CREDENTIAL_FORMAT')
    directory = base.output_directory(root)
    client = Client(key, session, clock, pause)
    report = dict(schema_version=1, phase='M9_1_PHASE3B', readiness='NOT_READY',
                  probe_status='INCOMPLETE', prediction_compatibility='INSUFFICIENT_EVIDENCE',
                  study_started=False, manifest_allowed=False, fixtures=[], markets=[],
                  discovery=[], rejected_candidates=[], lifecycle_snapshots=[],
                  observation_time_scope='THIS_PROBE_RUN_ONLY', finality_verified=False,
                  limits=dict(requests=80, pages_per_state=MAX_PAGES,
                              candidates_per_state=MAX_CANDIDATES_PER_STATE, recent_ms=RECENT_MS))
    seen = set()
    attempts = {'OPEN': 0, 'RESOLVED': 0}
    first_resolved = {}

    def capture(path, params=None):
        payload, metadata = client.get(path, params)
        # Record only validated discovery parameters, never request headers.
        metadata['query'] = base.sanitized(
            {'description': json.dumps(params or {}, sort_keys=True)}, key)['description']
        name = f'fixture-{len(report["fixtures"])+1:02}.json'
        base.write_new(directory/name, dict(metadata=metadata, payload=payload))
        report['fixtures'].append(name)
        def observe(value):
            if isinstance(value, dict):
                if value.get('status') == 'RESOLVED' and value.get('resolution') is not None:
                    mid = str(value.get('id', ''))
                    first_resolved.setdefault(mid, dict(received_at=metadata['received_at'],
                        available_at=metadata['available_at'], fixture=name))
                for child in value.values():
                    observe(child)
            elif isinstance(value, list):
                for child in value:
                    observe(child)
        observe(payload)
        return payload, metadata, name

    def covered():
        cohorts = {m['cohort'] for m in report['markets'] if m['accepted']}
        return 'RESOLVED' in cohorts and bool(cohorts & {'CURRENT_OPEN', 'RECENT_WINDOW_OPEN_STATUS'})

    def consider(category, origin):
        if not candidate(category):
            return
        slug = category.get('slug')
        if not isinstance(slug, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,180}', slug) or slug in seen:
            return
        state = 'RESOLVED' if category.get('status') == 'RESOLVED' else 'OPEN'
        if attempts[state] >= MAX_CANDIDATES_PER_STATE:
            return
        seen.add(slug)
        attempts[state] += 1
        payload, _, cname = capture('/v1/categories/' + slug)
        detail = payload['data']
        if not isinstance(detail, dict) or detail.get('slug') != slug:
            raise base.ProbeError('CATEGORY_IDENTITY_MISMATCH')
        members = detail.get('markets')
        if not isinstance(members, list) or len(members) != 1 or not isinstance(members[0], dict):
            report['rejected_candidates'].append(dict(category_slug=slug, fixture=cname,
                reason='AMBIGUOUS_CATEGORY_MARKET_MEMBERSHIP'))
            return
        mid = str(members[0].get('id', ''))
        if not re.fullmatch(r'[0-9]{1,20}', mid):
            raise base.ProbeError('MARKET_IDENTITY_INVALID')
        payload, meta, mname = capture('/v1/markets/' + mid)
        market = payload['data']
        if not isinstance(market, dict) or str(market.get('id', '')) != mid:
            raise base.ProbeError('MARKET_IDENTITY_MISMATCH')
        row = inspect_pair(market, detail, meta['received_at'])
        row.update(category_fixture=cname, market_fixture=mname, discovery_fixture=origin,
                   available_at=meta['available_at'], first_observed_resolved_at=None)
        if row['accepted'] and row['cohort'] == 'RESOLVED':
            row['first_observed_resolved_at'] = first_resolved[mid]['received_at']
            row['first_resolved_evidence'] = first_resolved[mid]
        report['markets'].append(row)

    try:
        for state in ('OPEN', 'RESOLVED'):
            cursor = None
            cursors = set()
            for page in range(MAX_PAGES):
                params = dict(first=50, status=state, marketVariant='CRYPTO_UP_DOWN')
                if cursor is not None:
                    params['after'] = cursor
                payload, _, name = capture('/v1/categories', params)
                entries = payload['data']
                if not isinstance(entries, list):
                    raise base.ProbeError('CATEGORY_LIST_SCHEMA')
                report['discovery'].append(dict(fixture=name, requested_status=state, page=page+1,
                    entries=len(entries), btc_5m_candidates=sum(candidate(x) for x in entries)))
                for item in entries:
                    consider(item, name)
                    if covered():
                        break
                if covered():
                    break
                cursor = payload.get('cursor')
                if cursor in (None, ''):
                    break
                if not isinstance(cursor, str) or not re.fullmatch(r'[A-Za-z0-9_+/=.:-]{1,512}', cursor):
                    raise base.ProbeError('INVALID_CURSOR')
                if cursor in cursors:
                    raise base.ProbeError('REPEATED_CURSOR')
                cursors.add(cursor)
        if not covered():
            for query in SEARCHES:
                payload, _, name = capture('/v1/search', dict(query=query, includeResolved='true', limit=50))
                data = payload['data']
                if not isinstance(data, dict) or not isinstance(data.get('categories'), list) \
                        or not isinstance(data.get('markets'), list):
                    raise base.ProbeError('SEARCH_SCHEMA')
                for item in data['categories']:
                    consider(item, name)
                for item in data['markets']:
                    if candidate(item):
                        consider(dict(item, slug=item.get('categorySlug')), name)
                if covered():
                    break
        # A second observation is evidence of two observed states only, never finality.
        for row in report['markets']:
            if row['accepted'] and row['cohort'] == 'CURRENT_OPEN':
                payload, meta, name = capture('/v1/markets/' + row['market_id'])
                value = payload['data']
                if not isinstance(value, dict) or str(value.get('id')) != row['market_id']:
                    raise base.ProbeError('MARKET_IDENTITY_MISMATCH')
                report['lifecycle_snapshots'].append(dict(market_id=row['market_id'], fixture=name,
                    received_at=meta['received_at'], status=value.get('status'),
                    trading_status=value.get('tradingStatus'), transition_semantics='UNVERIFIED'))
                break
        report['probe_status'] = ('TARGETED_CAPTURE_REQUIRES_CONTRACT_REVIEW' if covered()
                                  else 'BTC5M_COVERAGE_INCOMPLETE')
    except base.ProbeError as exc:
        report['probe_status'] = str(exc)
    except Exception:
        report['probe_status'] = 'SCHEMA_OR_OUTPUT_FAILURE'
    finally:
        client.http.close()
    report['request_count'] = client.count
    report['coverage'] = {cohort: sum(m['accepted'] and m['cohort'] == cohort for m in report['markets'])
                          for cohort in ('CURRENT_OPEN', 'RECENT_WINDOW_OPEN_STATUS', 'RESOLVED')}
    report['same_family_contract_verified'] = False
    base.write_new(directory/'report.json', report)
    return report, directory


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        report, directory = probe(os.environ.get('PREDICT_FUN_API_KEY'))
        print(json.dumps(dict(probe_status=report['probe_status'], readiness='NOT_READY',
            prediction_compatibility='INSUFFICIENT_EVIDENCE', requests=report['request_count'],
            fixtures=len(report['fixtures']), coverage=report['coverage'],
            output=str(directory.relative_to(ROOT)))))
        return 0 if report['probe_status'] == 'TARGETED_CAPTURE_REQUIRES_CONTRACT_REVIEW' else 2
    except base.ProbeError as exc:
        reason = str(exc) if str(exc) in ('MISSING_CREDENTIAL', 'INVALID_CREDENTIAL_FORMAT',
                                         'OUTPUT_ALIAS_REJECTED') else 'FAILED_CLOSED'
        print(json.dumps(dict(probe_status=reason, readiness='NOT_READY')))
        return 2
    except Exception:
        print('{"probe_status":"FAILED_CLOSED","readiness":"NOT_READY"}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
