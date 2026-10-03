"""A sealed validation candidate, never invented M8 predictions or settlements."""
from dataclasses import dataclass
from types import SimpleNamespace
from .store import read


@dataclass(frozen=True)
class ProspectiveDataset:
    manifest: object
    observations: tuple
    gaps: tuple
    dataset_root_hash: str
    readiness: str = 'NOT_REPLAY_READY_M8_BINDINGS_REQUIRE_EXPLICIT_RESEARCH_ADAPTER'

    def records(self):
        # M8 quality protocol: raw actual observations only. Absent predictions remain absent.
        return tuple(dict(id=f'prospective-{i}', at=o['processed_at'], sequence=i,
                          source_at=o['source_at'], received_at=o['received_at'],
                          available_at=o['processed_at'], source=o['source'], raw=o['payload'])
                     for i, o in enumerate(self.observations))


def load_sealed(study, now):
    study.verify(require_sealed=True)
    m = study.manifest
    if now < m['collection_end']:
        raise ValueError('WINDOW_NOT_ENDED')
    events = study.events()
    manifest = SimpleNamespace(dataset_id=m['dataset_id'], role=m['role'], evidence_mode=m['evidence_mode'],
                               collection_origin=m['collection_origin'], time_start=m['collection_start'],
                               time_end=m['collection_end'], created_at=m['created_at'],
                               cadence_ms=m['source_specs'][0]['poll_ms'], source=m['source_specs'][0]['name'],
                               baseline_git_sha=m['baseline_git_sha'], provenance=m)
    return ProspectiveDataset(manifest, tuple(e['payload'] for e in events if e['kind']=='OBSERVATION'),
                              tuple(e['payload'] for e in events if e['kind']=='GAP'),
                              read(study.path('sealed.json'))['dataset_root_hash'])
