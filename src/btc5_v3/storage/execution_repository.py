"""Transactional execution archives and immutable normalized audit projections."""
from dataclasses import asdict
import json

from btc5_v3.encoding import canonical,digest
from btc5_v3.analytics.models import ResearchObservation,ResolvedOutcome
from btc5_v3.path.models import MarketPathPoint
from btc5_v3.execution.models import ExecutionConfig,ExitPolicy
from btc5_v3.execution.engine import simulate
from btc5_v3.storage.path_repository import PathRepository
from btc5_v3.storage.edge_repository import payload_hash

TABLES={'simulated_orders':('orders','order_id'),'simulated_order_events':('order_events','event_id'),
        'simulated_fills':('fills','fill_id'),'simulated_positions':('positions','position_id'),
        'simulated_exit_attempts':('exit_attempts','exit_id'),'simulated_settlements':('settlements','settlement_id'),
        'simulated_ledger_entries':('ledger_entries','ledger_id')}


def migrate_execution(db):
    with db.connection as conn:
        conn.execute('BEGIN IMMEDIATE');version=conn.execute('PRAGMA user_version').fetchone()[0]
        if version==6:return
        if version!=5:raise ValueError('execution requires M4.5 schema')
        conn.execute('''CREATE TABLE execution_runs (
            id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments(id),
            code_git TEXT NOT NULL, cutoff INTEGER NOT NULL, created_at INTEGER NOT NULL,
            config_json TEXT NOT NULL CHECK(json_valid(config_json)), config_hash TEXT NOT NULL,
            policy_json TEXT NOT NULL CHECK(json_valid(policy_json)), policy_hash TEXT NOT NULL,
            inputs_json TEXT NOT NULL CHECK(json_valid(inputs_json)), input_hash TEXT NOT NULL,
            UNIQUE(experiment_id,id))''')
        conn.execute('''CREATE TABLE execution_results (
            run_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL,
            payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), payload_hash TEXT NOT NULL,
            FOREIGN KEY(experiment_id,run_id) REFERENCES execution_runs(experiment_id,id))''')
        for table in TABLES:
            conn.execute(f'''CREATE TABLE {table} (
                run_id TEXT NOT NULL, experiment_id TEXT NOT NULL, id TEXT NOT NULL,
                payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), payload_hash TEXT NOT NULL,
                PRIMARY KEY(run_id,id),
                FOREIGN KEY(experiment_id,run_id) REFERENCES execution_runs(experiment_id,id))''')
        for table in ('execution_runs','execution_results',*TABLES):
            for op in ('UPDATE','DELETE'):
                conn.execute(f'''CREATE TRIGGER {table}_immutable_{op.lower()} BEFORE {op} ON {table}
                    BEGIN SELECT RAISE(ABORT,'immutable simulation record'); END''')
            key='id=NEW.id' if table=='execution_runs' else 'run_id=NEW.run_id'
            if table in TABLES:key+=' AND id=NEW.id'
            conn.execute(f'''CREATE TRIGGER {table}_no_replace BEFORE INSERT ON {table}
                WHEN EXISTS (SELECT 1 FROM {table} WHERE {key})
                BEGIN SELECT RAISE(ABORT,'immutable simulation identity'); END''')
        conn.execute('PRAGMA user_version=6')


class ExecutionRepository:
    def __init__(self,db):
        self.db=db;self.paths=PathRepository(db);migrate_execution(db)

    def register(self,experiment):self.paths.register(experiment)

    def run(self,observation,books,outcome,config,policy,*,experiment_id,code_git,cutoff,created_at):
        books=tuple(books)
        result=simulate(observation,books,outcome,config,policy,experiment_id=experiment_id,code_git=code_git,cutoff=cutoff,created_at=created_at)
        inputs=canonical(dict(original=json.loads(observation.payload_json),books=sorted((asdict(b) for b in books),key=digest),
                              outcome=json.loads(outcome.to_json()) if outcome else None))
        with self.db.connection as conn:
            conn.execute('BEGIN IMMEDIATE');self.paths.analytics._experiment(experiment_id)
            if conn.execute('SELECT id FROM execution_runs WHERE id=?',(result.execution_id,)).fetchone():
                saved=self.get_run(result.execution_id)
                if saved.report_json!=result.report_json:raise ValueError('simulation retry conflict')
                return saved
            conn.execute('INSERT INTO execution_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (result.execution_id,experiment_id,code_git,cutoff,created_at,canonical(asdict(config)),config.hash,
                 canonical(asdict(policy)),policy.hash,inputs,result.input_hash))
            conn.execute('INSERT INTO execution_results VALUES (?,?,?,?)',
                (result.execution_id,experiment_id,result.to_json(),payload_hash(result.to_json())))
            for table,(field,key) in TABLES.items():
                for item in json.loads(result.report_json)[field]:
                    value=canonical(item)
                    conn.execute(f'INSERT INTO {table} VALUES (?,?,?,?,?)',
                                 (result.execution_id,experiment_id,item[key],value,payload_hash(value)))
        return result

    def get_run(self,identity):
        conn=self.db.connection
        row=conn.execute('SELECT * FROM execution_runs WHERE id=?',(identity,)).fetchone()
        saved=conn.execute('SELECT * FROM execution_results WHERE run_id=?',(identity,)).fetchone()
        if row is None or saved is None:raise KeyError(identity)
        data=json.loads(row['inputs_json']);config=ExecutionConfig.from_dict(json.loads(row['config_json']));policy=ExitPolicy(**json.loads(row['policy_json']))
        result=simulate(ResearchObservation(canonical(data['original'])),[MarketPathPoint(**x) for x in data['books']],
            ResolvedOutcome.from_dict(data['outcome']) if data['outcome'] else None,config,policy,
            experiment_id=row['experiment_id'],code_git=row['code_git'],cutoff=row['cutoff'],created_at=row['created_at'])
        if (result.execution_id!=identity or result.input_hash!=row['input_hash'] or result.config_hash!=row['config_hash']
                or result.policy_hash!=row['policy_hash'] or canonical(asdict(config))!=row['config_json']
                or canonical(asdict(policy))!=row['policy_json'] or result.to_json()!=saved['payload_json']
                or payload_hash(saved['payload_json'])!=saved['payload_hash'] or saved['experiment_id']!=row['experiment_id']):
            raise ValueError('execution replay integrity failure')
        report=result.data()
        for table,(field,key) in TABLES.items():
            expected={x[key]:canonical(x) for x in report[field]}
            rows=conn.execute(f'SELECT * FROM {table} WHERE run_id=?',(identity,)).fetchall()
            if len(rows)!=len(expected):raise ValueError('execution projection count mismatch')
            for x in rows:
                if (x['experiment_id']!=row['experiment_id'] or expected.get(x['id'])!=x['payload_json']
                        or payload_hash(x['payload_json'])!=x['payload_hash']):raise ValueError('execution projection integrity failure')
        return result
