"""Fail-closed scaffolding over the unchanged M9 integrity verifier.

An eligible evidence candidate is not a replay-ready dataset. In particular,
the M9 allowlist has no settlement binding. This module never invents one.
"""
from dataclasses import dataclass
import sqlite3

from btc5_v3.encoding import digest, timestamp
from btc5_v3.models.models import Prediction
from btc5_v3.prospective.adapter import load_sealed
from btc5_v3.prospective.identity import APPROVED
from btc5_v3.prospective.store import Study


@dataclass(frozen=True)
class AdapterResult:
    candidate_status: str
    readiness: str
    reasons: tuple[str, ...]
    missing_bindings: tuple[str, ...] = ()
    dataset_id: str | None = None
    dataset_root_hash: str | None = None
    manifest_hash: str | None = None
    collection_origin: str | None = None
    observation_count: int | None = None
    role: str | None = None
    evidence_mode: str | None = None
    baseline_git_sha: str | None = None

    @property
    def replay_allowed(self):
        # M10 scaffolding does not implement the final real-world binding.
        return False


def rejected(reason):
    return AdapterResult('REJECTED', 'NOT_READY', (reason,))


def inspect_synthetic_sealed(study: Study, *, now: int) -> AdapterResult:
    """Inspect an explicitly supplied synthetic study, never discover a path.

    Check role/mode/origin before invoking verification (which reads journals).
    REALTIME is deliberately blocked even when sealed until a later task.
    Only fixed reason codes leave this boundary, never exception text/payloads.
    """
    if type(study) is not Study or not timestamp(now):
        return rejected('INVALID_REQUEST')
    try:
        m = study.manifest
        if m['role'] != 'VALIDATION':
            return rejected('VALIDATION_REQUIRED')
        if m['evidence_mode'] != 'PROSPECTIVE':
            return rejected('PROSPECTIVE_REQUIRED')
        if m['collection_origin'] != 'SYNTHETIC_TEST':
            return rejected('REAL_DATA_ADAPTER_DEFERRED')
        if m['baseline_git_sha'] != APPROVED:
            return rejected('BASELINE_MISMATCH')
        if not timestamp(m['collection_end']) or now < m['collection_end']:
            return rejected('WINDOW_NOT_ENDED')
        if not study.path('sealed.json').is_file():
            return rejected('SEALED_REQUIRED')
        candidate = load_sealed(study, now)
        # Read twice to reject changes during this inspection. Hashes establish
        # integrity, not external authenticity or permission to run analysis.
        proof = study.verify(require_sealed=True)
        if not proof['valid'] or not proof['sealed'] or digest(m) != proof['manifest_hash']:
            return rejected('INTEGRITY_FAILURE')
        missing = {'SETTLEMENT_BINDING', 'MARKET_NORMALIZATION_BINDING',
                   'M8_RECORD_BINDING'}
        reasons = {'MISSING_BINDING'}
        if not candidate.observations:
            reasons.add('EMPTY_DATASET')
            missing.add('PREDICTION_BINDING')
        for observation in candidate.observations:
            payload = observation['payload']
            if not payload.get('prediction'):
                missing.add('PREDICTION_BINDING')
                continue
            try:
                p = Prediction.from_dict(payload['prediction'])
                if (p.market_id != observation['market_id']
                        or p.available_at > observation['processed_at']):
                    raise ValueError('incompatible archived input')
            except (ValueError, TypeError, KeyError, ArithmeticError, AttributeError):
                reasons.add('INVALID_PREDICTION_BINDING')
                missing.add('PREDICTION_BINDING')
        return AdapterResult(
            'ACCEPTED', 'NOT_READY', tuple(sorted(reasons)), tuple(sorted(missing)),
            m['dataset_id'], candidate.dataset_root_hash, proof['manifest_hash'],
            m['collection_origin'], len(candidate.observations), m['role'],
            m['evidence_mode'], m['baseline_git_sha'])
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError, ArithmeticError):
        return rejected('INTEGRITY_OR_SCHEMA_FAILURE')
