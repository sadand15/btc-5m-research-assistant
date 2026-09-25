import sqlite3
from btc5_v3.config.models import StorageConfig

SCHEMA = '''
CREATE TABLE IF NOT EXISTS experiments (
 id TEXT PRIMARY KEY, config_hash TEXT NOT NULL, config_json TEXT NOT NULL,
 metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)));
CREATE TABLE IF NOT EXISTS raw_market_events (
 id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments(id),
 source TEXT NOT NULL, source_at INTEGER, received_at INTEGER NOT NULL,
 sequence INTEGER NOT NULL, market_id TEXT, safe_payload TEXT NOT NULL CHECK(json_valid(safe_payload)),
 payload_hash TEXT NOT NULL, schema_version INTEGER NOT NULL CHECK(schema_version=1),
 redaction_status TEXT NOT NULL, ingestion_status TEXT NOT NULL CHECK(ingestion_status='RECEIVED'),
 event_key TEXT NOT NULL, recorded_at INTEGER NOT NULL, redaction_version TEXT NOT NULL,
 UNIQUE(experiment_id,id), UNIQUE(experiment_id,source,event_key), UNIQUE(experiment_id,sequence));
CREATE TABLE IF NOT EXISTS market_validation_events (
 id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, raw_event_id TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('VALID','INVALID')), primary_reason TEXT,
 reasons_json TEXT NOT NULL CHECK(json_valid(reasons_json)), validator_version TEXT NOT NULL,
 evaluation_at INTEGER NOT NULL, context_hash TEXT NOT NULL,
 UNIQUE(experiment_id,raw_event_id), UNIQUE(experiment_id,raw_event_id,id),
 FOREIGN KEY(experiment_id,raw_event_id) REFERENCES raw_market_events(experiment_id,id),
 CHECK((status='VALID' AND primary_reason IS NULL AND reasons_json='[]') OR
       (status='INVALID' AND primary_reason IS NOT NULL AND json_array_length(reasons_json)>0)));
CREATE TABLE IF NOT EXISTS market_snapshots (
 id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, raw_event_id TEXT NOT NULL,
 validation_event_id TEXT NOT NULL UNIQUE, snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)),
 snapshot_hash TEXT NOT NULL, UNIQUE(experiment_id,raw_event_id),
 FOREIGN KEY(experiment_id,raw_event_id,validation_event_id)
 REFERENCES market_validation_events(experiment_id,raw_event_id,id));
CREATE TRIGGER IF NOT EXISTS snapshot_requires_valid BEFORE INSERT ON market_snapshots
WHEN NOT EXISTS (SELECT 1 FROM market_validation_events WHERE id=NEW.validation_event_id
 AND experiment_id=NEW.experiment_id AND raw_event_id=NEW.raw_event_id AND status='VALID')
BEGIN SELECT RAISE(ABORT,'snapshot requires valid validation'); END;
CREATE INDEX IF NOT EXISTS raw_order ON raw_market_events(experiment_id,received_at,sequence);
'''


class Database:
    def __init__(self, config: StorageConfig):
        self.path=config.resolved_path()
        self.path.parent.mkdir(parents=True,exist_ok=True)
        if config.resolved_path()!=self.path:raise ValueError('database path changed')
        self.connection=sqlite3.connect(self.path,timeout=10)
        self.connection.row_factory=sqlite3.Row
        try:
            version=self.connection.execute('PRAGMA user_version').fetchone()[0]
            tables=self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if version not in (0,1,2,3,4,5) or (version==0 and tables):
                raise ValueError('not an M1 database')
            self.connection.execute('PRAGMA foreign_keys=ON')
            if version in (1,2,3,4,5):
                expected={'experiments','raw_market_events','market_validation_events','market_snapshots'}
                if version>=2:
                    expected |= {'predictions','edge_evaluations'}
                if version>=3:
                    expected.add('decisions')
                if version>=4:
                    expected |= {'resolved_outcomes','analysis_runs','analysis_results'}
                if version>=5:
                    expected |= {'path_analysis_runs','path_analysis_results'}
                if {row[0] for row in tables}!=expected:
                    raise ValueError('incomplete M1 schema')
                if self.connection.execute('PRAGMA journal_mode').fetchone()[0]!='wal':
                    raise ValueError('M1 database must use WAL')
                # Reopening must not attempt a schema write/lock upgrade. Ingestion
                # transactions serialize writers; bootstrap is provisioned once.
            else:
                self.connection.execute('PRAGMA journal_mode=WAL')
                self.connection.executescript('BEGIN IMMEDIATE;'+SCHEMA+'PRAGMA user_version=1;COMMIT;')
        except Exception:
            self.connection.close();raise

    def __enter__(self):return self
    def __exit__(self,*args):self.connection.close()
