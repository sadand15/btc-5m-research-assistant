"""Verify two fresh synthetic runs against committed SHA256 expectations."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from btc5_v3.research_adapter.offline_demo import run


def verify(root=ROOT):
    root = Path(root)
    if subprocess.check_output(['git','status','--porcelain'], cwd=root).strip():
        raise ValueError('CLEAN_CHECKOUT_REQUIRED')
    expected = json.loads((root/'tests/fixtures/m102_reproduction.json').read_text(encoding='utf-8'))
    actual = []
    for _ in range(2):
        with tempfile.TemporaryDirectory(prefix='m102-independent-') as folder:
            report, html = run(folder)
            hashes = {name:sha256((html.parent/name).read_bytes()).hexdigest()
                      for name in ('input.json','report.json','report.html')}
            if hashes != expected['files'] or report['report_hash'] != expected['report_hash']:
                raise ValueError('REPRODUCTION_HASH_MISMATCH')
            if report['calibration'] != expected['calibration']:
                raise ValueError('METRIC_MISMATCH')
            rejected = {r['id']:r['reasons'] for r in report['rows'] if not r['scores_included']}
            if rejected != expected['rejections']:
                raise ValueError('REJECTION_MISMATCH')
            actual.append(hashes)
    if actual[0] != actual[1]:
        raise ValueError('NONDETERMINISTIC_OUTPUT')
    lock = json.loads((root/'src/btc5_v3/prospective/baseline_lock.json').read_text(encoding='utf-8'))
    for name, expected_hash in lock['files'].items():
        normalized=(root/name).read_text(encoding='utf-8').replace('\r\n','\n').encode()
        if sha256(normalized).hexdigest() != expected_hash:
            raise ValueError('PROTECTED_FILE_MISMATCH')
    report, html = run(root)
    result = dict(status='REPRODUCED', real_status='REAL_DATA_NOT_READY',
        commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
        python=sys.version.split()[0], protected_files=len(lock['files']),
        accepted=report['accepted'], rejected=report['rejected'], files=actual[0], html=str(html))
    (html.parent/'verification.json').write_bytes((json.dumps(result,sort_keys=True,indent=2)+'\n').encode())
    return result


if __name__=='__main__':
    print(json.dumps(verify(),sort_keys=True,indent=2))
