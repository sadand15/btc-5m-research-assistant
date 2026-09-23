"""Redacted credential scan of an index, reachable history, or local files.

Uses only the standard library. No matching value is ever printed.
Heuristics complement review; a clean scan is not a proof of absence.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
RULES = {
    'predict_key': rb'pred_sk_[A-Za-z0-9]{20,}',
    'github_token': rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})',
    'private_key': rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----',
    'aws_access': rb'(?:AKIA|ASIA)[A-Z0-9]{16}',
    'credential_url': rb'https?://[^\s/:@]{1,80}:[^\s/@]{4,120}@',
    'literal_credential': rb'''(?i)(?:api[_-]?key|private[_-]?key|secret|access[_-]?token|password|cookie)["']?\s*[:=]\s*["']([A-Za-z0-9_+/=.-]{20,})["']''',
}
PATTERNS = {k: re.compile(v) for k, v in RULES.items()}


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def findings(data, label):
    return [{'file': label, 'rule': name} for name, rx in PATTERNS.items() if rx.search(data)]


def scan(mode):
    found = []; count = 0; size = 0
    if mode == 'index':
        for line in git('ls-files', '-s', '-z').split(b'\0'):
            if not line: continue
            meta, path = line.split(b'\t', 1)
            blob = git('cat-file', 'blob', meta.split()[1].decode())
            found.extend(findings(blob, path.decode('utf-8')))
            count += 1; size += len(blob)
    elif mode == 'history':
        for line in git('rev-list', '--objects', '--all').splitlines():
            oid, _, path = line.partition(b' ')
            if git('cat-file', '-t', oid.decode()).strip() != b'blob': continue
            blob = git('cat-file', 'blob', oid.decode())
            found.extend(findings(blob, oid.decode() + ':' + path.decode('utf-8')))
            count += 1; size += len(blob)
    else:
        for directory, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in ('.git', '.venv', 'venv', '__pycache__', '.pytest_cache', 'publish')]
            for name in files:
                path = Path(directory) / name
                label = path.relative_to(ROOT).as_posix()
                with path.open('rb') as stream:
                    overlap = b''
                    while chunk := stream.read(1024 * 1024):
                        found.extend(findings(overlap + chunk, label))
                        size += len(chunk); overlap = chunk[-512:]
                count += 1
    found = [dict(t) for t in sorted({tuple(sorted(f.items())) for f in found})]
    return {'mode': mode, 'files_or_blobs': count, 'bytes': size, 'findings': found}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['local', 'index', 'history'])
    result = scan(parser.parse_args().mode)
    print(json.dumps(result, indent=2))
    raise SystemExit(bool(result['findings']))
