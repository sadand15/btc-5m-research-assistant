"""Preregistered synthetic execution cases and complete one-factor research grids."""
import argparse
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import json
import subprocess

from btc5_v3.encoding import digest,canonical
from btc5_v3.config.models import StorageConfig,ValidatorConfig
from btc5_v3.market.normalize import raw_event
from btc5_v3.market.validation import validate_market
from btc5_v3.models.models import Prediction,TargetDefinition
from btc5_v3.edge.costs import EdgeConfig,FeeModel
from btc5_v3.edge.engine import evaluate_edge
from btc5_v3.decision.config import DecisionConfig
from btc5_v3.decision.policy import decide
from btc5_v3.analytics.models import ResearchObservation,ResolvedOutcome
from btc5_v3.path.models import MarketPathPoint
from btc5_v3.experiments.models import Experiment
from btc5_v3.execution.models import ExecutionConfig,ExitPolicy,LATENCY_GRID,SIZE_GRID,policy_grid
from btc5_v3.execution.report import study_report,markdown
from btc5_v3.storage.database import Database
from btc5_v3.storage.execution_repository import ExecutionRepository
from btc5_v3.storage.analytics_repository import RESEARCH_CONTRACT

D=Decimal
START=1704067200000
TD=START+60000
EXPIRY=START+300000
CUTOFF=EXPIRY+2000


def snapshot(experiment_id,market,sequence,at,*,bids=(('.10','1000'),),asks=(('.12','1000'),),source_at=None,available_at=None,side='YES',status='OPEN'):
    source_at=at if source_at is None else source_at;available_at=at if available_at is None else available_at
    if side=='NO':
        bids,asks=tuple((str(1-D(p)),q) for p,q in asks),tuple((str(1-D(p)),q) for p,q in bids)
    cfg=ValidatorConfig(market,'SYNTHETIC','synthetic-rule-v1')
    payload=dict(market_id=market,source_at=source_at,expiry=EXPIRY,market_type='CRYPTO_UP_DOWN',
        feed=cfg.feed,rule_hash=cfg.rule_hash,outcome_mapping='YES_UP',yes_bids=[list(x) for x in bids],yes_asks=[list(x) for x in asks],
        market_status=status,market_status_at=source_at,market_status_available_at=at)
    raw=raw_event(payload,experiment_id=experiment_id,source='synthetic',received_at=at,sequence=sequence)
    result=validate_market(raw,cfg,evaluation_at=available_at)
    if result.snapshot is None:raise ValueError('invalid synthetic execution book')
    return result.snapshot


def candidate(experiment_id='execution-test',market='m',*,side='YES',ask='.12',approved_size='100',stale=False,edge_latency_cost=0):
    s=snapshot(experiment_id,market,1,TD-10,bids=((str(D(ask)-D('.02')),'1000'),),asks=((ask,'1000'),),
               source_at=TD-4000 if stale else TD-10,side=side)
    modelhash=digest('synthetic-execution-model')
    p=Prediction(experiment_id,'prediction-'+market,market,D('.95') if side=='YES' else D('.05'),
        'synthetic-execution-model',modelhash,'synthetic-features','b'*64,TD-10,TD-5,
        TargetDefinition('YES_UP','synthetic-rule-v1',EXPIRY,target_source='synthetic-oracle',target_feed='SYNTHETIC'),'none')
    ec=EdgeConfig(target_shares=D(approved_size),latency_cost_assumption=edge_latency_cost);e=evaluate_edge(s,p,ec,evaluation_at=TD)
    dc=DecisionConfig(market,'synthetic','SYNTHETIC','synthetic-rule-v1','YES_UP','synthetic-oracle',modelhash,ec.hash,
        target_source_confirmed=True,semantic_contract_hash=digest('SYNTHETIC_ONLY'))
    d=decide(s,p,e,dc,experiment_id=experiment_id,attempt_key='decision-'+market,evaluation_at=TD)
    return ResearchObservation.from_inputs(p,s,e,d)


def resolved(experiment_id='execution-test',market='m',payout=0):
    return ResolvedOutcome(experiment_id,market,EXPIRY,EXPIRY+1000,D(payout),'synthetic-settlement','synthetic-rule-v1','synthetic-settlement-v1')


