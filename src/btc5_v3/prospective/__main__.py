"""Operational CLI only. No analysis, optimization, live orders or implicit study."""
import argparse
from datetime import datetime
from pathlib import Path
from btc5_v3.encoding import canonical
from .identity import identity
from .models import definition, CYCLE_MS
from .store import Study, Writer, read
from .sources import source_spec, PredictFun
from .collector import collect, utc_ms
from .adapter import load_sealed


def utc(value):
    date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if date.tzinfo is None or date.utcoffset().total_seconds() != 0:
        raise argparse.ArgumentTypeError('explicit UTC required')
    return int(date.timestamp()*1000)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root', type=Path, default=Path('.'))
    p.add_argument('--study', required=True)
    sub = p.add_subparsers(dest='command', required=True)
    create = sub.add_parser('create')
    create.add_argument('--dataset', required=True)
    create.add_argument('--source', choices=['binance','predictfun'], required=True)
    create.add_argument('--start', type=utc)
    create.add_argument('--duration-hours', type=int, default=24)
    for name in ('arm','collect','status','health','end','seal','verify','adapter'):
        sub.add_parser(name)
    args = p.parse_args(argv)
    study = Study(args.project_root, args.study)
    proof = lambda: identity(args.project_root)
    try:
        if args.command == 'create':
            now = utc_ms()
            if not 1 <= args.duration_hours <= 24*90:
                raise ValueError('DURATION_OUT_OF_RANGE')
            start = args.start or (now//CYCLE_MS+2)*CYCLE_MS
            profile = PredictFun(utc_ms).discover_profile() if args.source=='predictfun' else None
            study.create(definition(args.study,args.dataset,now,start,start+args.duration_hours*3600000,
                                    source_spec(args.source,profile=profile),proof()))
            result = study.status(now)
        elif args.command == 'arm':
            study.arm(utc_ms(),proof()); result=study.status(utc_ms())
        elif args.command == 'collect':
            collect(study,proof); result=study.status(utc_ms())
        elif args.command in ('status','health'):
            result=study.status(utc_ms())
            if args.command=='health':
                age=result.get('heartbeat_age_ms')
                healthy=(result['state'] in ('ARMED','COLLECTING','DEGRADED') and age is not None and 0<=age<=90000)
                print(canonical({'healthy':healthy,'state':result['state']}))
                return 0 if healthy else 1
        elif args.command=='verify':
            result=study.verify()
        elif args.command=='adapter':
            candidate=load_sealed(study,utc_ms())
            result=dict(dataset_root_hash=candidate.dataset_root_hash,role=candidate.manifest.role,
                        evidence_mode=candidate.manifest.evidence_mode,readiness=candidate.readiness)
        elif args.command=='seal' and study.path('sealed.json').exists():
            study.verify(require_sealed=True);result={'dataset_root_hash':read(study.path('sealed.json'))['dataset_root_hash']}
        else:
            with Writer(study,proof,utc_ms) as writer:
                if args.command=='end':writer.end();result=study.status(utc_ms())
                else:result={'dataset_root_hash':writer.seal()['dataset_root_hash']}
        print(canonical(result))
        return 0
    except Exception as error:
        # Fixed error category only; no arbitrary provider/OS credential-bearing text.
        print(canonical({'ok':False,'error_type':type(error).__name__,
                         'message':'OPERATION_REFUSED_CHECK_OPERATIONAL_STATE_AND_FROZEN_CONTRACT'}))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
