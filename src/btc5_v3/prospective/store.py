"""Append-only evidence journals and verifiable, atomic segment publication."""
from contextlib import contextmanager, closing
import json
import os
from pathlib import Path
import sqlite3

from btc5_v3.config.models import StorageConfig
from btc5_v3.encoding import canonical, digest, identifier, timestamp
from btc5_v3.monitoring.diagnostics import redact
from .identity import APPROVED
from .models import CYCLE_MS, HEARTBEAT_MS, SEGMENT_MS, safe_payload


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def atomic(path, value):
    """Caller holds writer lock. Never overwrite an existing published artifact."""
    if path.exists():
        raise ValueError('IMMUTABLE_ARTIFACT')
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('wb') as out:
        out.write(canonical(value).encode('utf-8'))
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, path)
    if os.name != 'nt':
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


@contextmanager
def lock(path):
    with path.open('a+b') as f:
        if os.fstat(f.fileno()).st_size == 0:
            f.write(b'0'); f.flush()
        f.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError('WRITER_ALREADY_RUNNING') from None
        try:
            yield
        finally:
            f.seek(0)
            if os.name == 'nt':
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f, fcntl.LOCK_UN)


def rows(path):
    if not path.exists():
        return []
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        result = [json.loads(r[0]) for r in db.execute('SELECT value FROM events ORDER BY seq')]
    previous = None
    for n, row in enumerate(result, 1):
        body = {k: v for k, v in row.items() if k != 'hash'}
        if row['seq'] != n or row['previous'] != previous or row['hash'] != digest(body):
            raise ValueError('JOURNAL_INTEGRITY_FAILURE')
        previous = row['hash']
    return result


def append(path, kind, at, payload):
    if not timestamp(at):
        raise ValueError('INVALID_TIME')
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY,value TEXT NOT NULL)')
        for action in ('UPDATE', 'DELETE'):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS no_{action.lower()} BEFORE {action} ON events BEGIN SELECT RAISE(ABORT,'append only'); END")
        db.execute('BEGIN IMMEDIATE')
        last = db.execute('SELECT value FROM events ORDER BY seq DESC LIMIT 1').fetchone()
        last = json.loads(last[0]) if last else None
        row = dict(seq=last['seq'] + 1 if last else 1, previous=last['hash'] if last else None,
                   kind=kind, at=at, payload=payload)
        row['hash'] = digest(row)
        db.execute('INSERT INTO events VALUES(?,?)', (row['seq'], canonical(row)))
    return row


