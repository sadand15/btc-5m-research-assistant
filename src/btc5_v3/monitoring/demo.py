"""Explicit offline fixture generation, then read-only M7 observation."""
import argparse
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import hashlib,subprocess

from btc5_v3.encoding import canonical,digest
from btc5_v3.config.models import StorageConfig
from btc5_v3.experiments.models import Experiment
from btc5_v3.storage.database import Database
from btc5_v3.storage.risk_repository import RiskRepository
from btc5_v3.storage.analytics_repository import RESEARCH_CONTRACT
from btc5_v3.execution.models import ExitPolicy
from btc5_v3.risk.models import RiskConfig
from btc5_v3.risk.demo import candidate,book,outcome,approve,TD,START
from btc5_v3.monitoring.models import ViewFilter
from btc5_v3.monitoring.service import MonitoringService
from btc5_v3.monitoring.report import markdown

D=Decimal
DATABASE=Path('runtime/v3/m7-dashboard/demo.sqlite')


def build_fixtures(root,code):
    """Writer is confined to this explicit demo step, never dashboard startup."""
    runs=[]
    with Database(StorageConfig(root,DATABASE)) as db:
        repo=RiskRepository(db)
        for name in ('A-normal','B-reduced','C-competition','D-partial','E-daily-pause','F-drawdown'):
            exp='m7-'+name+'-'+code
            repo.register(Experiment(exp,code,'m7-synthetic-fixtures-v1',42,START,digest(RESEARCH_CONTRACT)))
            cfg=RiskConfig()
            if name=='C-competition':cfg=replace(cfg,starting_capital=D(100),max_position_fraction=D(1),max_total_open_exposure_fraction=D(1))
            if name=='F-drawdown':cfg=replace(cfg,max_position_notional=D(300),max_position_fraction=D(1),max_market_exposure=D(500),max_daily_simulated_loss=D(1000))
            run=repo.create_run(exp,code,cfg,TD)
            original=candidate(exp,ask='.60' if name=='E-daily-pause' else '.50',
                shares='180' if name=='B-reduced' else '80' if name=='C-competition' else '300' if name=='F-drawdown' else '100')
            policy=ExitPolicy('FIXED_TTE',tte_ms=60000) if name=='E-daily-pause' else ExitPolicy()
            a=approve(repo,run,original,policy=policy);rid=a['risk_decision']['risk_decision_id']
            if name=='C-competition':
                b=approve(repo,run,candidate(exp,'second',shares='50'))
                assert b['risk_decision']['approved_shares']=='20'
            books=[book(original,TD+250,ask='.75' if name=='D-partial' else '.60' if name=='E-daily-pause' else '.50',
                        bid='.73' if name=='D-partial' else '.58' if name=='E-daily-pause' else '.48',
                        quantity='80' if name=='D-partial' else '1000')]
            at=TD+250;repo.execute(run,rid,books,cutoff=at)
            if name=='E-daily-pause':
                other=candidate(exp,'existing',at=at,ask='.60')
                b=approve(repo,run,other,policy=policy);other_id=b['risk_decision']['risk_decision_id']
                other_books=[book(other,TD+500,bid='.58',ask='.60')]
                repo.execute(run,other_id,other_books,cutoff=TD+500)
                books.append(book(original,TD+180250,seq=3,bid='.10',ask='.12'))
                repo.execute(run,rid,books,cutoff=TD+180250)
                rejected=approve(repo,run,candidate(exp,'blocked',at=TD+180250))
                assert 'DAILY_LOSS_LIMIT' in rejected['risk_decision']['all_reasons']
                other_books.append(book(other,TD+180500,seq=3,bid='.40',ask='.42',quantity='40'))
                repo.execute(run,other_id,other_books,cutoff=TD+180500)
                settlement=outcome(other,1);at=settlement.available_at
                repo.execute(run,other_id,other_books,settlement,cutoff=at)
            elif name=='F-drawdown':
                settlement=outcome(original);at=settlement.available_at
                repo.execute(run,rid,books,settlement,cutoff=at)
                rejected=approve(repo,run,candidate(exp,'blocked',at=at))
                assert 'MAX_DRAWDOWN_REACHED' in rejected['risk_decision']['all_reasons']
            runs.append(dict(case=name,run_id=run,at=at))
    return runs


def run_demo(root,code,*,viewer_branch='UNKNOWN'):
    root=Path(root);runs=build_fixtures(root,code)
    path=StorageConfig(root,DATABASE).resolved_path();before=hashlib.sha256(path.read_bytes()).hexdigest()
    service=MonitoringService(root,DATABASE);cases=[]
    viewer=dict(git_sha=code,branch=viewer_branch,working_tree='CLEAN_COMMITTED_DEMO')
    for item in runs:
        view=service.view(item['run_id'],ViewFilter(item['at'],page_size=200),viewer=viewer)
        again=MonitoringService(root,DATABASE).view(item['run_id'],ViewFilter(item['at'],page_size=200),viewer=viewer)
        assert view==again
        data=view.data()
        assert not data['diagnostics'],data['diagnostics']
        assert data['overview']['reconciliation']=='RECONCILED'
        cases.append(dict(case=item['case'],view_hash=view.hash,view=data))
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before
    report=dict(mode='SYNTHETIC_READ_ONLY_MONITORING',code_git=code,primary_db_unchanged=True,cases=cases)
    for name,value in (('m7-report.json',canonical(report)),('m7-report.md',markdown(report))):
        StorageConfig(root,Path('runtime/v3/m7-dashboard')/name).resolved_path().write_bytes(value.encode('utf-8'))
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project-root',type=Path,default=Path.cwd());args=p.parse_args()
    def git(*cmd):return subprocess.check_output(['git',*cmd],cwd=args.project_root,text=True).strip()
    if git('status','--porcelain'):raise ValueError('clean committed monitoring source required')
    report=run_demo(args.project_root,git('rev-parse','HEAD'),viewer_branch=git('branch','--show-current') or 'UNKNOWN')
    print(canonical(dict(mode=report['mode'],cases=len(report['cases']),primary_db_unchanged=report['primary_db_unchanged'],
                        artifacts=['runtime/v3/m7-dashboard/m7-report.json','runtime/v3/m7-dashboard/m7-report.md'])))


if __name__=='__main__':main()
