"""Read-only, root-pinned structural audit. No replay, predictions or outcomes.

Standalone execution is supported over stdin in the frozen M9 image so no
installation or writes to the evidence host are necessary.
"""
import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

from btc5_v3.encoding import digest, timestamp
from btc5_v3.prospective.identity import APPROVED
from btc5_v3.prospective.store import Study, read

FIELDS = (
    'source', 'event_key', 'source_at', 'received_at', 'processed_at', 'market_id',
    'cycle_id', 'quality', 'identity_hash', 'payload.bids', 'payload.asks',
    'payload.rule_hash', 'payload.feed', 'payload.symbol', 'payload.market_start',
    'payload.market_end', 'payload.quote_type', 'payload.prediction',
    'payload.outcome', 'payload.settlement', 'payload.market_status',
    'payload.market_status_at', 'payload.market_status_available_at',
    'payload.reference_underlying_price', 'payload.reference_price_at',
    'payload.price', 'payload.quantity', 'payload.source_status',
    'payload.no_bids', 'payload.no_asks', 'payload.health',
    'payload.condition_id', 'payload.yes_token_id', 'payload.no_token_id',
)


def present(record, path):
    value = record
    for part in path.split('.'):
        if not isinstance(value, dict) or part not in value:
            return False
        value = value[part]
    return value is not None


def fingerprint(study):
    """Evidence file bytes only; no lock creation, timestamp or database writes."""
    return {p.name: hashlib.sha256(study.path(p.name).read_bytes()).hexdigest()
            for p in sorted(study.folder.iterdir()) if p.is_file()}


def audit_sealed(study, *, now, expected_root, expected_dataset, expected_collector):
    if type(study) is not Study or not timestamp(now):
        raise ValueError('INVALID_REQUEST')
    if not isinstance(expected_root, str) or not re.fullmatch('[0-9a-f]{64}', expected_root):
        raise ValueError('EXPLICIT_ROOT_REQUIRED')
    m = study.manifest
    # Refuse role/window/identity before any journal/payload access.
    if m['role'] != 'VALIDATION' or m['evidence_mode'] != 'PROSPECTIVE':
        raise ValueError('VALIDATION_PROSPECTIVE_REQUIRED')
    if m['collection_origin'] not in ('REALTIME', 'SYNTHETIC_TEST'):
        raise ValueError('UNKNOWN_ORIGIN')
    if (m['dataset_id'] != expected_dataset or m['baseline_git_sha'] != APPROVED
            or m['baseline']['collector_git_sha'] != expected_collector):
        raise ValueError('IDENTITY_MISMATCH')
    if not timestamp(m['collection_end']) or now < m['collection_end']:
        raise ValueError('WINDOW_NOT_ENDED')
    index = read(study.path('sealed.json'))
    if index['dataset_root_hash'] != expected_root:
        raise ValueError('ROOT_MISMATCH')
    before = fingerprint(study)
    proof = study.verify(require_sealed=True)
    if proof['valid'] is not True or proof['sealed'] is not True:
        raise ValueError('VERIFICATION_REQUIRED')
    events = study.events()
    observations = [e['payload'] for e in events if e['kind'] == 'OBSERVATION']
    counts = {path: sum(present(o, path) for o in observations) for path in FIELDS}
    issues = Counter()
    for o in observations:
        p = o['payload']
        if not all(timestamp(o.get(k)) for k in ('source_at', 'received_at', 'processed_at')):
            issues['INVALID_TIMESTAMP'] += 1
        elif not m['collection_start'] <= o['source_at'] <= o['received_at'] <= o['processed_at'] < m['collection_end']:
            issues['CAUSAL_WINDOW_MISMATCH'] += 1
        if (not timestamp(p.get('market_start')) or not timestamp(p.get('market_end'))
                or p['market_end'] - p['market_start'] != 300000
                or not p['market_start'] <= o['received_at'] < p['market_end']):
            issues['MARKET_WINDOW_MISMATCH'] += 1
        if p.get('quote_type') != 'YES_BOOK':
            issues['UNKNOWN_PRICE_SEMANTICS'] += 1
        if p.get('rule_hash') != digest(m['source_specs'][0]['rule_profile']):
            issues['RULE_PROFILE_MISMATCH'] += 1
        try:
            levels = []
            for side in ('bids', 'asks'):
                rows = p[side]
                if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
                    raise ValueError('invalid depth')
                if any(not isinstance(r, list) or len(r) != 2 for r in rows):
                    raise ValueError('invalid level')
                parsed = [(Decimal(str(r[0])), Decimal(str(r[1]))) for r in rows]
                if any(not price.is_finite() or not quantity.is_finite()
                       or not 0 < price < 1 or not 0 < quantity <= Decimal('1e18')
                       for price, quantity in parsed):
                    raise ValueError('invalid level')
                levels.append(parsed)
            if max(p for p, q in levels[0]) > min(p for p, q in levels[1]):
                raise ValueError('crossed book')
        except (KeyError, TypeError, ValueError, InvalidOperation):
            issues['BOOK_REQUIRES_REJECTION_OR_REVIEW'] += 1
    beats = [e['payload'] for e in events if e['kind'] == 'HEARTBEAT']
    profile = m['source_specs'][0]['rule_profile']
    study.verify(require_sealed=True)
    if before != fingerprint(study):
        raise ValueError('EVIDENCE_CHANGED_DURING_AUDIT')
    return dict(schema='m10-binding-audit-v1', study_id=m['study_id'],
                dataset_id=m['dataset_id'], dataset_root_hash=expected_root,
                collector_git_sha=expected_collector, baseline_git_sha=APPROVED,
                role=m['role'], evidence_mode=m['evidence_mode'], origin=m['collection_origin'],
                collection_start=m['collection_start'], collection_end=m['collection_end'],
                verification=proof, evidence_bytes_unchanged=True,
                observations=len(observations), field_presence=counts,
                structural_issues=dict(sorted(issues.items())),
                heartbeat_count=len(beats), heartbeat_fields={k: sum(present(b, k) for b in beats)
                    for k in ('source_health', 'last_received_at', 'baseline_valid', 'storage', 'clock_offset')},
                profile_checks=dict(yes_is_up=profile.get('yes_is_up') is True,
                    chainlink_declared=profile.get('feed') == 'CHAINLINK',
                    cycle_300000=profile.get('cycle_ms') == 300000,
                    description_hash_present=present(profile, 'description_hash')),
                readiness='NOT_READY', replay_allowed=False,
                blockers=['EXPLICIT_PREDICTION_BINDING_REQUIRED', 'SETTLEMENT_BINDING_REQUIRED',
                          'REAL_M8_SEMANTICS_UNSUPPORTED', 'CAUSAL_MARKET_STATUS_AND_HEALTH_REQUIRED'],
                limitations=['FIELD_PRESENCE_IS_NOT_SEMANTIC_VALIDITY',
                             'NO_PERFORMANCE_OR_REPLAY', 'NO_OUTCOME_INFERENCE'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('project-root', 'study', 'expected-root', 'expected-dataset', 'expected-collector'):
        p.add_argument('--' + name, required=True)
    p.add_argument('--now', required=True, type=int)
    a = p.parse_args()
    try:
        result = audit_sealed(Study(a.project_root, a.study), now=a.now,
            expected_root=a.expected_root, expected_dataset=a.expected_dataset,
            expected_collector=a.expected_collector)
        print(json.dumps(result, sort_keys=True))
    except Exception:
        print(json.dumps({'readiness': 'NOT_READY', 'error': 'AUDIT_REFUSED'}))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
