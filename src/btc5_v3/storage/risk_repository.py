"""Serialized risk permission, reservation and M5 reconciliation transactions."""
from dataclasses import asdict
import json

from btc5_v3.encoding import canonical, digest, identifier
from btc5_v3.analytics.models import validate_run_identity
from btc5_v3.execution.models import ExecutionConfig, ExitPolicy
from btc5_v3.risk.models import RiskConfig, PortfolioState
from btc5_v3.risk.engine import empty_context, apply_event, portfolio
from btc5_v3.storage.execution_repository import ExecutionRepository

RISK_TABLES = ('risk_runs', 'risk_events', 'risk_decisions', 'capital_reservations', 'portfolio_snapshots')


def migrate_risk(db):
    with db.connection as conn:
        conn.execute('BEGIN IMMEDIATE')
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        if version == 7: return
        if version != 6: raise ValueError('risk requires M5 schema')
        conn.execute('''CREATE TABLE risk_runs (
            id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments(id),
            payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), payload_hash TEXT NOT NULL,
            UNIQUE(experiment_id,id))''')
        conn.execute('''CREATE TABLE risk_events (
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL, experiment_id TEXT NOT NULL,
            sequence INTEGER NOT NULL, request_key TEXT NOT NULL, at INTEGER NOT NULL,
            kind TEXT NOT NULL, inputs_json TEXT NOT NULL CHECK(json_valid(inputs_json)),
            output_json TEXT NOT NULL CHECK(json_valid(output_json)), previous_hash TEXT NOT NULL,
            event_hash TEXT NOT NULL, UNIQUE(run_id,sequence), UNIQUE(run_id,request_key),
            UNIQUE(run_id,id), FOREIGN KEY(experiment_id,run_id) REFERENCES risk_runs(experiment_id,id))''')
        for table in RISK_TABLES[2:]:
            conn.execute(f'''CREATE TABLE {table} (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL, event_id TEXT NOT NULL,
                payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), payload_hash TEXT NOT NULL,
                FOREIGN KEY(run_id,event_id) REFERENCES risk_events(run_id,id))''')
        for table in RISK_TABLES:
            for op in ('UPDATE', 'DELETE'):
                conn.execute(f'''CREATE TRIGGER {table}_immutable_{op.lower()} BEFORE {op} ON {table}
                    BEGIN SELECT RAISE(ABORT,'append-only risk archive'); END''')
            conn.execute(f'''CREATE TRIGGER {table}_no_replace BEFORE INSERT ON {table}
                WHEN EXISTS (SELECT 1 FROM {table} WHERE id=NEW.id)
                BEGIN SELECT RAISE(ABORT,'immutable risk identity'); END''')
        conn.execute('PRAGMA user_version=7')


def projections(event_id, kind, output):
    rows = {'risk_decisions': [], 'capital_reservations': [], 'portfolio_snapshots': []}
    if kind == 'EVALUATE': rows['risk_decisions'].append(output['risk_decision'])
    if kind != 'EXECUTE' and output.get('reservation'): rows['capital_reservations'].append(output['reservation'])
    rows['capital_reservations'] += output.get('reservation_changes', [])
    rows['portfolio_snapshots'].append(output['state_after'])
    return {table: [(digest([event_id, table, n]), canonical(value), digest(value)) for n, value in enumerate(values)]
            for table, values in rows.items()}