def cases(experiment_id):
    output=[]
    for market,ask,payout,side in (('full-hold','.50',1,'YES'),('partial-entry','.12',0,'YES'),
        ('adverse-latency','.20',1,'YES'),('temporary-rebound','.12',0,'YES'),
        ('hold-better','.12',1,'YES'),('missed-exit','.12',0,'YES'),
        ('multiple-partial-split','.12',D('.5'),'YES'),('no-side','.12',1,'NO')):
        original=candidate(experiment_id,market,ask=ask,side=side);books=[];seq=2
        for delay in (100,250,500,2000):
            price=D('.35') if market=='adverse-latency' and delay>=250 else D(ask)
            qty='60' if market=='partial-entry' else '200'
            books.append(MarketPathPoint.from_snapshot(snapshot(experiment_id,market,seq,TD+delay,
                bids=((str(price-D('.02')),qty),),asks=((str(price),qty),),side=side)));seq+=1
        if market not in ('full-hold','partial-entry','adverse-latency'):
            if market=='multiple-partial-split':later=[(3000,'.60','100'),(3250,'.55','30'),(3500,'.60','100'),(3750,'.55','40')]
            else:later=[(3000,'.60','100'),(3250,'.35' if market=='temporary-rebound' else '.45','100')]
            for delay,bid,qty in later:
                books.append(MarketPathPoint.from_snapshot(snapshot(experiment_id,market,seq,TD+delay,
                    bids=((bid,qty),),asks=((str(D(bid)+D('.02')),'100'),),side=side,
                    source_at=TD+3000 if market=='missed-exit' and delay==3250 else None)));seq+=1
        output.append((market,original,books,resolved(experiment_id,market,payout)))
    return output


def run_demo(root,code):
    root=Path(root);exp='m5-demo-'+code;rows=[]
    with Database(StorageConfig(root,Path('runtime/v3/m5-demo.sqlite'))) as db:
        repo=ExecutionRepository(db);repo.register(Experiment(exp,code,'m5-synthetic-v1',42,START,digest(RESEARCH_CONTRACT)))
        for name,original,books,outcome in cases(exp):
            base=ExecutionConfig(entry_fee=FeeModel(rate=D('.005')),exit_fee=FeeModel(rate=D('.005')),
                                 settlement_fee=FeeModel(rate=D('.001')))
            specs=[('EXIT_POLICY',policy.kind+':'+str(policy.rebound if policy.rebound is not None else policy.tte_ms),base,policy) for policy in policy_grid()]
            specs += [('LATENCY',str(n),replace(base,decision_to_order_latency_ms=n,exit_latency_ms=n),ExitPolicy('BID_REBOUND',D('.20'))) for n in LATENCY_GRID]
            specs += [('SIZE',str(n),replace(base,requested_shares=n),ExitPolicy('BID_REBOUND',D('.20'))) for n in SIZE_GRID]
            for dimension,value,cfg,policy in specs:
                result=repo.run(original,books,outcome,cfg,policy,experiment_id=exp,code_git=code,cutoff=CUTOFF,created_at=CUTOFF)
                rows.append(dict(case=name,dimension=dimension,value=value,original=original.data(),result=result.data(),execution_id=result.execution_id))
            assert repo.get_run(result.execution_id)==result
    report=study_report(rows,experiment_id=exp,code_git=code)
    for name,value in (('m5-report.json',canonical(report)),('m5-report.md',markdown(report))):
        path=StorageConfig(root,Path('runtime/v3')/name).resolved_path();path.write_bytes(value.encode())
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--project-root',type=Path,default=Path.cwd());args=parser.parse_args()
    if subprocess.check_output(['git','status','--porcelain'],cwd=args.project_root,text=True).strip():raise ValueError('clean committed execution source required')
    code=subprocess.check_output(['git','rev-parse','HEAD'],cwd=args.project_root,text=True).strip();report=run_demo(args.project_root,code)
    print(json.dumps(dict(mode=report['mode'],cases=report['cases'],grid_rows=len(report['rows']),artifacts=['runtime/v3/m5-report.json','runtime/v3/m5-report.md'])))


if __name__=='__main__':main()
