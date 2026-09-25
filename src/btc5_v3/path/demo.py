"""Synthetic intracycle paths only; no production reads or network calls."""
import argparse
from decimal import Decimal
from pathlib import Path
import json
import subprocess

from btc5_v3.config.models import StorageConfig, ValidatorConfig
from btc5_v3.encoding import digest
from btc5_v3.experiments.models import Experiment
from btc5_v3.market.normalize import raw_event
from btc5_v3.market.validation import validate_market
from btc5_v3.analytics.models import ResolvedOutcome
from btc5_v3.path.models import IntracyclePathConfig,MarketPathPoint
from btc5_v3.path.report import markdown
from btc5_v3.storage.database import Database
from btc5_v3.storage.analytics_repository import RESEARCH_CONTRACT
from btc5_v3.storage.path_repository import PathRepository

START=1704067200000
D=Decimal


def point(market,index,bid,ask,*,experiment_id='path-test',tte=240000,source_age=0,available_delay=0,depth='10',expiry=START+300000,reference=None):
    at=expiry-tte;cfg=ValidatorConfig(market,'SYNTHETIC','synthetic-rule-v1')
    payload=dict(market_id=market,source_at=at-source_age,expiry=expiry,market_type='CRYPTO_UP_DOWN',
        feed=cfg.feed,rule_hash=cfg.rule_hash,outcome_mapping='YES_UP',yes_bids=[[str(bid),depth]],yes_asks=[[str(ask),depth]])
    if reference: payload.update(reference_underlying_price=reference[0],reference_price_at=reference[1])
    raw=raw_event(payload,experiment_id=experiment_id,source='synthetic',received_at=at,sequence=index)
    snapshot=validate_market(raw,cfg,evaluation_at=at+available_delay).snapshot
    if snapshot is None: raise ValueError('invalid synthetic snapshot')
    return MarketPathPoint.from_snapshot(snapshot)


def dataset(experiment_id):
    specs={
        'scenario-a':[(240000,'.09','.11'),(180000,'.18','.21'),(60000,'.88','.91')],
        # Requested .90 mid with .25 bid would require illegal ask=1.55.
        'wide-spread-b':[(240000,'.05','.15'),(180000,'.25','.95')],
        'temporary-c':[(240000,'.09','.11'),(237000,'.59','.61'),(234000,'.07','.09')],
        'winning-d':[(240000,'.09','.11'),(237000,'.29','.31'),(234000,'.79','.81')],
        'continuation':[(240000,'.09','.11'),(237000,'.05','.07'),(234000,'.02','.04')],
        'whipsaw':[(240000,'.19','.21'),(237000,'.69','.71'),(234000,'.24','.26'),(231000,'.79','.81')],
        'stale-peak':[(240000,'.09','.11'),(237000,'.89','.91'),(234000,'.19','.21')],
        'split':[(240000,'.39','.41'),(237000,'.49','.51')]}
    points=[];outcomes=[]
    for market,quotes in specs.items():
        for i,(tte,bid,ask) in enumerate(quotes):
            points.append(point(market,i+1,bid,ask,experiment_id=experiment_id,tte=tte,
                                source_age=10000 if market=='stale-peak' and i==1 else 0))
        payout=D('.5') if market=='split' else D(market in ('winning-d','scenario-a'))
        outcomes.append(ResolvedOutcome(experiment_id,market,START+300000,START+301000,payout,
                                       'synthetic-settlement','synthetic-rule-v1','synthetic-settlement-v1'))
    return points,outcomes


def run_demo(root,code):
    root=Path(root);exp='m4.5-demo-'+code;points,outcomes=dataset(exp);cutoff=START+302000
    with Database(StorageConfig(root,Path('runtime/v3/m4-5-demo.sqlite'))) as db:
        repo=PathRepository(db)
        repo.register(Experiment(exp,code,'m4.5-synthetic-v1',42,START,digest(RESEARCH_CONTRACT)))
        result=repo.run(points,outcomes,IntracyclePathConfig(),experiment_id=exp,code_git=code,cutoff=cutoff,created_at=cutoff)
        assert repo.get_run(result.analysis_id)==result
    for name,value in (('m4-5-report.json',result.to_json()),('m4-5-report.md',markdown(result))):
        path=StorageConfig(root,Path('runtime/v3')/name).resolved_path();path.write_bytes(value.encode())
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--project-root',type=Path,default=Path.cwd());args=parser.parse_args()
    if subprocess.check_output(['git','status','--porcelain'],cwd=args.project_root,text=True).strip(): raise ValueError('clean committed source required')
    code=subprocess.check_output(['git','rev-parse','HEAD'],cwd=args.project_root,text=True).strip()
    result=run_demo(args.project_root,code)
    print(json.dumps(dict(mode='SYNTHETIC_PATH_ONLY',analysis_id=result.analysis_id,
                         artifacts=['runtime/v3/m4-5-report.json','runtime/v3/m4-5-report.md'])))


if __name__=='__main__': main()