class RiskRepository:
    def __init__(self, db):
        self.db = db
        self.execution = ExecutionRepository(db)
        migrate_risk(db)

    def register(self, experiment):
        self.execution.register(experiment)

    def create_run(self, experiment_id, code_git, config, created_at):
        validate_run_identity(experiment_id, code_git, created_at, created_at)
        if not isinstance(config, RiskConfig): raise TypeError('RiskConfig required')
        value = dict(experiment_id=experiment_id, code_git=code_git, config=asdict(config),
                     config_hash=config.hash, created_at=created_at, version='risk-v1')
        rid = digest(value); value['run_id'] = rid
        with self.db.connection as conn:
            conn.execute('BEGIN IMMEDIATE')
            self.execution.paths.analytics._experiment(experiment_id)
            old = conn.execute('SELECT id FROM risk_runs WHERE id=?', (rid,)).fetchone()
            if old:
                if self._run(rid) != json.loads(canonical(value)): raise ValueError('risk run conflict')
            else:
                conn.execute('INSERT INTO risk_runs VALUES (?,?,?,?)', (rid, experiment_id, canonical(value), digest(value)))
        return rid

    def _run(self, rid):
        row = self.db.connection.execute('SELECT * FROM risk_runs WHERE id=?', (rid,)).fetchone()
        if row is None: raise KeyError(rid)
        data = json.loads(row['payload_json']); identity = data.pop('run_id')
        expected = digest(data); data['run_id'] = identity
        cfg = RiskConfig(**data['config'])
        validate_run_identity(data['experiment_id'], data['code_git'], data['created_at'], data['created_at'])
        if (identity != rid or expected != rid or data['experiment_id'] != row['experiment_id']
                or digest(data) != row['payload_hash'] or canonical(data) != row['payload_json']
                or cfg.hash != data['config_hash']):
            raise ValueError('risk run integrity failure')
        return data

    def _replay(self, rid, at=None):
        run = self._run(rid); ctx = empty_context(); previous = digest(run)
        sql = 'SELECT * FROM risk_events WHERE run_id=?'; params = [rid]
        if at is not None: sql += ' AND at<=?'; params.append(at)
        rows = self.db.connection.execute(sql+' ORDER BY sequence', params).fetchall()
        for seq, row in enumerate(rows, 1):
            inputs = json.loads(row['inputs_json'])
            output = apply_event(ctx, run, row['kind'], inputs)
            event_id = digest([rid, row['request_key']])
            event_hash = digest([previous, event_id, seq, row['kind'], inputs, output])
            if (row['sequence'] != seq or row['id'] != event_id or row['experiment_id'] != run['experiment_id']
                    or row['at'] != inputs['at'] or row['previous_hash'] != previous or row['event_hash'] != event_hash
                    or canonical(inputs) != row['inputs_json'] or canonical(output) != row['output_json']):
                raise ValueError('risk event replay integrity failure')
            for table, expected in projections(event_id, row['kind'], output).items():
                saved = self.db.connection.execute(f'SELECT * FROM {table} WHERE event_id=? ORDER BY id', (event_id,)).fetchall()
                actual = [(x['id'], x['payload_json'], x['payload_hash']) for x in saved]
                if actual != sorted(expected) or any(x['run_id'] != rid for x in saved):
                    raise ValueError('risk projection integrity failure')
            previous = event_hash
        return run, ctx, rows, previous

    def _append(self, rid, key, kind, inputs):
        # BEGIN IMMEDIATE serializes independent connections before reading cash.
        # Any failure rolls back permission, reservation, snapshot and M5 archive.
        with self.db.connection as conn:
            conn.execute('BEGIN IMMEDIATE')
            run, ctx, rows, previous = self._replay(rid)
            old = conn.execute('SELECT * FROM risk_events WHERE run_id=? AND request_key=?', (rid, key)).fetchone()
            if old:
                if old['kind'] != kind or old['inputs_json'] != canonical(inputs):
                    raise ValueError('conflicting risk idempotency input')
                return json.loads(old['output_json'])
            output = apply_event(ctx, run, kind, json.loads(canonical(inputs)))
            event_id = digest([rid, key]); seq = len(rows)+1
            h = digest([previous, event_id, seq, kind, inputs, output])
            conn.execute('INSERT INTO risk_events VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                         (event_id, rid, run['experiment_id'], seq, key, inputs['at'], kind,
                          canonical(inputs), canonical(output), previous, h))
            for table, entries in projections(event_id, kind, output).items():
                for identity, payload, ph in entries:
                    conn.execute(f'INSERT INTO {table} VALUES (?,?,?,?,?)', (identity, rid, event_id, payload, ph))
        return output

    def evaluate(self, run_id, original, *, at, health=None, execution_config=None, policy=None):
        inputs = dict(original=original.data(), at=at, health=asdict(health) if health else None,
                      execution_config=asdict(execution_config or ExecutionConfig()), policy=asdict(policy or ExitPolicy()))
        return self._append(run_id, 'candidate:'+inputs['original']['decision']['decision_id'], 'EVALUATE', inputs)

    def execute(self, run_id, risk_decision_id, books, outcome=None, *, cutoff):
        identifier(risk_decision_id)
        inputs = dict(risk_decision_id=risk_decision_id, at=cutoff,
                      books=sorted((asdict(b) for b in books), key=digest),
                      outcome=json.loads(outcome.to_json()) if outcome else None)
        return self._append(run_id, 'execution:'+risk_decision_id+':'+str(cutoff), 'EXECUTE', inputs)

    def control(self, run_id, request_id, action, *, at, health=None):
        identifier(request_id)
        return self._append(run_id, 'control:'+request_id, 'CONTROL',
                            dict(at=at, action=action, health=asdict(health) if health else None))

    def expire(self, run_id, risk_decision_id, *, at):
        return self._append(run_id, 'expiry:'+risk_decision_id, 'EXPIRE', dict(at=at, risk_decision_id=risk_decision_id))

    def state(self, run_id, *, at):
        # One read transaction pins a consistent WAL snapshot across all tables.
        with self.db.connection as conn:
            conn.execute('BEGIN')
            run, ctx, _, _ = self._replay(run_id, at)
            if at < run['created_at']: raise ValueError('portfolio predates run')
            return PortfolioState(canonical(portfolio(ctx, RiskConfig(**run['config']), at)))

    def report(self, run_id, *, at):
        from btc5_v3.risk.report import report
        with self.db.connection as conn:
            conn.execute('BEGIN')
            run, ctx, rows, _ = self._replay(run_id, at)
            return report(run, ctx, [json.loads(x['output_json']) for x in rows], at)
