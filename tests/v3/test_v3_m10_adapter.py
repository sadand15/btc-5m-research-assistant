"""Synthetic temporary evidence only; no real archive or network access."""
from dataclasses import asdict
import socket

import pytest

from btc5_v3.encoding import canonical, digest
from btc5_v3.prospective.models import definition
from btc5_v3.prospective.sources import source_spec
from btc5_v3.prospective.identity import APPROVED
from btc5_v3.prospective.store import Study, Writer, read
from btc5_v3.research_adapter import inspect_synthetic_sealed


def fixture(root, *, seal=True, payload=None, empty=False):
    proof = dict(baseline_git_sha=APPROVED, collector_git_sha='a'*40,
                 branch='synthetic-test', baseline_config_hash=digest('fixture'))
    s = Study(root, 'm10-synthetic')
    s.create(definition('m10-synthetic', 'm10-synthetic-dataset', 1, 300000, 600000,
                        source_spec('synthetic'), proof, 'SYNTHETIC_TEST'))
    s.arm(2, proof)
    clock = [300000]
    with Writer(s, lambda: proof, lambda: clock[0]) as w:
        if not empty:
            w.observation('synthetic', 'event-one', 300000, 300000,
                          payload if payload is not None else {'price': '100'}, 'market-one')
        if seal:
            clock[0] = 600000
            w.seal()
    return s


def test_accepts_integrity_candidate_but_missing_binding_blocks_replay(tmp_path):
    s = fixture(tmp_path)
    before = {p.name: p.read_bytes() for p in s.folder.iterdir()}
    a = inspect_synthetic_sealed(s, now=600000)
    assert a.candidate_status == 'ACCEPTED'
    assert a.readiness == 'NOT_READY' and not a.replay_allowed
    assert a.reasons == ('MISSING_BINDING',)
    assert {'PREDICTION_BINDING', 'SETTLEMENT_BINDING'} <= set(a.missing_bindings)
    assert a.role == 'VALIDATION' and a.evidence_mode == 'PROSPECTIVE'
    assert a.collection_origin == 'SYNTHETIC_TEST' and a.observation_count == 1
    assert a.dataset_root_hash == read(s.path('sealed.json'))['dataset_root_hash']
    assert a == inspect_synthetic_sealed(s, now=600000)
    assert before == {p.name: p.read_bytes() for p in s.folder.iterdir()}


def test_unsealed_and_early_refused(tmp_path):
    s = fixture(tmp_path, seal=False)
    assert inspect_synthetic_sealed(s, now=600000).reasons == ('SEALED_REQUIRED',)
    assert inspect_synthetic_sealed(s, now=599999).reasons == ('WINDOW_NOT_ENDED',)


@pytest.mark.parametrize('target', ['manifest.json', 'sealed.json', 'segment-000001.json', 'journal-000001.sqlite'])
def test_tampering_refused(tmp_path, target):
    s = fixture(tmp_path)
    s.path(target).write_bytes(b'corrupt synthetic evidence')
    assert inspect_synthetic_sealed(s, now=600000).candidate_status == 'REJECTED'


@pytest.mark.parametrize('field,value,reason', [
    ('role', 'BLIND', 'VALIDATION_REQUIRED'),
    ('role', 'DEVELOPMENT', 'VALIDATION_REQUIRED'),
    ('evidence_mode', 'SYNTHETIC', 'PROSPECTIVE_REQUIRED'),
    ('collection_origin', 'REALTIME', 'REAL_DATA_ADAPTER_DEFERRED'),
    ('collection_origin', 'UNKNOWN', 'REAL_DATA_ADAPTER_DEFERRED'),
    ('baseline_git_sha', 'b'*40, 'BASELINE_MISMATCH'),
])
def test_gate_before_journal_access(tmp_path, monkeypatch, field, value, reason):
    s = fixture(tmp_path)
    m = s.manifest; m[field] = value
    s.path('manifest.json').write_text(canonical(m), encoding='utf-8')
    def prohibited(*args, **kwargs):
        raise AssertionError('payload accessed before metadata gate')
    monkeypatch.setattr(Study, 'verify', prohibited)
    monkeypatch.setattr(Study, 'events', prohibited)
    assert inspect_synthetic_sealed(s, now=600000).reasons == (reason,)


def test_malformed_prediction_not_promoted(tmp_path):
    s = fixture(tmp_path, payload={'prediction': {'p_yes': '.9'}})
    a = inspect_synthetic_sealed(s, now=600000)
    assert 'INVALID_PREDICTION_BINDING' in a.reasons
    assert not a.replay_allowed


def test_empty_not_ready(tmp_path):
    a = inspect_synthetic_sealed(fixture(tmp_path, empty=True), now=600000)
    assert 'EMPTY_DATASET' in a.reasons and not a.replay_allowed


def test_no_network_or_order_output(tmp_path, monkeypatch):
    def prohibited(*args, **kwargs):
        raise AssertionError('network forbidden')
    monkeypatch.setattr(socket, 'socket', prohibited)
    monkeypatch.setattr(socket, 'create_connection', prohibited)
    result = inspect_synthetic_sealed(fixture(tmp_path), now=600000)
    assert result.candidate_status == 'ACCEPTED'
    assert not {'order', 'wallet', 'payload', 'prediction', 'settlement'} & set(asdict(result))


@pytest.mark.parametrize('now', [True, -1, None, '600000'])
def test_invalid_clock(tmp_path, now):
    assert inspect_synthetic_sealed(fixture(tmp_path), now=now).reasons == ('INVALID_REQUEST',)
