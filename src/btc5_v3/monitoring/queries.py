"""Bounded, explicit schema-7 queries. No SQL is accepted from the UI."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3

from btc5_v3.config.models import StorageConfig
from btc5_v3.encoding import canonical

CONTRACT = canonical({'mode':'M4_SYNTHETIC_ARCHIVE_V1'})
TABLES = frozenset(('experiments','risk_runs','risk_events','risk_decisions','capital_reservations','portfolio_snapshots'))
MAX_PAYLOAD = 4*1024*1024
MAX_ARCHIVE_BYTES = 64*1024*1024


def authorize(action, arg1, arg2, database, origin):
    if action==sqlite3.SQLITE_READ:
        return sqlite3.SQLITE_OK if database=='main' and arg1 in TABLES and origin is None else sqlite3.SQLITE_DENY
    if action in (sqlite3.SQLITE_SELECT,sqlite3.SQLITE_TRANSACTION): return sqlite3.SQLITE_OK
    if action==sqlite3.SQLITE_FUNCTION and arg2 in ('length','max','count'): return sqlite3.SQLITE_OK
    if action==sqlite3.SQLITE_PRAGMA and arg1=='user_version' and arg2 is None: return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


class ReadOnlyQueries:
    def __init__(self, project_root, database, *, max_events=1000):
        if type(max_events) is not int or not 1<=max_events<=5000: raise ValueError('invalid read budget')
        self.root=Path(project_root); self.database=Path(database); self.max_events=max_events

    @contextmanager
    def _reader(self):
        path=StorageConfig(self.root,self.database).resolved_path()
        if not path.is_file(): raise FileNotFoundError('research archive unavailable')
        conn=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)
        try:
            conn.row_factory=sqlite3.Row
            conn.execute('PRAGMA query_only=ON');conn.execute('PRAGMA trusted_schema=OFF')
            conn.set_authorizer(authorize);conn.execute('BEGIN')
            yield conn
        finally:
            conn.close()

    def catalog(self, *, limit=100):
        if type(limit) is not int or not 1<=limit<=200: raise ValueError('invalid catalog limit')
        with self._reader() as c:
            if c.execute('PRAGMA user_version').fetchone()[0]!=7: return []
            rows=c.execute('''SELECT r.id,r.experiment_id FROM risk_runs r JOIN experiments e ON e.id=r.experiment_id
                              WHERE e.config_json=? ORDER BY r.id LIMIT ?''',(CONTRACT,limit)).fetchall()
            return [dict(x) for x in rows]

    def latest_at(self, run_id):
        with self._reader() as c:
            row=c.execute('''SELECT max(v.at) FROM risk_events v JOIN risk_runs r ON r.id=v.run_id
                             JOIN experiments e ON e.id=r.experiment_id WHERE r.id=? AND e.config_json=?''',
                          (run_id,CONTRACT)).fetchone()
            return row[0] if row else None

    def fetch(self, run_id, as_of):
        with self._reader() as c:
            version=c.execute('PRAGMA user_version').fetchone()[0]
            if version!=7: return dict(schema=version,run=None,experiment=None,events=[],projections={})
            run=c.execute('''SELECT id,experiment_id,payload_hash,
                  CASE WHEN length(payload_json)<=? THEN payload_json ELSE NULL END AS payload_json
                  FROM risk_runs WHERE id=?''',(MAX_PAYLOAD,run_id)).fetchone()
            if not run: return dict(schema=version,run=None,experiment=None,events=[],projections={})
            experiment=c.execute('SELECT id,config_hash,config_json,metadata_json FROM experiments WHERE id=?',
                                 (run['experiment_id'],)).fetchone()
            if not experiment or experiment['config_json']!=CONTRACT:
                return dict(schema=version,run=None,experiment=None,events=[],projections={})
            cursor=c.execute('''SELECT id,run_id,experiment_id,sequence,request_key,at,kind,previous_hash,event_hash,
                CASE WHEN length(inputs_json)<=? THEN inputs_json ELSE NULL END AS inputs_json,
                CASE WHEN length(output_json)<=? THEN output_json ELSE NULL END AS output_json
                FROM risk_events WHERE run_id=? AND at<=? ORDER BY sequence LIMIT ?''',
                (MAX_PAYLOAD,MAX_PAYLOAD,run_id,as_of,self.max_events+1))
            rows=[];size=0;truncated=False
            for row in cursor:
                size+=len(row['inputs_json'] or '')+len(row['output_json'] or '')
                if len(rows)>=self.max_events or size>MAX_ARCHIVE_BYTES:
                    truncated=True;break
                rows.append(row)
            cursor.close()
            projections={}
            for table in ('risk_decisions','capital_reservations','portfolio_snapshots'):
                cursor=c.execute(f'''SELECT p.id,p.run_id,p.event_id,p.payload_hash,
                    CASE WHEN length(p.payload_json)<=? THEN p.payload_json ELSE NULL END AS payload_json
                    FROM {table} p JOIN risk_events v ON v.id=p.event_id
                    WHERE v.run_id=? AND v.at<=? AND v.sequence<=? ORDER BY v.sequence,p.id LIMIT ?''',
                    (MAX_PAYLOAD,run_id,as_of,len(rows),self.max_events*32+1))
                projections[table]=[]
                for x in cursor:
                    size+=len(x['payload_json'] or '')
                    if size>MAX_ARCHIVE_BYTES:truncated=True;break
                    projections[table].append(dict(x))
                cursor.close()
            return dict(schema=version,run=dict(run),experiment=dict(experiment),
                        events=[dict(x) for x in rows[:self.max_events]],projections=projections,
                        truncated=truncated)
