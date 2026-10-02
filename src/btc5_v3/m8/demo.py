"""Twelve explicit synthetic research scenarios; no external data or credentials."""
import argparse
from dataclasses import asdict,replace
from decimal import Decimal as D
import json
from pathlib import Path
import sqlite3
import subprocess

from btc5_v3.encoding import canonical,digest
from btc5_v3.config.models import StorageConfig
from btc5_v3.models.models import Prediction
from btc5_v3.risk.demo import candidate,book,outcome,healthy,TD
from btc5_v3.m8.models import dataset,Baseline
from btc5_v3.m8.research import run_research
from btc5_v3.m8.report import write_reports
from btc5_v3.data_quality.checks import assess
from btc5_v3.robustness.sensitivity import sensitivity
from btc5_v3.validation.datasets import load_dataset

ARCHIVE='runtime/v3/m8/synthetic-inputs.sqlite'


def fixture(n,at,*,p='.95',ask='.50',spread='.02',payout=1):
    original=candidate('m8-synthetic','m8-market-'+str(n),at=at,ask=ask)
    data=original.data();s=data['snapshot'];prediction=replace(Prediction.from_dict(data['prediction']),p_yes=D(p))
    raw=dict(market_id=s['market_id'],source_at=s['source_at'],expiry=s['expiry'],market_type='CRYPTO_UP_DOWN',
        feed=s['feed'],rule_hash=s['rule_hash'],outcome_mapping=s['outcome_mapping'],
        yes_bids=[[str(D(ask)-D(spread)),'1000']],yes_asks=[[ask,'1000']],market_status='OPEN',
        market_status_at=s['source_at'],market_status_available_at=s['source_at'])
    return dict(id='m8-row-'+str(n),at=at,sequence=n,source='synthetic',raw=raw,received_at=s['received_at'],
         available_at=s['available_at'],prediction=json.loads(prediction.to_json()),health=asdict(healthy(at)),
         books=[dict(available_at=at+250,point=asdict(book(original,at+250)))],
         outcome=json.loads(outcome(original,payout).to_json()))


def fixtures():
    dev=[fixture(i,TD+i*242000,p='.515' if i%3==0 else '.95',spread='.06' if i==6 else '.04' if i%2 else '.02') for i in range(24)]
    dev.pop(1)  # Declared cadence records the actual missing slot.
    dev[2]['raw']['source_at']-=4000
    dev[3]['raw']['source_at']=dev[3]['at']+100
    dev[4]['venue_prices']=[dict(price='100',available_at=dev[4]['at']),dict(price='103',available_at=dev[4]['at'])]
    val=[fixture(100+i,TD+(32+i)*242000,payout=0,spread='.04' if i%2 else '.02') for i in range(24)]
    return dataset('m8-development','DEVELOPMENT',dev,cadence_ms=242000),dataset('m8-validation','VALIDATION',val,cadence_ms=242000)


def save_fixtures(root,datasets):
    """Explicit demo writer only; research readers never call this function."""
    path=StorageConfig(Path(root),ARCHIVE).resolved_path();path.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE IF NOT EXISTS m8_dataset_manifests(id TEXT PRIMARY KEY,metadata_json TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS m8_dataset_records(dataset_id TEXT PRIMARY KEY,records_json TEXT NOT NULL)')
        for ds in datasets:
            for table,key,value in (('m8_dataset_manifests','id',canonical(asdict(ds.manifest))),('m8_dataset_records','dataset_id',ds.records_json)):
                old=c.execute(f'SELECT * FROM {table} WHERE {key}=?',(ds.manifest.dataset_id,)).fetchone()
                if old is not None:
                    if old[1]!=value:raise ValueError('synthetic fixture conflict; no overwrite')
                else:c.execute(f'INSERT INTO {table} VALUES (?,?)',(ds.manifest.dataset_id,value))


def run_demo(root,code_git,branch='UNKNOWN'):
    import hashlib
    dev,val=fixtures();save_fixtures(root,(dev,val));path=StorageConfig(Path(root),ARCHIVE).resolved_path()
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    dev=load_dataset(root,ARCHIVE,dev.manifest.dataset_id,required_role='DEVELOPMENT')
    val=load_dataset(root,ARCHIVE,val.manifest.dataset_id,required_role='VALIDATION')
    cutoff=val.manifest.time_end+241000
    reports=run_research(dev,val,cutoff=cutoff,code_git=code_git,branch=branch)
    q=reports['data_quality'][dev.manifest.dataset_id]['report']
    plateau=sensitivity(dataset('plateau','DEVELOPMENT',[fixture(1000,TD)]),cutoff=TD+241000,code_git=code_git)
    cliff=sensitivity(dataset('cliff','DEVELOPMENT',[fixture(1001,TD,p='.515')]),cutoff=TD+241000,code_git=code_git)
    cases=dict(clean=assess(fixture(1002,TD))['state']=='VALID',missing_gap=q['coverage']['gap_count']>0,
       stale=q['stale_count']>0,timestamp_violation=q['counts']['INVALID']>0,
       venue_divergence=q['divergence_exceedances']>0,
       deterministic_replay=reports['validation']['status']=='PASS',
       regime_split=len(reports['validation']['cohorts']['QUALITY_PASSED']['regimes']['spread'])>=2,
       sensitivity_plateau=len(plateau['stability']['plateau_intervals'])==4,
       sensitivity_cliff=bool(cliff['stability']['cliff_intervals']),
       ablation=reports['robustness']['ablation']['delta']['candidate_count']>0,
       bootstrap=reports['robustness']['uncertainty']['mean_edge']['status']=='ESTIMATE',
       calibration_drift=D(reports['robustness']['calibration_drift']['overall']['brier_delta'])>D('.1'))
    if not all(cases.values()):raise AssertionError(canonical(cases))
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before
    reports['summary']['synthetic_demo_cases']=cases
    reports['summary']['source_database_unchanged']=True
    paths=write_reports(root,reports)
    return dict(cases=cases,artifacts=paths,research_hash=digest(reports),code_git=code_git)


def main(track='unified'):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project-root',type=Path,default=Path.cwd());args=p.parse_args()
    def git(*a):return subprocess.check_output(['git',*a],cwd=args.project_root,text=True).strip()
    if git('status','--porcelain'):raise ValueError('clean committed M8 source required')
    result=run_demo(args.project_root,git('rev-parse','HEAD'),git('branch','--show-current') or 'UNKNOWN')
    print(canonical(dict(track=track,mode='SYNTHETIC',cases=result['cases'],research_hash=result['research_hash'],artifacts=result['artifacts'])))


if __name__=='__main__':main()
