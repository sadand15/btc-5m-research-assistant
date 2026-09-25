"""Synthetic research archive; no production reads, API calls, training or orders."""
import argparse
from decimal import Decimal
from pathlib import Path
import json
import subprocess

from btc5_v3.config.models import StorageConfig,ValidatorConfig
from btc5_v3.encoding import digest
from btc5_v3.experiments.models import Experiment
from btc5_v3.market.normalize import raw_event
from btc5_v3.market.validation import validate_market
from btc5_v3.models.models import Prediction,TargetDefinition
from btc5_v3.edge.costs import EdgeConfig,FeeModel
from btc5_v3.edge.engine import evaluate_edge
from btc5_v3.decision.config import DecisionConfig
from btc5_v3.decision.policy import decide
from btc5_v3.analytics.models import AnalyticsConfig,ResearchObservation,ResolvedOutcome
from btc5_v3.analytics.report import markdown
from btc5_v3.storage.database import Database
from btc5_v3.storage.analytics_repository import AnalyticsRepository,RESEARCH_CONTRACT

D=Decimal


def synthetic_observation(experiment_id,index,*,p='.8',payout=1,model='synthetic-model',tte=90000,
                          delta='.07',stale=False,fee='.005',fee_model=None,at=None):
    at=1704067205000+index*1000 if at is None else at
    market='synthetic-market-'+str(index);cfg=ValidatorConfig(market,'SYNTHETIC','synthetic-rule-v1')
    prob=D(p);mid=prob-D(delta) if prob>=D('.5') else prob+D(delta)
    payload=dict(market_id=market,source_at=at-(4000 if stale else 1000),expiry=at+tte,market_type='CRYPTO_UP_DOWN',
                 feed=cfg.feed,rule_hash=cfg.rule_hash,outcome_mapping='YES_UP',
                 yes_bids=[[str(mid-D('.01')),'10']],yes_asks=[[str(mid+D('.01')),'10']],
                 market_status='OPEN',market_status_at=at-1000,market_status_available_at=at-1000)
    raw=raw_event(payload,experiment_id=experiment_id,source='synthetic',received_at=at-1000,sequence=index+1)
    s=validate_market(raw,cfg,evaluation_at=at-1000).snapshot
    if s is None:raise ValueError('invalid synthetic book')
    model_hash=digest(model)
    prediction=Prediction(experiment_id,'p-'+str(index),market,prob,model,model_hash,'synthetic-features','b'*64,
                          at-1000,at-500,TargetDefinition('YES_UP',cfg.rule_hash,s.expiry,target_source='synthetic-oracle',target_feed=cfg.feed),'none')
    ec=EdgeConfig(fee=fee_model or FeeModel(collateral_per_share=fee))
    edge=evaluate_edge(s,prediction,ec,evaluation_at=at)
    dc=DecisionConfig(market,'synthetic',cfg.feed,cfg.rule_hash,'YES_UP','synthetic-oracle',model_hash,ec.hash,
                      target_source_confirmed=True,semantic_contract_hash=digest('SYNTHETIC_CONTRACT_ONLY'))
    decision=decide(s,prediction,edge,dc,experiment_id=experiment_id,attempt_key='d-'+str(index),evaluation_at=at)
    outcome=ResolvedOutcome(experiment_id,market,s.expiry+1000,s.expiry+1500,D(str(payout)),
                            'synthetic-settlement',cfg.rule_hash,'synthetic-settlement-v1')
    return ResearchObservation.from_inputs(prediction,s,edge,decision),outcome


def run_demo(project_root,git_commit):
    root=Path(project_root);experiment_id='m4-demo-'+git_commit
    observations=[];outcomes=[]
    for i in range(64):
        if i<40:
            p='.2' if i<20 else '.8';payout=int(i%20<(4 if i<20 else 16));model='well-calibrated-synthetic'
        elif i<60:
            p='.1' if i<50 else '.9';payout=int(i%2==0);model='overconfident-synthetic'
        else:p='.5';payout=D('.5');model='split-synthetic'
        observation,outcome=synthetic_observation(experiment_id,i,p=p,payout=payout,model=model,
            tte=(20000,45000,90000,150000,240000)[i%5],delta=('.01','.03','.07','.12','.20')[i%5],
            stale=i%10==9,at=1704067205000+(i//20)*86400000+(i%20)*1000)
        observations.append(observation);outcomes.append(outcome)
    cutoff=max(o.available_at for o in outcomes)+1000
    with Database(StorageConfig(project_root=root,database=Path('runtime/v3/m4-demo.sqlite'))) as db:
        repo=AnalyticsRepository(db)
        repo.register(Experiment(experiment_id,git_commit,'m4-synthetic-v1',42,1704067200000,digest(RESEARCH_CONTRACT)))
        result=repo.run(observations,outcomes,AnalyticsConfig(),experiment_id=experiment_id,code_git=git_commit,cutoff=cutoff,created_at=cutoff)
        assert repo.get_run(result.analysis_id)==result
    for name,content in (('m4-report.json',result.to_json()),('m4-report.md',markdown(result))):
        path=StorageConfig(project_root=root,database=Path('runtime/v3')/name).resolved_path()
        path.write_bytes(content.encode('utf-8'))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--project-root',type=Path,default=Path.cwd())
    args=parser.parse_args()
    if subprocess.check_output(['git','status','--porcelain'],cwd=args.project_root,text=True).strip():
        raise ValueError('Commit changes before a versioned research demo')
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=args.project_root,text=True).strip()
    result=run_demo(args.project_root,sha)
    print(json.dumps({'mode':'SYNTHETIC_ANALYTICS_ONLY','analysis_id':result.analysis_id,
                      'artifacts':['runtime/v3/m4-report.json','runtime/v3/m4-report.md']}))


if __name__=='__main__':main()
