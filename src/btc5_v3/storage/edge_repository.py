"""Explicit M1 -> M2 migration and append-only, replay-verified edge records."""
from dataclasses import asdict
import hashlib
import json

from btc5_v3.encoding import canonical
from btc5_v3.models.models import Prediction
from btc5_v3.edge.costs import EdgeConfig
from btc5_v3.edge.engine import evaluate_edge


DDL = (
    'CREATE UNIQUE INDEX IF NOT EXISTS snapshot_experiment_id ON market_snapshots(experiment_id,id)',
    '''CREATE TABLE predictions (
        id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments(id),
        prediction_key TEXT NOT NULL, payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
        payload_hash TEXT NOT NULL, UNIQUE(experiment_id,id), UNIQUE(experiment_id,prediction_key))''',
    '''CREATE TABLE edge_evaluations (
        id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments(id),
        prediction_id TEXT NOT NULL, snapshot_id TEXT NOT NULL, evaluated_at INTEGER NOT NULL,
        config_hash TEXT NOT NULL, config_json TEXT NOT NULL CHECK(json_valid(config_json)),
        payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), payload_hash TEXT NOT NULL,
        FOREIGN KEY(experiment_id,prediction_id) REFERENCES predictions(experiment_id,id),
        FOREIGN KEY(experiment_id,snapshot_id) REFERENCES market_snapshots(experiment_id,id),
        UNIQUE(experiment_id,prediction_id,snapshot_id,evaluated_at,config_hash))''',
)


def payload_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def migrate_m2(db):
    """Explicit, transactional migration; concurrent attempts recheck under writer lock."""
    conn = db.connection
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        if version in (2, 3, 4, 5):
            return
        if version != 1:
            raise ValueError('M2 requires M1 schema')
        for statement in DDL:
            conn.execute(statement)
        for table in ('predictions', 'edge_evaluations'):
            for operation in ('UPDATE', 'DELETE'):
                conn.execute(f'''CREATE TRIGGER {table}_immutable_{operation.lower()}
                    BEFORE {operation} ON {table}
                    BEGIN SELECT RAISE(ABORT,'append-only M2 record'); END''')
        # SQLite REPLACE may bypass DELETE triggers unless recursive_triggers is on.
        # Reject a replacement before uniqueness conflict resolution can delete a row.
        conn.execute('''CREATE TRIGGER predictions_no_replace BEFORE INSERT ON predictions
            WHEN EXISTS (SELECT 1 FROM predictions WHERE id=NEW.id OR
                (experiment_id=NEW.experiment_id AND prediction_key=NEW.prediction_key))
            BEGIN SELECT RAISE(ABORT,'append-only prediction identity'); END''')
        conn.execute('''CREATE TRIGGER edges_no_replace BEFORE INSERT ON edge_evaluations
            WHEN EXISTS (SELECT 1 FROM edge_evaluations WHERE id=NEW.id OR
                (experiment_id=NEW.experiment_id AND prediction_id=NEW.prediction_id
                 AND snapshot_id=NEW.snapshot_id AND evaluated_at=NEW.evaluated_at AND config_hash=NEW.config_hash))
            BEGIN SELECT RAISE(ABORT,'append-only edge identity'); END''')
        conn.execute('PRAGMA user_version=2')


class EdgeRepository:
    def __init__(self, market_repository):
        self.market = market_repository
        self.db = market_repository.db
        migrate_m2(self.db)

    def _put_prediction(self, prediction):
        self.market._experiment(prediction.experiment_id)
        conn = self.db.connection
        row = conn.execute('SELECT * FROM predictions WHERE id=?', (prediction.prediction_id,)).fetchone()
        value = prediction.to_json()
        if row:
            old = self.get_prediction(prediction.prediction_id)
            if old.to_json() != value:
                raise ValueError('conflicting prediction retry')
        else:
            conn.execute('INSERT INTO predictions VALUES (?,?,?,?,?)',
                         (prediction.prediction_id, prediction.experiment_id, prediction.prediction_key,
                          value, payload_hash(value)))

    def put_prediction(self, prediction):
        with self.db.connection as conn:
            conn.execute('BEGIN IMMEDIATE')
            self._put_prediction(prediction)
        return prediction

    def get_prediction(self, prediction_id):
        row = self.db.connection.execute('SELECT * FROM predictions WHERE id=?', (prediction_id,)).fetchone()
        if row is None:
            raise KeyError(prediction_id)
        result = Prediction.from_dict(json.loads(row['payload_json']))
        self.market._experiment(result.experiment_id)
        if (result.to_json() != row['payload_json'] or payload_hash(row['payload_json']) != row['payload_hash']
                or result.prediction_id != row['id'] or result.experiment_id != row['experiment_id']
                or result.prediction_key != row['prediction_key']):
            raise ValueError('prediction integrity failure')
        return result

    def evaluate_and_store(self, snapshot_id, prediction, config, *, evaluation_at):
        with self.db.connection as conn:
            conn.execute('BEGIN IMMEDIATE')
            snapshot = self.market.get_snapshot(snapshot_id)
            if snapshot.experiment_id != prediction.experiment_id:
                raise ValueError('cross-experiment linkage forbidden')
            self._put_prediction(prediction)
            result = evaluate_edge(snapshot, prediction, config, evaluation_at=evaluation_at)
            row = conn.execute('SELECT * FROM edge_evaluations WHERE id=?', (result.edge_id,)).fetchone()
            if row:
                if self.get_edge(result.edge_id).to_json() != result.to_json():
                    raise ValueError('conflicting edge retry')
            else:
                value = result.to_json()
                conn.execute('INSERT INTO edge_evaluations VALUES (?,?,?,?,?,?,?,?,?)',
                             (result.edge_id, result.experiment_id, result.prediction_id, result.snapshot_id,
                              result.evaluated_at, config.hash, canonical(asdict(config)), value, payload_hash(value)))
        return result

    def get_edge(self, edge_id):
        row = self.db.connection.execute('SELECT * FROM edge_evaluations WHERE id=?', (edge_id,)).fetchone()
        if row is None:
            raise KeyError(edge_id)
        prediction = self.get_prediction(row['prediction_id'])
        snapshot = self.market.get_snapshot(row['snapshot_id'])
        config = EdgeConfig.from_dict(json.loads(row['config_json']))
        if (prediction.experiment_id != snapshot.experiment_id or row['experiment_id'] != snapshot.experiment_id
                or config.hash != row['config_hash'] or canonical(asdict(config)) != row['config_json']):
            raise ValueError('edge context integrity failure')
        result = evaluate_edge(snapshot, prediction, config, evaluation_at=row['evaluated_at'])
        if (result.edge_id != row['id'] or result.to_json() != row['payload_json']
                or payload_hash(row['payload_json']) != row['payload_hash']):
            raise ValueError('edge replay integrity failure')
        return result
