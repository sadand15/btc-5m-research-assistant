"""Explicit research archives. Never discovers/opens the production observation DB."""
from dataclasses import asdict
import json

from btc5_v3.encoding import canonical, digest
from btc5_v3.analytics.models import AnalyticsConfig, ResolvedOutcome, ResearchObservation
from btc5_v3.analytics.engine import analyze
from btc5_v3.storage.edge_repository import migrate_m2, payload_hash
from btc5_v3.storage.decision_repository import migrate_m3

RESEARCH_CONTRACT={'mode':'M4_SYNTHETIC_ARCHIVE_V1'}
DDL=(
    '''CREATE TABLE resolved_outcomes (
        id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments(id), market_id TEXT NOT NULL,
        payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), payload_hash TEXT NOT NULL,
        UNIQUE(experiment_id,market_id))''',
    '''CREATE TABLE analysis_runs (
        id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments(id),
        code_git TEXT NOT NULL, cutoff INTEGER NOT NULL, created_at INTEGER NOT NULL,
        config_json TEXT NOT NULL CHECK(json_valid(config_json)), config_hash TEXT NOT NULL,
        inputs_json TEXT NOT NULL CHECK(json_valid(inputs_json)), input_hash TEXT NOT NULL,
        UNIQUE(experiment_id,id))''',
    '''CREATE TABLE analysis_results (
        analysis_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL,
        result_json TEXT NOT NULL CHECK(json_valid(result_json)), result_hash TEXT NOT NULL,
        FOREIGN KEY(experiment_id,analysis_id) REFERENCES analysis_runs(experiment_id,id))''',
)


def migrate_m4(db):
    with db.connection as conn:
        conn.execute('BEGIN IMMEDIATE')
        version=conn.execute('PRAGMA user_version').fetchone()[0]
        if version in (4,5):return
        if version!=3:raise ValueError('M4 requires M3 schema')
        for sql in DDL:conn.execute(sql)
        for table,key in (('resolved_outcomes','id'),('analysis_runs','id'),('analysis_results','analysis_id')):
            for operation in ('UPDATE','DELETE'):
                conn.execute(f'''CREATE TRIGGER {table}_immutable_{operation.lower()} BEFORE {operation} ON {table}
                    BEGIN SELECT RAISE(ABORT,'append-only analytical record'); END''')
            extra=' OR (experiment_id=NEW.experiment_id AND market_id=NEW.market_id)' if table=='resolved_outcomes' else ''
            conn.execute(f'''CREATE TRIGGER {table}_no_replace BEFORE INSERT ON {table}
                WHEN EXISTS (SELECT 1 FROM {table} WHERE {key}=NEW.{key}{extra})
                BEGIN SELECT RAISE(ABORT,'append-only analytical identity'); END''')
        conn.execute('PRAGMA user_version=4')


