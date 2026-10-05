"""Audit regression uses only temporary synthetic archives, never the real study."""
import socket
import pytest
from btc5_v3.encoding import canonical, digest
from btc5_v3.prospective.store import Study, Writer, read
from btc5_v3.prospective.models import definition
from btc5_v3.prospective.sources import source_spec
from btc5_v3.prospective.identity import APPROVED
from btc5_v3.research_adapter.binding_audit import audit_sealed, fingerprint


def setup(root, **payload_changes):
    proof = dict(baseline_git_sha=APPROVED, collector_git_sha='a'*40, branch='synthetic',
                 baseline_config_hash=digest('fixture'))
    profile = dict(feed='CHAINLINK', yes_is_up=True, cycle_ms=300000, description_hash=digest('fixture'))
    spec = source_spec('synthetic', profile=profile)
    study = Study(root, 'synthetic-audit')
    study.create(definition('synthetic-audit', 'synthetic-dataset', 1, 300000, 600000,
                            spec, proof, 'SYNTHETIC_TEST'))
    study.arm(2, proof)
    at = [300000]
    payload = dict(bids=[['0.4','10']], asks=[['0.6','10']], rule_hash=digest(profile),
                   feed='CHAINLINK', symbol='BTCUSDT', market_start=300000,
                   market_end=600000, quote_type='YES_BOOK')
    payload.update(payload_changes)
    with Writer(study, lambda: proof, lambda: at[0]) as writer:
        writer.observation('synthetic', 'event', 300000, 300000, payload, 'market')
        writer.heartbeat()
        at[0] = 600000
        writer.seal()
    return study


def run(study, **changes):
    args = dict(now=600000, expected_root=read(study.path('sealed.json'))['dataset_root_hash'],
                expected_dataset='synthetic-dataset', expected_collector='a'*40)
    args.update(changes)
    return audit_sealed(study, **args)


def test_presence_is_not_readiness_and_no_mutation(tmp_path):
    s = setup(tmp_path); before = fingerprint(s)
    result = run(s)
    assert result == run(s)
    assert result['verification']['sealed'] and result['evidence_bytes_unchanged']
    assert result['field_presence']['payload.prediction'] == 0
    assert result['field_presence']['payload.outcome'] == 0
    assert result['field_presence']['payload.bids'] == 1
    assert result['readiness'] == 'NOT_READY' and result['replay_allowed'] is False
    assert result['structural_issues'] == {}
    assert fingerprint(s) == before


@pytest.mark.parametrize('changes', [dict(expected_root='f'*64), dict(expected_root=None),
    dict(expected_dataset='other'), dict(expected_collector='b'*40), dict(now=599999), dict(now=True)])
def test_explicit_gates(tmp_path, changes):
    with pytest.raises(ValueError): run(setup(tmp_path), **changes)


@pytest.mark.parametrize('field,value', [('role','BLIND'), ('role','DEVELOPMENT'),
    ('evidence_mode','UNKNOWN'), ('collection_origin','UNKNOWN'), ('baseline_git_sha','b'*40)])
def test_role_and_identity_gate_before_payload(tmp_path, monkeypatch, field, value):
    s = setup(tmp_path); m = s.manifest; m[field] = value
    s.path('manifest.json').write_text(canonical(m), encoding='utf-8')
    def no_payload(*args, **kwargs): raise AssertionError('payload accessed')
    monkeypatch.setattr(Study, 'verify', no_payload)
    monkeypatch.setattr(Study, 'events', no_payload)
    with pytest.raises(ValueError): run(s)


@pytest.mark.parametrize('target', ['sealed.json','segment-000001.json','journal-000001.sqlite'])
def test_tampered_archive(tmp_path, target):
    s = setup(tmp_path); expected = read(s.path('sealed.json'))['dataset_root_hash']
    s.path(target).write_bytes(b'broken')
    with pytest.raises(Exception):
        audit_sealed(s, now=600000, expected_root=expected,
                     expected_dataset='synthetic-dataset', expected_collector='a'*40)


def test_unsealed_refused(tmp_path):
    s = setup(tmp_path); s.path('sealed.json').unlink()
    with pytest.raises(FileNotFoundError):
        audit_sealed(s, now=600000, expected_root='a'*64,
                     expected_dataset='synthetic-dataset', expected_collector='a'*40)


@pytest.mark.parametrize('changes', [dict(bids=[]),dict(asks=None),dict(bids=[['NaN','2']]),
    dict(asks=[['0.3','2']]),dict(bids=[['0','2']]),dict(asks=[['0.6','0']])])
def test_unusable_depth_preserved_in_audit(tmp_path, changes):
    result = run(setup(tmp_path, **changes))
    assert result['structural_issues']['BOOK_REQUIRES_REJECTION_OR_REVIEW'] == 1
    assert not result['replay_allowed']


def test_no_network_no_price_or_prediction_disclosure(tmp_path, monkeypatch):
    s = setup(tmp_path, prediction={'p_yes':'0.123456789'})
    def no_network(*args, **kwargs): raise AssertionError('network')
    monkeypatch.setattr(socket, 'socket', no_network)
    result = run(s)
    assert result['field_presence']['payload.prediction'] == 1
    assert not result['replay_allowed']
    assert '0.123456789' not in canonical(result)


def test_evidence_mutation_during_inspection_fails(tmp_path, monkeypatch):
    s = setup(tmp_path); original = Study.events
    def changed(self):
        events = original(self)
        self.path('unexpected.json').write_text('{}')
        return events
    monkeypatch.setattr(Study, 'events', changed)
    with pytest.raises(ValueError, match='EVIDENCE_CHANGED'): run(s)
