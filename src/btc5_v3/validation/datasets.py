"""Explicit read-only M8 dataset catalog. Role checked before payload access."""
from contextlib import contextmanager
import json
import sqlite3
from pathlib import Path
from btc5_v3.config.models import StorageConfig
from btc5_v3.m8.models import DatasetManifest,Dataset


def authorize(action,first,second,database,origin):
    if action==sqlite3.SQLITE_READ:
        return sqlite3.SQLITE_OK if database=='main' and first in ('m8_dataset_manifests','m8_dataset_records') and origin is None else sqlite3.SQLITE_DENY
    if action in (sqlite3.SQLITE_SELECT,sqlite3.SQLITE_TRANSACTION):return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


@contextmanager
def reader(root,path):
    p=StorageConfig(Path(root),Path(path)).resolved_path()
    if not p.is_file():raise FileNotFoundError('explicit M8 archive unavailable')
    c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)
    try:
        c.execute('PRAGMA query_only=ON');c.set_authorizer(authorize);c.execute('BEGIN');yield c
    finally:c.close()


def load_dataset(root,path,dataset_id,*,required_role):
    if required_role not in ('DEVELOPMENT','VALIDATION'):raise PermissionError('blind role denied before database access')
    with reader(root,path) as c:
        row=c.execute('SELECT metadata_json FROM m8_dataset_manifests WHERE id=?',(dataset_id,)).fetchone()
        if row is None:raise ValueError('unknown manifest')
        if len(row[0])>65536:raise ValueError('manifest too large')
        manifest=DatasetManifest(**json.loads(row[0]))
        if manifest.dataset_id!=dataset_id:raise ValueError('manifest identity mismatch')
        if manifest.role!=required_role:raise PermissionError('dataset role mismatch; payload not read')
        c.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,16*1024*1024)
        row=c.execute('SELECT records_json FROM m8_dataset_records WHERE dataset_id=?',(dataset_id,)).fetchone()
        if row is None:raise ValueError('missing dataset payload')
        return Dataset(manifest,row[0])
