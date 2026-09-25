"""Four synthetic M3 scenarios; candidates only, never orders."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess

from btc5_v3.config.models import StorageConfig, ValidatorConfig
from btc5_v3.encoding import canonical, digest
from btc5_v3.experiments.models import Experiment
from btc5_v3.models.models import Prediction, TargetDefinition
from btc5_v3.edge.costs import EdgeConfig
from btc5_v3.decision.config import DecisionConfig
from btc5_v3.storage.database import Database
from btc5_v3.storage.repository import Repository
from btc5_v3.storage.edge_repository import EdgeRepository
from btc5_v3.storage.decision_repository import DecisionRepository


def run_demo(project_root, git_commit):
    vcfg=ValidatorConfig('m3-demo-market','SYNTHETIC','m3-demo-rule')
    exp=Experiment('m3-demo-'+git_commit,git_commit,'m3-synthetic-v1',42,900,vcfg.hash)
    # This is an explicit synthetic semantic assertion, not a claim about a real oracle.
    semantic_hash=digest({'contract':'synthetic-market-yes-v1','source':'synthetic-oracle',
                          'feed':'SYNTHETIC','model_hash':'a'*64,'rule_hash':vcfg.rule_hash})
    scenarios=(('A_ADMISSIBLE',4000,'.59','.61','100'),
               ('B_STALE_SOURCE',1000,'.59','.61','100'),
               ('C_WIDE_SPREAD',4000,'.55','.65','100'),
               ('D_INSUFFICIENT_DEPTH',4000,'.59','.61','60'))
    results=[]
    with Database(StorageConfig(project_root=Path(project_root),database=Path('runtime/v3/m3-demo.sqlite'))) as db:
        market=Repository(db,vcfg);market.register(exp)
        edges=EdgeRepository(market);decisions=DecisionRepository(edges)
        for sequence,(name,source_at,bid,ask,quantity) in enumerate(scenarios,1):
            payload=dict(market_id=vcfg.market_id,source_at=source_at,expiry=301000,market_type='CRYPTO_UP_DOWN',
                         feed=vcfg.feed,rule_hash=vcfg.rule_hash,outcome_mapping='YES_UP',
                         yes_bids=[[bid,'100']],yes_asks=[[ask,quantity]],market_status='OPEN',
                         market_status_at=4000,market_status_available_at=4000)
            s=market.ingest(payload,experiment_id=exp.id,source='synthetic',received_at=4000,
                            sequence=sequence,evaluation_at=4000).snapshot
            p=Prediction(exp.id,name,vcfg.market_id,'.90','synthetic-model','a'*64,'synthetic-feature','b'*64,
                         4000,4500,TargetDefinition('YES_UP',vcfg.rule_hash,301000,target_source='synthetic-oracle',
                                                   target_feed='SYNTHETIC'),'none')
            ec=EdgeConfig(target_shares=100,minimum_executable_fraction='.1')
            e=edges.evaluate_and_store(s.snapshot_id,p,ec,evaluation_at=5000)
            dc=DecisionConfig(vcfg.market_id,'synthetic',vcfg.feed,vcfg.rule_hash,'YES_UP','synthetic-oracle',
                              'a'*64,ec.hash,target_source_confirmed=True,semantic_contract_hash=semantic_hash)
            d=decisions.decide_and_store(dc,experiment_id=exp.id,attempt_key=name,evaluation_at=5000,
                                         prediction_id=p.prediction_id,snapshot_id=s.snapshot_id,edge_id=e.edge_id)
            assert decisions.get_decision(d.decision_id)==d
            results.append(dict(scenario=name,decision=asdict(d)))
    return dict(mode='SYNTHETIC_ADMISSIBILITY_ONLY',experiment_id=exp.id,scenarios=results)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',type=Path,default=Path.cwd())
    args=parser.parse_args()
    if subprocess.check_output(['git','status','--porcelain'],cwd=args.project_root,text=True).strip():
        raise ValueError('Commit changes before running a versioned demo')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=args.project_root,text=True).strip()
    print(json.dumps(json.loads(canonical(run_demo(args.project_root,commit))),indent=2))


if __name__=='__main__':main()
