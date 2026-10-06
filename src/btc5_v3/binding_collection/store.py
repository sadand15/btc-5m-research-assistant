"""Reuse M9 chain/transaction/publication/recovery in a separate schema namespace."""
from pathlib import Path

from btc5_v3.config.models import StorageConfig
from btc5_v3.encoding import digest, timestamp, canonical
from btc5_v3.monitoring.diagnostics import redact
from btc5_v3.prospective.store import Study, Writer, append, rows
from .schema import validate_manifest, require


class BindingStudy(Study):
    def path_for(self, study_id, name):
        require(study_id != 'prospective-001', 'LEGACY_STUDY_PROTECTED')
        return StorageConfig(self.root, Path('runtime/v3/binding') / study_id / name).resolved_path()

    def create(self, draft):
        validate_manifest(draft)
        super().create(draft)

    def _segment(self, number, previous):
        return dict(super()._segment(number, previous), schema_version=2, event_contract='binding-collection-v1')

    def verify(self, *, require_sealed=False):
        validate_manifest(self.manifest)
        return super().verify(require_sealed=require_sealed)

    def status(self, at):
        info = self.verify()
        events = self.events()
        markets = {e['payload']['market_id'] for e in events if e['kind']=='MARKET_STATE'}
        predicted = {e['payload']['market_id'] for e in events if e['kind']=='PREDICTION'}
        settled = {e['payload']['market_id'] for e in events if e['kind']=='SETTLEMENT'}
        return dict(valid=info['valid'], sealed=info['sealed'],
                    pending_predictions=sorted(markets-predicted), pending_settlements=sorted(markets-settled),
                    rejected_events=sum(e['kind']=='REJECTED' for e in events),
                    event_count=len(events), collection_start=self.manifest['collection_start'],
                    quote_end=self.manifest['quote_end'], followup_end=self.manifest['collection_end'],
                    phase='SEALED' if info['sealed'] else
                          'ENDED' if at >= self.manifest['collection_end'] else
                          'SETTLEMENT_FOLLOWUP' if at >= self.manifest['quote_end'] else
                          'ARMED' if at < self.manifest['collection_start'] else 'COLLECTION')


class BindingWriter(Writer):
    def __enter__(self):
        require(type(self.study) is BindingStudy, 'ISOLATED_BINDING_STUDY_REQUIRED')
        # Check before obtaining a lock: even writer.lock must not change post-seal.
        self.study.mutable()
        super().__enter__()
        self.ids = {e['payload']['id']: e for e in self.study.events() if 'id' in e['payload']}
        return self

    def _restart_gap(self):
        if self.ended:
            return
        events = self.study.events()
        now = min(self.clock(), self.m['collection_end'])
        since = max(self.m['collection_start'], events[-1]['at'] if events else self.m['collection_start'])
        if now > since:
            self.gap(since, now, 'UNKNOWN')

    def put(self, kind, payload):
        self._identity()
        now = self.clock()
        require(timestamp(now) and self.m['collection_start'] <= now < self.m['collection_end'],
                'OUTSIDE_FIXED_WINDOW')
        require(kind in ('MARKET_STATE','BTC_REFERENCE','BOOK','PREDICTION','SETTLEMENT','REJECTED'),
                'UNKNOWN_EVENT_KIND')
        if kind not in ('SETTLEMENT','REJECTED'):
            require(now < self.m['quote_end'], 'SETTLEMENT_ONLY_FOLLOWUP')
        require(timestamp(payload.get('available_at')) and payload['available_at'] <= now,
                'FUTURE_EVENT_AVAILABILITY')
        if kind == 'PREDICTION':
            require(payload['generated_at'] <= payload['available_at'] <= now < payload['market_end'],
                    'PREDICTION_COMMIT_AFTER_EXPIRY')
        require(canonical(redact(payload)) == canonical(payload), 'UNSAFE_BINDING_PAYLOAD')
        require(len(canonical(payload).encode()) <= 262144, 'EVENT_TOO_LARGE')
        key = payload['id']
        if key in self.ids:
            old = self.ids[key]
            require(old['kind'] == kind and old['payload'] == payload, 'EVENT_IDENTITY_CONFLICT')
            return old
        event = self._write(kind, payload, at=now)
        self.ids[key] = event
        return event

    def end(self):
        self.study.mutable()
        require(self.clock() >= self.m['collection_end'], 'FOLLOWUP_NOT_ENDED')
        if not self.ended:
            # Capture unobserved tail. No invented quotes/predictions/resolutions.
            self._restart_gap()
            self.finalize()
            append(self.study.path('registry.sqlite'), 'WINDOW_ENDED', self.clock(), {})
            self.ended = True

    def pending_markets(self):
        events = self.study.events()
        observed = {e['payload']['market_id'] for e in events if e['kind']=='MARKET_STATE'}
        settled = {e['payload']['market_id'] for e in events if e['kind']=='SETTLEMENT'}
        return sorted(observed - settled)
