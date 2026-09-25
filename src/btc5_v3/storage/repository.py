from dataclasses import asdict
import hashlib
import json
import sqlite3

from btc5_v3.encoding import canonical
from btc5_v3.market.models import RawMarketEvent
from btc5_v3.market.normalize import raw_event
from btc5_v3.market.validation import validate_market


class Repository:
    def __init__(self,db,config):self.db,self.config=db,config

    def register(self,experiment):
        if experiment.config_hash!=self.config.hash:raise ValueError('experiment config conflict')
        metadata=canonical(asdict(experiment));config=canonical(asdict(self.config))
        with self.db.connection as conn:
            conn.execute('BEGIN IMMEDIATE')
            old=conn.execute('SELECT * FROM experiments WHERE id=?',(experiment.id,)).fetchone()
            if old and (old['metadata_json']!=metadata or old['config_json']!=config):
                raise ValueError('experiment identity conflict')
            conn.execute('INSERT OR IGNORE INTO experiments VALUES (?,?,?,?)',
                         (experiment.id,self.config.hash,config,metadata))

    def _experiment(self,experiment_id):
        row=self.db.connection.execute('SELECT config_hash FROM experiments WHERE id=?',(experiment_id,)).fetchone()
        if row is None or row[0]!=self.config.hash:raise ValueError('unknown or incompatible experiment')

    def ingest(self,payload,*,experiment_id,source,received_at,sequence,evaluation_at,
               event_key=None,recorded_at=None,transport_metadata=None):
        self._experiment(experiment_id)
        event=raw_event(payload,experiment_id=experiment_id,source=source,received_at=received_at,
                        sequence=sequence,event_key=event_key,recorded_at=recorded_at,transport_metadata=transport_metadata)
        conn=self.db.connection
        # First durable transaction: never lose received data if validation crashes.
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            old=conn.execute('SELECT * FROM raw_market_events WHERE id=?',(event.id,)).fetchone()
            if old:
                if old['payload_hash']!=event.payload_hash:raise ValueError('upstream event content conflict')
                event=RawMarketEvent(**dict(old))
            else:
                fields=asdict(event)
                try:
                    conn.execute('INSERT INTO raw_market_events ('+','.join(fields)+') VALUES ('+
                                 ','.join('?' for _ in fields)+')',tuple(fields.values()))
                except sqlite3.IntegrityError as exc:raise ValueError('ingestion sequence conflict') from exc
        old_validation=conn.execute('SELECT * FROM market_validation_events WHERE raw_event_id=?',(event.id,)).fetchone()
        if old_validation:return self._verified_result(event,old_validation)
        result=validate_market(event,self.config,evaluation_at=evaluation_at)
        # One transaction for validation and snapshot. No half-accepted result.
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            existing=conn.execute('SELECT * FROM market_validation_events WHERE raw_event_id=?',(event.id,)).fetchone()
            if existing:return self._verified_result(event,existing)
            conn.execute('INSERT INTO market_validation_events VALUES (?,?,?,?,?,?,?,?,?)',
                         (result.validation_id,event.experiment_id,event.id,result.status,result.primary_reason,
                          canonical(result.all_reasons),result.validator_version,result.evaluation_at,result.context_hash))
            if result.snapshot:
                value=result.snapshot.to_json()
                conn.execute('INSERT INTO market_snapshots VALUES (?,?,?,?,?,?)',
                             (result.snapshot.snapshot_id,event.experiment_id,event.id,result.validation_id,
                              value,hashlib.sha256(value.encode()).hexdigest()))
        return result

    def _verified_result(self,event,row):
        self._experiment(event.experiment_id)
        result=validate_market(event,self.config,evaluation_at=row['evaluation_at'])
        expected=(result.validation_id,result.status,result.primary_reason,canonical(result.all_reasons),
                  result.validator_version,result.context_hash)
        stored=tuple(row[k] for k in ('id','status','primary_reason','reasons_json','validator_version','context_hash'))
        if expected!=stored:raise ValueError('validation integrity failure')
        snapshot=self.db.connection.execute('SELECT * FROM market_snapshots WHERE raw_event_id=?',(event.id,)).fetchone()
        if result.snapshot:
            value=result.snapshot.to_json()
            if (snapshot is None or snapshot['snapshot_json']!=value
                    or snapshot['snapshot_hash']!=hashlib.sha256(value.encode()).hexdigest()
                    or snapshot['id']!=result.snapshot.snapshot_id
                    or snapshot['validation_event_id']!=result.validation_id):
                raise ValueError('snapshot integrity failure')
        elif snapshot is not None:raise ValueError('invalid event snapshot integrity failure')
        return result

    def get_snapshot(self,snapshot_id):
        row=self.db.connection.execute('SELECT raw_event_id FROM market_snapshots WHERE id=?',(snapshot_id,)).fetchone()
        if row is None:raise KeyError(snapshot_id)
        event=RawMarketEvent(**dict(self.db.connection.execute('SELECT * FROM raw_market_events WHERE id=?',(row[0],)).fetchone()))
        validation=self.db.connection.execute('SELECT * FROM market_validation_events WHERE raw_event_id=?',(event.id,)).fetchone()
        return self._verified_result(event,validation).snapshot

    def raw_events(self,experiment_id,*,as_of=None,through_sequence=None):
        self._experiment(experiment_id)
        query='SELECT * FROM raw_market_events WHERE experiment_id=?';args=[experiment_id]
        if as_of is not None:
            query+=' AND received_at<=?';args.append(as_of)
            if through_sequence is not None:
                query+=' AND (received_at<? OR sequence<=?)';args.extend((as_of,through_sequence))
        elif through_sequence is not None:raise ValueError('sequence cutoff requires as_of time')
        query+=' ORDER BY received_at,sequence'
        return tuple(RawMarketEvent(**dict(r)) for r in self.db.connection.execute(query,args))

    def counts(self,experiment_id=None):
        counts={}
        if experiment_id is not None:self._experiment(experiment_id)
        for name in ('experiments','raw_market_events','market_validation_events','market_snapshots'):
            query='SELECT COUNT(*) FROM '+name;args=()
            if experiment_id is not None:
                query+=' WHERE '+('id' if name=='experiments' else 'experiment_id')+'=?';args=(experiment_id,)
            counts[name]=self.db.connection.execute(query,args).fetchone()[0]
        return counts
