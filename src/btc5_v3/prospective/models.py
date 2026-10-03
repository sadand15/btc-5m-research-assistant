"""Small immutable policy; safe payloads and operational events only."""
from btc5_v3.encoding import canonical,digest,identifier,timestamp
from btc5_v3.monitoring.diagnostics import redact

HEARTBEAT_MS=30000
SEGMENT_MS=3600000
CYCLE_MS=300000
SCHEMA=1
KINDS=('OBSERVATION','HEARTBEAT','GAP','DIAGNOSTIC')
PAYLOAD_FIELDS=('price','quantity','bids','asks','rule_hash','feed','symbol','market_start','market_end',
                'source_status','prediction','clock_offset_ms','clock_offset_basis','quote_type')


def safe_payload(payload):
    safe=redact({k:payload[k] for k in PAYLOAD_FIELDS if k in payload})
    if len(canonical(safe).encode())>262144:raise ValueError('EVIDENCE_TOO_LARGE')
    return safe


def definition(study_id,dataset_id,created_at,start,end,spec,proof,origin='REALTIME'):
    identifier(study_id);identifier(dataset_id)
    if not all(timestamp(x) for x in (created_at,start,end)) or not created_at<start<end or start%CYCLE_MS or end%CYCLE_MS:
        raise ValueError('FUTURE_ALIGNED_WINDOW_REQUIRED')
    if origin not in ('REALTIME','SYNTHETIC_TEST'):raise ValueError('EXPLICIT_ORIGIN_REQUIRED')
    if not isinstance(spec,dict) or set(spec)!= {'name','type','endpoint','symbol','timestamp_semantics','received_at_semantics','mode','poll_ms','rule_profile'}:
        raise ValueError('EXPLICIT_SOURCE_SPEC_REQUIRED')
    identifier(spec['name']);identifier(spec['type'])
    if canonical(redact(spec))!=canonical(spec):raise ValueError('UNSAFE_SOURCE_SPEC')
    if type(spec['poll_ms']) is not int or not 1000<=spec['poll_ms']<=60000:raise ValueError('BOUNDED_POLL_INTERVAL_REQUIRED')
    return dict(study_id=study_id,dataset_id=dataset_id,role='VALIDATION',evidence_mode='PROSPECTIVE',
       collection_origin=origin,timezone='UTC',created_at=created_at,collection_start=start,collection_not_before=start,
       collection_end=end,baseline=proof,baseline_git_sha=proof['baseline_git_sha'],branch=proof['branch'],
       schema_version=SCHEMA,collector_version='prospective-v1',source_specs=[spec],market_definitions={'cycle_ms':CYCLE_MS,'symbol':spec['symbol']},
       policies=dict(heartbeat_ms=HEARTBEAT_MS,segment_ms=SEGMENT_MS,gaps='PRESERVE_NO_BACKFILL',
                     sealing='END_VERIFY_ORDERED_ROOT_IMMUTABLE',redaction='ALLOWLIST_REDACT_NO_HEADERS'),
       notes='COLLECT_FIRST_ANALYZE_LATER; baseline domain unchanged; no real model inference is invented')