class Study:
    def __init__(self, root, study_id):
        # Stricter directory name than general domain identifiers (no dot aliases).
        identifier(study_id)
        if study_id in ('.', '..') or ':' in study_id:
            raise ValueError('UNSAFE_STUDY_ID')
        self.root = Path(root).resolve()
        self.folder = self.path_for(study_id, 'manifest.json').parent

    def path_for(self, study_id, name):
        return StorageConfig(self.root, Path('runtime/v3/prospective') / study_id / name).resolved_path()

    def path(self, name):
        return StorageConfig(self.root, self.folder / name).resolved_path()

    @property
    def manifest(self):
        return read(self.path('manifest.json'))

    def create(self, draft):
        if canonical(draft)!=canonical(redact(draft)):
            raise ValueError('UNSAFE_MANIFEST')
        if draft['study_id'] != self.folder.name:
            raise ValueError('STUDY_ID_MISMATCH')
        self.folder.parent.mkdir(parents=True, exist_ok=True)
        catalog_lock=StorageConfig(self.root,self.folder.parent/'catalog.lock').resolved_path()
        with lock(catalog_lock):
            for other in self.folder.parent.glob('*/draft.json'):
                checked=StorageConfig(self.root,other).resolved_path()
                if read(checked)['dataset_id']==draft['dataset_id']:
                    raise ValueError('DATASET_ID_ALREADY_EXISTS')
            self.folder.mkdir(parents=True, exist_ok=False)
            atomic(self.path('draft.json'), draft)

    def mutable(self):
        if self.path('sealed.json').exists():
            raise ValueError('SEALED_IMMUTABLE')

    def arm(self, at, proof):
        with lock(self.path('writer.lock')):
            self.mutable()
            draft = read(self.path('draft.json'))
            if not draft['created_at'] <= at < draft['collection_start']:
                raise ValueError('FUTURE_WINDOW_REQUIRED')
            if draft['baseline'] != proof or proof['baseline_git_sha'] != APPROVED:
                raise ValueError('BASELINE_CHANGED')
            manifest = dict(draft, armed_at=at)
            atomic(self.path('manifest.json'), manifest)
            append(self.path('registry.sqlite'), 'ARMED', at, {'manifest_hash': digest(manifest)})

    def _segment(self, number, previous):
        events = rows(self.path(f'journal-{number:06d}.sqlite'))
        return dict(segment_id=number, schema_version=1, baseline_git_sha=APPROVED,
                    manifest_hash=digest(self.manifest), previous_segment_hash=previous,
                    boundary_start=(events[0]['at'] // SEGMENT_MS) * SEGMENT_MS if events else None,
                    boundary_end=(events[0]['at'] // SEGMENT_MS + 1) * SEGMENT_MS if events else None,
                    first_at=events[0]['at'] if events else None, last_at=events[-1]['at'] if events else None,
                    count=len(events), content_hash=digest(events), events=events)

    def verify(self, *, require_sealed=False):
        m = self.manifest
        registry = rows(self.path('registry.sqlite'))
        if not registry or registry[0]['kind'] != 'ARMED' or registry[0]['payload']['manifest_hash'] != digest(m):
            raise ValueError('MANIFEST_INTEGRITY_FAILURE')
        if m['baseline_git_sha'] != APPROVED or m['baseline']['baseline_git_sha'] != APPROVED:
            raise ValueError('BASELINE_CHANGED')
        if m['role'] != 'VALIDATION' or m['evidence_mode'] != 'PROSPECTIVE':
            raise ValueError('EVIDENCE_ROLE_MISMATCH')
        closed = [r['payload'] for r in registry if r['kind'] == 'SEGMENT_CLOSED']
        journals = sorted(self.folder.glob('journal-*.sqlite'))
        if ([p.name for p in journals] != [f'journal-{n:06d}.sqlite' for n in range(1,len(journals)+1)]
                or len(journals) not in (len(closed),len(closed)+1)):
            raise ValueError('JOURNAL_SEQUENCE_FAILURE')
        for n in range(1,len(journals)+1):
            rows(self.path(f'journal-{n:06d}.sqlite'))
        if any(p.name not in {f'segment-{n:06d}.json' for n in range(1,len(journals)+1)}
               for p in self.folder.glob('segment-*.json')):
            raise ValueError('UNEXPECTED_SEGMENT')
        previous = None
        for n, entry in enumerate(closed, 1):
            path = self.path(f'segment-{n:06d}.json')
            if entry['number'] != n or not path.exists():
                raise ValueError('MISSING_OR_REORDERED_SEGMENT')
            actual = read(path)
            if actual != self._segment(n, previous) or digest(actual) != entry['hash']:
                raise ValueError('SEGMENT_INTEGRITY_FAILURE')
            previous = entry['hash']
        sealed = self.path('sealed.json').exists()
        if sealed:
            index = read(self.path('sealed.json'))
            body = {k: v for k, v in index.items() if k != 'dataset_root_hash'}
            if (index['dataset_root_hash'] != digest(body) or index['manifest_hash'] != digest(m)
                    or index['segment_hashes'] != [c['hash'] for c in closed]
                    or index['registry_hash'] != registry[-1]['hash']
                    or index['sealed_at'] < m['collection_end']):
                raise ValueError('SEAL_INTEGRITY_FAILURE')
            if len(list(self.folder.glob('journal-*.sqlite'))) != len(closed) or len(list(self.folder.glob('segment-*.json'))) != len(closed):
                raise ValueError('UNSEALED_SEGMENT')
        elif require_sealed:
            raise ValueError('SEALED_DATASET_REQUIRED')
        return dict(valid=True, sealed=sealed, manifest_hash=digest(m), segments=len(closed),
                    last_segment_hash=previous)

    def events(self):
        # Read-only, raw evidence API. Operational UI never returns these payloads.
        result = []
        for path in sorted(self.folder.glob('journal-*.sqlite')):
            result.extend(rows(self.path(path.name)))
        return result

    def status(self, at):
        if not self.path('manifest.json').exists():
            d = read(self.path('draft.json'))
            return dict(study_id=d['study_id'], state='DRAFT', collection_start=d['collection_start'], collection_end=d['collection_end'])
        m = self.manifest
        try:
            integrity = self.verify()
            events = self.events()
            registry = rows(self.path('registry.sqlite'))
        except (ValueError, OSError, sqlite3.Error, KeyError):
            return dict(study_id=m['study_id'], state='INVALID', integrity='FAILED')
        obs = [e for e in events if e['kind'] == 'OBSERVATION']
        heartbeats = [e for e in events if e['kind'] == 'HEARTBEAT']
        elapsed = max(0, min(at, m['collection_end']) - m['collection_start'])
        cycles = (elapsed + CYCLE_MS - 1) // CYCLE_MS
        observed = len({(e['payload']['received_at'] - m['collection_start']) // CYCLE_MS for e in obs})
        poll_ms = m['source_specs'][0]['poll_ms']
        expected_polls = (elapsed+poll_ms-1)//poll_ms
        poll_slots = {(e['payload']['received_at']-m['collection_start'])//poll_ms for e in obs}
        state = registry[-1]['kind']
        states = [r['kind'] for r in registry if r['kind'] in ('ARMED', 'COLLECTING', 'DEGRADED', 'INTERRUPTED', 'WINDOW_ENDED')]
        state = 'SEALED' if integrity['sealed'] else states[-1]
        last = heartbeats[-1]['at'] if heartbeats else None
        gaps = [e['payload'] for e in events if e['kind'] == 'GAP']
        covered = set()
        for e in heartbeats:
            if m['collection_start'] <= e['at'] < min(at, m['collection_end']):
                covered.add((e['at'] - m['collection_start']) // HEARTBEAT_MS)
        return dict(study_id=m['study_id'], dataset_id=m['dataset_id'], role=m['role'], evidence_mode=m['evidence_mode'],
                    collection_origin=m['collection_origin'], baseline_git_sha=m['baseline_git_sha'],
                    collector_git_sha=m['baseline']['collector_git_sha'], state=state,
                    collection_start=m['collection_start'], collection_end=m['collection_end'],
                    observations=len(obs), diagnostics=sum(e['kind'] == 'DIAGNOSTIC' for e in events),
                    expected_elapsed_cycles=cycles, observed_cycles=observed, missing_cycles=max(0, cycles-observed),
                    expected_poll_slots=expected_polls, observed_poll_slots=len(poll_slots),
                    missing_poll_slots=max(0,expected_polls-len(poll_slots)),
                    coverage=observed / cycles if cycles else None,
                    last_observation_at=obs[-1]['payload']['received_at'] if obs else None,
                    last_heartbeat_at=last, heartbeat_age_ms=at-last if last is not None else None,
                    heartbeat_observed_ms=min(elapsed, len(covered)*HEARTBEAT_MS),
                    source_health=heartbeats[-1]['payload']['source_health'] if heartbeats else 'UNKNOWN',
                    interruptions=[dict(at=r['at'],**r['payload']) for r in registry if r['kind']=='INTERRUPTED'],
                    gaps=gaps, integrity=integrity)


class Writer:
    """One process, one study. Clock/proof injection is for synthetic tests only."""
    def __init__(self, study, proof, clock, *, fault=None):
        self.study, self.proof, self.clock, self.fault = study, proof, clock, fault
        self.number = None
        self.dedup = {}
        self.source_health = 'UNKNOWN'
        self.last_received = None
        self.failure_start = None
        self.last_event_at = None
        self.gap_ids = set()
        self.closed_count = 0
        self.segment_boundary = None

    def __enter__(self):
        self.guard = lock(self.study.path('writer.lock')); self.guard.__enter__()
        try:
            self.study.mutable(); self.study.verify()
            self.m = self.study.manifest
            self._identity()
            self._recover()
            self._restart_gap()
            return self
        except BaseException:
            self.guard.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        self.guard.__exit__(*args)

    def _identity(self):
        self.study.mutable()
        try:
            same = self.proof() == self.study.manifest['baseline']
        except Exception:
            same = False
        if not same:
            append(self.study.path('registry.sqlite'), 'INTERRUPTED', self.clock(), {'reason': 'BASELINE_CHANGED'})
            raise ValueError('BASELINE_CHANGED')

    def _recover(self):
        info = self.study.verify()
        closed = info['segments']
        self.closed_count=closed
        journals = sorted(self.study.folder.glob('journal-*.sqlite'))
        expected = [f'journal-{n:06d}.sqlite' for n in range(1, len(journals)+1)]
        if [p.name for p in journals] != expected or len(journals) > closed+1:
            raise ValueError('JOURNAL_SEQUENCE_FAILURE')
        for e in self.study.events():
            self.last_event_at=e['at']
            if e['kind']=='GAP':self.gap_ids.add(e['payload']['gap_id'])
            if e['kind'] in ('OBSERVATION', 'DIAGNOSTIC') and 'event_key' in e['payload']:
                p = e['payload']; self.dedup[(p['source'], p['event_key'])] = p['identity_hash']
                self.last_received = p['received_at']
            if e['kind']=='DIAGNOSTIC' and e['payload'].get('reason') in ('CONNECTION_FAILURE','AUTH_MISSING_OR_FAILED','NO_ACTIVE_MARKET','MALFORMED_SOURCE'):
                self.failure_start=e['at']; self.source_health='FAILED'
            if e['kind']=='GAP' and e['payload']['type']=='SOURCE_CONNECTION_FAILURE':
                self.failure_start=None
        # A partial publication is never accepted as complete evidence.
        partials=0
        for temp in sorted(self.study.folder.glob('*.tmp')):
            target = self.study.path(temp.name + '.quarantined')
            if target.exists():
                target = self.study.path(temp.name + '.' + digest(temp.read_bytes().hex()) + '.quarantined')
            os.replace(self.study.path(temp.name), target)
            partials+=1
        if len(journals) == closed+1:
            self.number = closed+1
            self.finalize()
        if partials:
            self._write('DIAGNOSTIC', {'reason':'PARTIAL_PUBLICATION_QUARANTINED','count':partials})
        registry = rows(self.study.path('registry.sqlite'))
        interruptions = [r for r in registry if r['kind'] == 'INTERRUPTED']
        if interruptions and interruptions[-1]['payload']['reason'] != 'EXPLICIT_STOP' and self.clock()<self.m['collection_end']:
            raise ValueError('TERMINAL_INTERRUPTION')
        if any(r['kind'] == 'WINDOW_ENDED' for r in registry):
            self.ended = True
        else:
            self.ended = False

    def _restart_gap(self):
        if self.ended:
            return
        events = self.study.events()
        beats = [e for e in events if e['kind'] == 'HEARTBEAT']
        last = beats[-1]['at'] if beats else None
        since = max(self.m['collection_start'], last+HEARTBEAT_MS if last is not None else self.m['collection_start'])
        old_gaps=[e['payload']['observed_resume'] for e in events if e['kind']=='GAP' and e['payload']['source']=='collector']
        if old_gaps:since=max(since,max(old_gaps))
        now = min(self.clock(), self.m['collection_end'])
        registry = rows(self.study.path('registry.sqlite'))
        explicit = registry[-1]['kind'] == 'INTERRUPTED' and registry[-1]['payload']['reason'] == 'EXPLICIT_STOP'
        if now > since:
            self.gap(since, now, 'COLLECTOR_DOWN' if explicit else 'UNKNOWN', last)

    def _write(self, kind, payload, *, at=None):
        self.study.mutable()
        at = self.clock() if at is None else at
        if self.last_event_at is not None and at<self.last_event_at:
            append(self.study.path('registry.sqlite'),'INTERRUPTED',self.last_event_at,
                   {'reason':'LOCAL_CLOCK_REVERSED','detected_at':at})
            raise ValueError('LOCAL_CLOCK_REVERSED')
        if self.number is not None:
            if self.segment_boundary is not None and at//SEGMENT_MS != self.segment_boundary:
                self.finalize()
        if self.number is None:
            self.number = self.closed_count+1
            self.segment_boundary=at//SEGMENT_MS
        result = append(self.study.path(f'journal-{self.number:06d}.sqlite'), kind, at, payload)
        self.last_event_at=at
        if self.fault:
            self.fault('after_commit')
        return result

    def finalize(self):
        self.study.mutable()
        if self.number is None:
            return
        info = self.study.verify()
        segment = self.study._segment(self.number, info['last_segment_hash'])
        target = self.study.path(f'segment-{self.number:06d}.json')
        if target.exists():
            if read(target) != segment:
                raise ValueError('ORPHAN_SEGMENT_MISMATCH')
        else:
            atomic(target, segment)
        if self.fault:
            self.fault('after_segment_rename')
        append(self.study.path('registry.sqlite'), 'SEGMENT_CLOSED', self.clock(),
               {'number': self.number, 'hash': digest(segment)})
        self.closed_count=self.number
        self.number = None
        self.segment_boundary=None

    def gap(self, start, end, reason, last=None, source='collector'):
        self.study.mutable()
        if reason not in ('UNKNOWN','COLLECTOR_DOWN','SOURCE_CONNECTION_FAILURE','NO_EXPECTED_EVENT'):
            raise ValueError('UNSUPPORTED_GAP_REASON')
        if source not in ('collector',self.m['source_specs'][0]['name']):
            raise ValueError('UNDECLARED_SOURCE')
        if not all(timestamp(t) for t in (start,end)) or start<self.m['collection_start'] or end>self.m['collection_end']:
            raise ValueError('GAP_OUTSIDE_WINDOW')
        if end <= start:
            return
        payload = dict(source=source, dataset_id=self.m['dataset_id'], expected_start=start, observed_resume=end, duration_ms=end-start,
                       type=reason, reason=reason, detected_at=self.clock(), last_heartbeat_at=last)
        payload['gap_id'] = digest(dict(source=source,start=start,end=end,reason=reason,dataset_id=self.m['dataset_id']))
        if payload['gap_id'] in self.gap_ids:return
        self._write('GAP', payload)
        self.gap_ids.add(payload['gap_id'])

    def heartbeat(self):
        self.study.mutable(); self._identity()
        now = self.clock()
        if self.ended or now >= self.m['collection_end']:
            raise ValueError('WINDOW_ENDED')
        result = self._write('HEARTBEAT', dict(process_alive=True, source_health=self.source_health,
                          last_received_at=self.last_received, dataset_id=self.m['dataset_id'],
                          baseline_valid=True, storage='COMMITTED_TRANSACTION', clock_offset='UNKNOWN'))
        if now >= self.m['collection_start']:
            append(self.study.path('registry.sqlite'), 'DEGRADED' if self.source_health == 'FAILED' else 'COLLECTING', now, {})
        return result

    def observation(self, source, event_key, source_at, received_at, payload, market_id=None):
        self.study.mutable()
        now = self.clock()
        if self.ended or not self.m['collection_start'] <= received_at <= now < self.m['collection_end']:
            raise ValueError('OUTSIDE_PRESPECIFIED_WINDOW')
        identifier(source); identifier(str(event_key))
        if source != self.m['source_specs'][0]['name']:
            raise ValueError('UNDECLARED_SOURCE')
        if source_at is not None and not timestamp(source_at):
            raise ValueError('INVALID_SOURCE_TIME')
        if market_id is not None:
            identifier(str(market_id))
        safe = safe_payload(payload)
        key = (source, str(event_key))
        stable = digest(dict(source_at=source_at, payload=safe, market_id=market_id))
        quality = ('UNKNOWN_SOURCE_TIME' if source_at is None else
                   'PRE_WINDOW_SOURCE' if source_at < self.m['collection_start'] else
                   'FUTURE_SOURCE_TIME' if source_at > received_at else
                   'SOURCE_STALE' if received_at-source_at > HEARTBEAT_MS else 'RECEIVED')
        if key in self.dedup:
            if self.dedup[key] != stable:
                raise ValueError('DUPLICATE_IDENTITY_CONFLICT')
            self.source_health='OK' if quality=='RECEIVED' else 'STALE_OR_INVALID'
            if self.failure_start is not None:
                self.gap(self.failure_start,now,'SOURCE_CONNECTION_FAILURE',source=source)
                self.failure_start=None
            return False
        record = dict(source=source, event_key=str(event_key), source_at=source_at, received_at=received_at,
                      processed_at=now, market_id=market_id, cycle_id=received_at//CYCLE_MS,
                      quality=quality, payload=safe, identity_hash=stable)
        self._write('OBSERVATION' if quality == 'RECEIVED' else 'DIAGNOSTIC', record)
        self.dedup[key] = stable
        self.last_received = received_at
        self.source_health = 'OK' if quality == 'RECEIVED' else 'STALE_OR_INVALID'
        if self.failure_start is not None:
            self.gap(self.failure_start, now, 'SOURCE_CONNECTION_FAILURE', source=source)
            self.failure_start = None
        return True

    def source_failure(self, reason='CONNECTION_FAILURE'):
        self.study.mutable()
        if reason not in ('CONNECTION_FAILURE', 'AUTH_MISSING_OR_FAILED', 'NO_ACTIVE_MARKET', 'MALFORMED_SOURCE'):
            reason = 'CONNECTION_FAILURE'
        self.source_health = 'FAILED'
        if self.failure_start is None:
            self.failure_start = self.clock()
            self._write('DIAGNOSTIC', {'reason': reason, 'source': self.m['source_specs'][0]['name']})

    def stop(self, reason='EXPLICIT_STOP'):
        self.study.mutable()
        if reason not in ('EXPLICIT_STOP', 'RULE_CHANGED', 'BASELINE_CHANGED','LOCAL_CLOCK_REVERSED'):
            raise ValueError('INVALID_STOP_REASON')
        self.finalize()
        append(self.study.path('registry.sqlite'), 'INTERRUPTED', self.clock(), {'reason': reason})

    def end(self):
        self.study.mutable()
        if self.clock() < self.m['collection_end']:
            raise ValueError('WINDOW_NOT_ENDED')
        if not self.ended:
            self._restart_gap()
            if self.failure_start is not None:
                self.gap(self.failure_start, self.m['collection_end'], 'SOURCE_CONNECTION_FAILURE', source=self.m['source_specs'][0]['name'])
            # Missing receipt slots remain missing, even when the process was alive.
            # This ledger is about unique source events, not every successful HTTP poll.
            spec=self.m['source_specs'][0]; cadence=spec['poll_ms']; start=self.m['collection_start']; end=self.m['collection_end']
            slots=sorted({(e['payload']['received_at']-start)//cadence for e in self.study.events() if e['kind']=='OBSERVATION'})
            previous=-1
            for slot in [*slots,(end-start+cadence-1)//cadence]:
                if slot>previous+1:
                    self.gap(start+(previous+1)*cadence,min(end,start+slot*cadence),'NO_EXPECTED_EVENT',source=spec['name'])
                previous=slot
            self.finalize()
            append(self.study.path('registry.sqlite'), 'WINDOW_ENDED', self.clock(), {})
            self.ended = True

    def seal(self):
        self._identity(); self.end(); self.finalize(); self.study.verify()
        registry = rows(self.study.path('registry.sqlite'))
        hashes = [r['payload']['hash'] for r in registry if r['kind'] == 'SEGMENT_CLOSED']
        index = dict(schema_version=1, manifest_hash=digest(self.m), segment_hashes=hashes,
                     registry_hash=registry[-1]['hash'], sealed_at=self.clock(),
                     collection_start=self.m['collection_start'], collection_end=self.m['collection_end'],
                     record_count=len(self.study.events()), operational_coverage=self.study.status(self.clock()))
        index['dataset_root_hash'] = digest(index)
        atomic(self.study.path('sealed.json'), index)
        self.study.verify(require_sealed=True)
        return index
