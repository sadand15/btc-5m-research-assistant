"""Deterministic synthetic lifecycle demonstration. Never starts a real source."""
import argparse
from pathlib import Path
import tempfile
from btc5_v3.encoding import canonical, digest
from .identity import APPROVED
from .models import definition
from .sources import source_spec
from .store import Study, Writer, read
from .adapter import load_sealed


class Clock:
    def __init__(self):self.at=300000
    def __call__(self):return self.at


def proof():
    return dict(baseline_git_sha=APPROVED,collector_git_sha='a'*40,branch='synthetic-test',
                baseline_config_hash=digest('synthetic-demo-not-a-real-study'))


def run_demo(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    results={}
    with tempfile.TemporaryDirectory(prefix='m9-synthetic-',dir=root) as folder:
        def setup(name):
            s=Study(folder,name)
            s.create(definition(name,name+'-data',1,300000,7500000,source_spec('synthetic'),proof(),'SYNTHETIC_TEST'))
            s.arm(2,proof());return s,Clock()
        def emit(w,c,key='one'):
            return w.observation('synthetic',key,c(),c(),{'price':'100'})
        s,c=setup('normal');results['create_and_freeze']=s.status(c())['state']=='ARMED'
        with Writer(s,proof,c) as w:
            w.heartbeat();emit(w,c)
            results['duplicate_idempotence']=not emit(w,c)
            c.at=3600000;emit(w,c,'two');w.heartbeat();w.stop()
        results['multi_segment']=s.verify()['segments']==2
        c.at+=120000
        with Writer(s,proof,c) as w:
            w.heartbeat();emit(w,c,'three')
            results['restart']=s.status(c())['observations']==3
            results['collector_outage']=any(g['type']=='COLLECTOR_DOWN' for g in s.status(c())['gaps'])
            w.source_failure();c.at+=30000;w.heartbeat();emit(w,c,'four')
            results['network_outage']=any(g['type']=='SOURCE_CONNECTION_FAILURE' for g in s.status(c())['gaps'])
            c.at=7500000
            try:emit(w,c,'late')
            except ValueError:results['end_rejects_observation']=True
            seal=w.seal()
        results['sealed_root']=s.verify(require_sealed=True)['valid'] and len(seal['dataset_root_hash'])==64
        results['sealed_adapter']=load_sealed(s,c()).manifest.evidence_mode=='PROSPECTIVE'
        try:
            with Writer(s,proof,c):pass
        except ValueError:results['sealed_write_rejected']=True
        status=canonical(s.status(c())).lower()
        results['peeking_guard']=not any(x in status for x in ('pnl','accuracy','win_rate','brier','probability'))
        u,uc=setup('unsealed')
        try:load_sealed(u,uc())
        except ValueError:results['unsealed_adapter_rejected']=True
        try:
            with Writer(u,lambda:dict(proof(),collector_git_sha='b'*40),uc):pass
        except ValueError:results['baseline_change_interrupt']=u.status(uc())['state']=='INTERRUPTED'
        p,pc=setup('partial')
        def crash(where):
            if where=='after_segment_rename':raise RuntimeError('synthetic_crash')
        try:
            with Writer(p,proof,pc,fault=crash) as w:emit(w,pc);w.finalize()
        except RuntimeError:pass
        p.path('partial.json.tmp').write_bytes(b'{partial')
        with Writer(p,proof,pc) as w:w.finalize()
        results['partial_crash_recovery']=p.verify()['valid'] and bool(list(p.folder.glob('*.quarantined')))
        path=p.path('segment-000001.json');original=path.read_bytes();path.write_bytes(b'{}')
        try:p.verify()
        except ValueError:results['tamper_detection']=True
        path.write_bytes(original);path.unlink()
        try:p.verify()
        except ValueError:results['missing_segment_detection']=True
    if len(results)!=16 or not all(results.values()):raise AssertionError(results)
    return dict(origin='SYNTHETIC_TEST',scenarios=results,passed=len(results),real_study_started=False)


def main():
    p=argparse.ArgumentParser();p.add_argument('--project-root',type=Path,default=Path('.'));args=p.parse_args()
    print(canonical(run_demo(args.project_root/'runtime/v3/m9-demo')))


if __name__=='__main__':main()
