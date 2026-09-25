"""Two synthetic ingestion events. No feeds, predictions, decisions or trading."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess

from btc5_v3.config.models import StorageConfig,ValidatorConfig
from btc5_v3.experiments.models import Experiment
from btc5_v3.storage.database import Database
from btc5_v3.storage.repository import Repository


def run_demo(project_root,git_commit):
    root=Path(project_root)
    cfg=ValidatorConfig(market_id='synthetic-demo',feed='SYNTHETIC',rule_hash='synthetic-rule-v1')
    experiment=Experiment('demo-'+git_commit,git_commit,'synthetic-events-v1',42,900,cfg.hash)
    payload=dict(market_id=cfg.market_id,source_at=1000,expiry=301000,market_type='CRYPTO_UP_DOWN',
                 feed=cfg.feed,rule_hash=cfg.rule_hash,outcome_mapping='YES_UP',
                 yes_bids=[['0.40','10']],yes_asks=[['0.42','12']])
    crossed=deepcopy(payload);crossed['yes_bids']=[['0.60','10']]
    with Database(StorageConfig(project_root=root,database=Path('runtime/v3/demo.sqlite'))) as db:
        repo=Repository(db,cfg);repo.register(experiment)
        events=[]
        for sequence,item in enumerate((payload,crossed),1):
            result=repo.ingest(item,experiment_id=experiment.id,source='synthetic',received_at=1010,
                               sequence=sequence,evaluation_at=1010)
            events.append(dict(raw_event_id=result.raw_event_id,validation_id=result.validation_id,
                               status=result.status,reasons=result.all_reasons,
                               snapshot_id=result.snapshot.snapshot_id if result.snapshot else None))
        counts=repo.counts(experiment.id)
    return {'mode':'SYNTHETIC_INGESTION_ONLY','experiment_id':experiment.id,'events':events,'counts':counts}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',type=Path,default=Path.cwd())
    args=parser.parse_args()
    if subprocess.check_output(['git','status','--porcelain'],cwd=args.project_root,text=True).strip():
        raise ValueError('Commit changes before running a versioned demo')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=args.project_root,text=True).strip()
    print(json.dumps(run_demo(args.project_root,commit),indent=2))


if __name__=='__main__':main()
