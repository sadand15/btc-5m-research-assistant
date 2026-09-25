"""Append-only, replay-verified path analysis archives in isolated V3 storage."""
from dataclasses import asdict
import json

from btc5_v3.encoding import canonical, digest
from btc5_v3.analytics.models import ResolvedOutcome
from btc5_v3.path.models import IntracyclePathConfig, MarketPathPoint
from btc5_v3.path.engine import analyze_paths
from btc5_v3.storage.analytics_repository import AnalyticsRepository
from btc5_v3.storage.edge_repository import payload_hash

DDL=(
    '''CREATE TABLE path_analysis_runs (
        id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments(id),
        code_git TEXT NOT NULL, cutoff INTEGER NOT NULL, created_at INTEGER NOT NULL,
        config_json TEXT NOT NULL CHECK(json_valid(config_json)), config_hash TEXT NOT NULL,
        inputs_json TEXT NOT NULL CHECK(json_valid(inputs_json)), input_hash TEXT NOT NULL,
        UNIQUE(experiment_id,id))''',
    '''CREATE TABLE path_analysis_results (
        analysis_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL,
        result_json TEXT NOT NULL CHECK(json_valid(result_json)), result_hash TEXT NOT NULL,
        FOREIGN KEY(experiment_id,analysis_id) REFERENCES path_analysis_runs(experiment_id,id))''',
)


def migrate_path(db):
    with db.connection as conn:
        conn.execute('BEGIN IMMEDIATE')
        version=conn.execute('PRAGMA user_version').fetchone()[0]
        if version==5: return
        if version!=4: raise ValueError('path analytics requires M4 schema')
        for sql in DDL: conn.execute(sql)
        for table,key in (('path_analysis_runs','id'),('path_analysis_results','analysis_id')):
            for operation in ('UPDATE','DELETE'):
                conn.execute(f'''CREATE TRIGGER {table}_immutable_{operation.lower()} BEFORE {operation} ON {table}
                    BEGIN SELECT RAISE(ABORT,'append-only path analysis'); END''')
            conn.execute(f'''CREATE TRIGGER {table}_no_replace BEFORE INSERT ON {table}
                WHEN EXISTS (SELECT 1 FROM {table} WHERE {key}=NEW.{key})
                BEGIN SELECT RAISE(ABORT,'append-only path identity'); END''')
        conn.execute('PRAGMA user_version=5')


class PathRepository:
    def __init__(self,db):
        self.db=db
        self.analytics=AnalyticsRepository(db)
        migrate_path(db)

    def register(self,experiment): self.analytics.register(experiment)

    def run(self,points,outcomes,config,*,experiment_id,code_git,cutoff,created_at):
        points=tuple(points);outcomes=tuple(outcomes)
        result=analyze_paths(points,outcomes,config,experiment_id=experiment_id,code_git=code_git,cutoff=cutoff,created_at=created_at)
        inputs=canonical(dict(points=sorted((asdict(p) for p in points),key=digest),
                              outcomes=sorted((json.loads(o.to_json()) for o in outcomes),key=lambda x:x['outcome_id'])))
        with self.db.connection as conn:
            conn.execute('BEGIN IMMEDIATE');self.analytics._experiment(experiment_id)
            old=conn.execute('SELECT id FROM path_analysis_runs WHERE id=?',(result.analysis_id,)).fetchone()
            if old:
                saved=self.get_run(result.analysis_id)
                if saved.report_json!=result.report_json: raise ValueError('path retry conflict')
                return saved
            conn.execute('INSERT INTO path_analysis_runs VALUES (?,?,?,?,?,?,?,?,?)',
                (result.analysis_id,experiment_id,code_git,cutoff,created_at,canonical(asdict(config)),config.hash,inputs,result.input_hash))
            conn.execute('INSERT INTO path_analysis_results VALUES (?,?,?,?)',
                (result.analysis_id,experiment_id,result.to_json(),payload_hash(result.to_json())))
        return result

    def get_run(self,identity):
        conn=self.db.connection
        row=conn.execute('SELECT * FROM path_analysis_runs WHERE id=?',(identity,)).fetchone()
        saved=conn.execute('SELECT * FROM path_analysis_results WHERE analysis_id=?',(identity,)).fetchone()
        if row is None or saved is None: raise KeyError(identity)
        data=json.loads(row['inputs_json']);cfg=IntracyclePathConfig(**json.loads(row['config_json']))
        result=analyze_paths([MarketPathPoint(**p) for p in data['points']],
            [ResolvedOutcome.from_dict(o) for o in data['outcomes']],cfg,experiment_id=row['experiment_id'],
            code_git=row['code_git'],cutoff=row['cutoff'],created_at=row['created_at'])
        if (result.analysis_id!=identity or cfg.hash!=row['config_hash'] or result.input_hash!=row['input_hash']
                or canonical(asdict(cfg))!=row['config_json'] or result.to_json()!=saved['result_json']
                or saved['experiment_id']!=row['experiment_id'] or payload_hash(saved['result_json'])!=saved['result_hash']):
            raise ValueError('path read-back integrity failure')
        return result
