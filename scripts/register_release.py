"""Attach an immutable Git release to the existing frozen study, without retraining.

Writes a separate provenance table and sidecar, never edits the freeze manifest.
Run after creating the annotated release tag. Re-running is idempotent.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from btc5.config import load_config
from btc5.forward import policy, sources, sha


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def register(version):
    manifest_path = ROOT / 'runtime/forward/manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    cfg = load_config()
    # Check even after the observation window ends.
    if sha(cfg['storage']['model']) != manifest['model_sha256']:
        raise ValueError('Frozen model changed')
    if policy(cfg) != manifest['policy'] or sources() != manifest['source_sha256']:
        raise ValueError('Frozen policy or source changed')
    if cfg['storage']['database'] != manifest['database']:
        raise ValueError('Study database mismatch')
    commit = git('rev-parse', 'HEAD').decode().strip()
    if git('rev-parse', version + '^{commit}').decode().strip() != commit:
        raise ValueError('Tag must identify HEAD')
    for name, digest in manifest['source_sha256'].items():
        blob = git('show', commit + ':' + name.replace('\\', '/'))
        if hashlib.sha256(blob).hexdigest() != digest:
            raise ValueError('Committed source differs from frozen source: ' + name)
    raw_config = (ROOT / 'config.yaml').read_bytes()
    if git('show', commit + ':config.yaml') != raw_config:
        raise ValueError('Committed config differs from running config')
    record = {
        'run_id': manifest['run_id'], 'version': version, 'git_commit': commit,
        'model_hash': manifest['model_sha256'],
        'config_hash': hashlib.sha256(raw_config).hexdigest(),
        'policy_hash': hashlib.sha256(json.dumps(manifest['policy'], sort_keys=True,
             separators=(',', ':'), ensure_ascii=True).encode()).hexdigest(),
    }
    with sqlite3.connect(manifest['database'], timeout=30) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS forward_release_provenance (
            run_id TEXT PRIMARY KEY, version TEXT NOT NULL, git_commit TEXT NOT NULL,
            model_hash TEXT NOT NULL, config_hash TEXT NOT NULL, policy_hash TEXT NOT NULL,
            registered_at TEXT NOT NULL)''')
        old = db.execute('SELECT run_id,version,git_commit,model_hash,config_hash,policy_hash '
                         'FROM forward_release_provenance WHERE run_id=?', (record['run_id'],)).fetchone()
        if old and old != tuple(record.values()):
            raise ValueError('Existing provenance differs; refusing to overwrite')
        db.execute('INSERT OR IGNORE INTO forward_release_provenance VALUES (?,?,?,?,?,?,?)',
                   (*record.values(), datetime.now(timezone.utc).isoformat()))
    sidecar = manifest_path.with_name('release.json')
    sidecar.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(record, indent=2))
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', default='v2.0.0')
    register(parser.parse_args().version)
