"""Approved baseline is explicit; running collector identity is separate."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
from btc5_v3.encoding import digest
from btc5_v3.m8.models import Baseline

APPROVED='4dd8c798cac479ddd411cb69a7901fda6e0f8136'
VERSION='prospective-v1'


def file_hash(path):return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n',b'\n')).hexdigest()


def identity(root,*,strict=True):
    root=Path(root);folder=root/'src/btc5_v3/prospective'
    lock=json.loads((folder/'baseline_lock.json').read_text(encoding='utf-8'))
    if lock['baseline_git_sha']!=APPROVED:raise ValueError('BASELINE_LOCK_CHANGED')
    if any(not (root/p).is_file() or file_hash(root/p)!=h for p,h in lock['files'].items()):raise ValueError('BASELINE_CHANGED')
    collector_hash=digest({p.name:file_hash(p) for p in sorted(folder.glob('*.py'))})
    if (root/'.git').exists():
        def git(*a):return subprocess.check_output(['git',*a],cwd=root,text=True).strip()
        sha=git('rev-parse','HEAD');branch=git('branch','--show-current') or 'DETACHED'
        if strict and git('status','--porcelain'):raise ValueError('CLEAN_COLLECTOR_COMMIT_REQUIRED')
        subprocess.run(['git','merge-base','--is-ancestor',APPROVED,sha],cwd=root,check=True,capture_output=True)
    else:
        build=json.loads((root/'collector-build.json').read_text(encoding='utf-8'))
        sha=build['collector_git_sha'];branch=build['branch']
        if build['collector_hash']!=collector_hash:raise ValueError('COLLECTOR_CHANGED')
    if not re.fullmatch('[0-9a-f]{40}',sha):raise ValueError('CODE_IDENTITY_REQUIRED')
    b=Baseline();cfg=b.configuration()
    return dict(baseline_git_sha=APPROVED,collector_git_sha=sha,collector_hash=collector_hash,branch=branch,
        baseline_lock_hash=digest(lock),baseline_config_hash=b.hash,
        prediction_config_hash=digest({k:cfg[k] for k in ('model_hash','model_version','feature_hash','feature_version','calibration_version')}),
        decision_config_hash=digest(cfg['decision_template']),edge_config_hash=b.edge.hash,
        execution_config_hash=b.execution.hash,risk_config_hash=b.risk.hash,calibration_config_hash=digest(cfg['analytics']),
        model_hash=b.model_hash,model_version=b.model_version,model_artifact='NOT_APPLICABLE_ARCHIVED_PREDICTION_INPUT',
        m8_contract_hash=file_hash(root/'docs/architecture/V3_M8_RESEARCH_VALIDATION_CONTRACT.md'),
        evidence_only_rationale='Collector commit separate from explicitly approved M8; all locked M1-M8 source/contracts unchanged')
