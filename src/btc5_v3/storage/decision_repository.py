"""Minimal schema 3: one decisions table; upstream verification remains with M1/M2."""
from dataclasses import asdict
import json

from btc5_v3.encoding import canonical
from btc5_v3.decision.config import DecisionConfig
from btc5_v3.decision.policy import decide
from btc5_v3.storage.edge_repository import payload_hash


DDL = (
    'CREATE UNIQUE INDEX IF NOT EXISTS edge_experiment_id ON edge_evaluations(experiment_id,id)',
    '''CREATE TABLE decisions (
        id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments(id),
        attempt_key TEXT NOT NULL, prediction_id TEXT, snapshot_id TEXT, edge_id TEXT,
        evaluated_at INTEGER NOT NULL, config_hash TEXT NOT NULL,
        config_json TEXT NOT NULL CHECK(json_valid(config_json)),
        payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), payload_hash TEXT NOT NULL,
        UNIQUE(experiment_id,attempt_key),
        FOREIGN KEY(experiment_id,prediction_id) REFERENCES predictions(experiment_id,id),
        FOREIGN KEY(experiment_id,snapshot_id) REFERENCES market_snapshots(experiment_id,id),
        FOREIGN KEY(experiment_id,edge_id) REFERENCES edge_evaluations(experiment_id,id))''',
    '''CREATE TRIGGER decisions_immutable_update BEFORE UPDATE ON decisions
        BEGIN SELECT RAISE(ABORT,'append-only decision'); END''',
    '''CREATE TRIGGER decisions_immutable_delete BEFORE DELETE ON decisions
        BEGIN SELECT RAISE(ABORT,'append-only decision'); END''',
    '''CREATE TRIGGER decisions_no_replace BEFORE INSERT ON decisions
        WHEN EXISTS (SELECT 1 FROM decisions WHERE id=NEW.id OR
            (experiment_id=NEW.experiment_id AND attempt_key=NEW.attempt_key))
        BEGIN SELECT RAISE(ABORT,'append-only decision identity'); END''',
)


def migrate_m3(db):
    with db.connection as conn:
        conn.execute('BEGIN IMMEDIATE')
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        if version in (3, 4, 5):
            return
        if version != 2:
            raise ValueError('M3 requires M2 schema')
        for statement in DDL:
            conn.execute(statement)
        conn.execute('PRAGMA user_version=3')


class DecisionRepository:
    def __init__(self, edge_repository):
        self.edges = edge_repository
        self.db = edge_repository.db
        migrate_m3(self.db)

    def _inputs(self, experiment_id, prediction_id, snapshot_id, edge_id):
        self.edges.market._experiment(experiment_id)
        p = self.edges.get_prediction(prediction_id) if prediction_id is not None else None
        s = self.edges.market.get_snapshot(snapshot_id) if snapshot_id is not None else None
        e = self.edges.get_edge(edge_id) if edge_id is not None else None
        if any(x is not None and x.experiment_id != experiment_id for x in (s,p,e)):
            raise ValueError('cross-experiment decision references forbidden')
        return s,p,e

    def decide_and_store(self, config, *, experiment_id, attempt_key, evaluation_at,
                         prediction_id=None, snapshot_id=None, edge_id=None):
        with self.db.connection as conn:
            conn.execute('BEGIN IMMEDIATE')
            inputs = self._inputs(experiment_id,prediction_id,snapshot_id,edge_id)
            result = decide(*inputs,config,experiment_id=experiment_id,attempt_key=attempt_key,evaluation_at=evaluation_at)
            row = conn.execute('SELECT id FROM decisions WHERE id=?',(result.decision_id,)).fetchone()
            if row:
                if self.get_decision(row[0]).to_json() != result.to_json():
                    raise ValueError('conflicting decision retry')
            else:
                value = result.to_json()
                conn.execute('INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                             (result.decision_id,experiment_id,attempt_key,prediction_id,snapshot_id,edge_id,
                              evaluation_at,config.hash,canonical(asdict(config)),value,payload_hash(value)))
        return result

    def get_decision(self, decision_id):
        row = self.db.connection.execute('SELECT * FROM decisions WHERE id=?',(decision_id,)).fetchone()
        if row is None:
            raise KeyError(decision_id)
        config = DecisionConfig(**json.loads(row['config_json']))
        inputs = self._inputs(row['experiment_id'],row['prediction_id'],row['snapshot_id'],row['edge_id'])
        result = decide(*inputs,config,experiment_id=row['experiment_id'],attempt_key=row['attempt_key'],
                        evaluation_at=row['evaluated_at'])
        if (config.hash != row['config_hash'] or canonical(asdict(config)) != row['config_json']
                or result.decision_id != row['id'] or result.to_json() != row['payload_json']
                or payload_hash(row['payload_json']) != row['payload_hash']):
            raise ValueError('decision integrity failure')
        return result
