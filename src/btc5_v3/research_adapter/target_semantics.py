"""M10.2 typed offline entry point. Never converts three classes to M8 binary."""
import json

from btc5_v3.encoding import digest, identifier
from btc5_v3.target_semantics.lab import Contract, Outcome, Point, analyze, calibration


def seal_offline(records):
    """Synthetic envelope only; not a M9 Study, signature or prospective archive."""
    payload = dict(schema_version=1, origin='SYNTHETIC_TEST', role='VALIDATION',
                   evidence_mode='OFFLINE_SYNTHETIC', records=records)
    return dict(status='SEALED', payload=payload, root_hash=digest(payload))


def adapt_offline(envelope, *, expected_root):
    result = dict(status='NOT_READY', real_status='REAL_DATA_NOT_READY',
                  real_compatibility='TARGET_MISMATCH', origin='SYNTHETIC_TEST',
                  reasons=[], rows=[], calibration={}, verified=False)
    try:
        # Snapshot caller data; never mutate source or trust cached analytical fields.
        e = json.loads(json.dumps(envelope, allow_nan=False))
        p = e['payload']
        if (p['schema_version'] != 1 or p['origin'] != 'SYNTHETIC_TEST'
                or p['role'] != 'VALIDATION' or p['evidence_mode'] != 'OFFLINE_SYNTHETIC'):
            raise ValueError('OFFLINE_SYNTHETIC_ONLY')
        if e['status'] != 'SEALED':
            raise ValueError('SEALED_REQUIRED')
        if not isinstance(expected_root, str) or e['root_hash'] != expected_root or digest(p) != expected_root:
            raise ValueError('ROOT_MISMATCH')
        records = p['records']
        if not isinstance(records, list) or not 1 <= len(records) <= 1000:
            raise ValueError('RECORD_BUDGET_OR_EMPTY')
        ids = [identifier(r['id']) for r in records]
        if len(set(ids)) != len(ids):
            raise ValueError('DUPLICATE_RECORD_ID')
        result.update(verified=True, root_hash=expected_root)
        eligible = {}
        for record in sorted(records, key=lambda r:r['id']):
            row = dict(id=record['id'], status='REJECTED', reasons=[], scores_included=False)
            try:
                contract = Contract(**record['contract'])
                if not isinstance(record['points'], list) or not 1 <= len(record['points']) <= 1000:
                    raise ValueError('invalid points')
                points = tuple(Point(**v) for v in record['points'])
                outcome = Outcome(**record['outcome']) if record['outcome'] is not None else None
                pred = record['prediction']
                analysis = analyze(points, contract, pred['generated_at'], pred['probabilities'], outcome,
                    analysis_at=record['analysis_at'], end_offset_ms=record['end_offset_ms'],
                    max_delay_ms=record['max_delay_ms'])
                reasons = set(analysis['reasons'])
                if pred['input_hash'] != analysis['prediction']['input_hash']:
                    reasons.add('PREDICTION_INPUT_BINDING_MISMATCH')
                if not record['quality'] == 'VALID':
                    reasons.add('DATA_QUALITY_NOT_VALID')
                row.update(feed=contract.feed, market_id=contract.market_id,
                    probabilities=analysis['prediction']['probabilities'],
                    prediction=analysis['prediction'], posthoc_label=analysis['posthoc_label'],
                    quality=record['quality'], reasons=sorted(reasons),
                    confidence=dict(kind='MAX_CLASS_PROBABILITY_NOT_CONFIDENCE_INTERVAL',
                                    value=max(float(x) for x in pred['probabilities'].values())),
                    input_age_ms=max((pred['generated_at']-point.source_at for point in points
                        if contract.start <= point.source_at < contract.end
                        and point.available_at <= pred['generated_at']), default=None))
                if not reasons:
                    row.update(status='ACCEPTED', scores_included=True)
                    # Do not mix feeds/rule variants/boundary hypotheses in calibration.
                    group = f'{contract.feed}:{contract.rule_id}:end{record["end_offset_ms"]}'
                    eligible.setdefault(group, []).append(analysis)
            except (ValueError, KeyError, TypeError, ArithmeticError, OverflowError):
                row['reasons'] = ['INVALID_OR_MISSING_RECORD_BINDING']
            result['rows'].append(row)
        result['calibration'] = {g:calibration(rows) for g,rows in sorted(eligible.items())}
        result['accepted'] = sum(r['scores_included'] for r in result['rows'])
        result['rejected'] = len(result['rows'])-result['accepted']
        result['status'] = 'SYNTHETIC_READY' if result['accepted'] else 'NOT_READY'
        result['reasons'] = [] if result['accepted'] else ['NO_SCOREABLE_ROWS']
        result['report_hash'] = digest(result)
        return result
    except (ValueError, KeyError, TypeError, ArithmeticError, OverflowError):
        # No untrusted payload/exception strings cross this boundary.
        return dict(status='NOT_READY', real_status='REAL_DATA_NOT_READY',
                    real_compatibility='TARGET_MISMATCH', origin='UNVERIFIED',
                    reasons=['ENVELOPE_INTEGRITY_OR_ELIGIBILITY_FAILURE'],
                    rows=[], calibration={}, verified=False)