class AnalyticsRepository:
    def __init__(self,db):
        self.db=db
        migrate_m2(db);migrate_m3(db);migrate_m4(db)

    def register(self,experiment):
        """Dedicated multi-market synthetic research cohort, not a venue collector."""
        if experiment.config_hash!=digest(RESEARCH_CONTRACT):raise ValueError('explicit synthetic research contract required')
        metadata=canonical(asdict(experiment));contract=canonical(RESEARCH_CONTRACT)
        with self.db.connection as conn:
            conn.execute('BEGIN IMMEDIATE')
            old=conn.execute('SELECT * FROM experiments WHERE id=?',(experiment.id,)).fetchone()
            if old:
                if old['metadata_json']!=metadata or old['config_json']!=contract:raise ValueError('experiment conflict')
            else:conn.execute('INSERT INTO experiments VALUES (?,?,?,?)',(experiment.id,experiment.config_hash,contract,metadata))

    def _experiment(self,experiment_id):
        if self.db.connection.execute('SELECT id FROM experiments WHERE id=?',(experiment_id,)).fetchone() is None:
            raise ValueError('unknown research experiment')

    def _put_outcome(self,outcome):
        self._experiment(outcome.experiment_id)
        row=self.db.connection.execute('SELECT id FROM resolved_outcomes WHERE experiment_id=? AND market_id=?',
                                        (outcome.experiment_id,outcome.market_id)).fetchone()
        if row:
            if self.get_outcome(row[0]).to_json()!=outcome.to_json():raise ValueError('conflicting immutable outcome')
        else:
            value=outcome.to_json()
            self.db.connection.execute('INSERT INTO resolved_outcomes VALUES (?,?,?,?,?)',
                                       (outcome.outcome_id,outcome.experiment_id,outcome.market_id,value,payload_hash(value)))

    def get_outcome(self,outcome_id):
        row=self.db.connection.execute('SELECT * FROM resolved_outcomes WHERE id=?',(outcome_id,)).fetchone()
        if row is None:raise KeyError(outcome_id)
        result=ResolvedOutcome.from_dict(json.loads(row['payload_json']))
        if (result.outcome_id!=row['id'] or result.experiment_id!=row['experiment_id'] or result.market_id!=row['market_id']
                or result.to_json()!=row['payload_json'] or payload_hash(row['payload_json'])!=row['payload_hash']):
            raise ValueError('outcome integrity failure')
        return result

    def run(self,observations,outcomes,config,*,experiment_id,code_git,cutoff,created_at):
        observations=tuple(observations);outcomes=tuple(outcomes)
        result=analyze(observations,outcomes,config,experiment_id=experiment_id,code_git=code_git,cutoff=cutoff,created_at=created_at)
        inputs=canonical(dict(observations=[json.loads(o.payload_json) for o in sorted(observations,key=lambda x:x.input_hash)],
                              outcome_ids=sorted(o.outcome_id for o in outcomes)))
        with self.db.connection as conn:
            conn.execute('BEGIN IMMEDIATE');self._experiment(experiment_id)
            for o in outcomes:self._put_outcome(o)
            old=conn.execute('SELECT * FROM analysis_runs WHERE id=?',(result.analysis_id,)).fetchone()
            if old:
                saved=self.get_run(result.analysis_id)
                if saved.report_json!=result.report_json or old['inputs_json']!=inputs:raise ValueError('analysis retry conflict')
                return saved  # retain first creation metadata, never update it on a retry
            conn.execute('INSERT INTO analysis_runs VALUES (?,?,?,?,?,?,?,?,?)',
                         (result.analysis_id,experiment_id,code_git,cutoff,created_at,canonical(asdict(config)),config.hash,inputs,result.input_hash))
            value=result.to_json()
            conn.execute('INSERT INTO analysis_results VALUES (?,?,?,?)',(result.analysis_id,experiment_id,value,payload_hash(value)))
        return result

    def get_run(self,analysis_id):
        conn=self.db.connection
        row=conn.execute('SELECT * FROM analysis_runs WHERE id=?',(analysis_id,)).fetchone()
        saved=conn.execute('SELECT * FROM analysis_results WHERE analysis_id=?',(analysis_id,)).fetchone()
        if row is None or saved is None:raise KeyError(analysis_id)
        data=json.loads(row['inputs_json']);config=AnalyticsConfig(**json.loads(row['config_json']))
        observations=tuple(ResearchObservation(canonical(x)) for x in data['observations'])
        outcomes=tuple(self.get_outcome(i) for i in data['outcome_ids'])
        result=analyze(observations,outcomes,config,experiment_id=row['experiment_id'],code_git=row['code_git'],
                       cutoff=row['cutoff'],created_at=row['created_at'])
        if (result.analysis_id!=row['id'] or result.input_hash!=row['input_hash'] or config.hash!=row['config_hash']
                or canonical(asdict(config))!=row['config_json'] or saved['experiment_id']!=row['experiment_id']
                or result.to_json()!=saved['result_json'] or payload_hash(saved['result_json'])!=saved['result_hash']):
            raise ValueError('analysis read-back integrity failure')
        return result
