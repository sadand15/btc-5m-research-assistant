"""V2 research CLI. Reuses verified V1 archives and samples; no test tuning."""
import argparse
from datetime import datetime, timezone, timedelta
import json
import subprocess
import sys
import pandas as pd
from btc5.config import ROOT,load_config
from btc5.archives import ArchiveDownloader
from btc5.micro import micro_frame,MICRO_COLUMNS
from btc5.v2research import run_experiment


def enriched(cfg):
    source=ROOT/'runtime/seconds/samples.parquet'
    f=pd.read_parquet(source)
    cache=ROOT/'runtime/v2/seconds/enriched.parquet'
    cache.parent.mkdir(parents=True,exist_ok=True)
    a=datetime.fromtimestamp(f.timestamp.min()/1000,timezone.utc).date()
    b=datetime.fromtimestamp(f.timestamp.max()/1000,timezone.utc).date()
    downloader=ArchiveDownloader(ROOT/'runtime/archives')
    prior=downloader.day(a-timedelta(days=1),'1s').tail(61)
    pieces=[]
    for day in pd.date_range(a,b):
        data=downloader.day(day.date(),'1s')
        m=micro_frame(pd.concat([prior,data],ignore_index=True))
        start=int(day.tz_localize('UTC').timestamp()*1000)
        pieces.append(m[m.timestamp>=start]);prior=data.tail(61)
    features=pd.concat(pieces,ignore_index=True)
    f=f.merge(features,on='timestamp',how='left',validate='one_to_one')
    if f[MICRO_COLUMNS].isna().any().any():
        raise ValueError('Micro features missing; do not silently drop samples')
    f.to_parquet(cache,index=False)
    return f


def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['research','paper'],default='research',nargs='?')
    p.add_argument('--dataset',choices=['seconds','regimes','all'],default='all')
    p.add_argument('--quotes',help='CSV or JSON recorded quotes for paper replay')
    args=p.parse_args();cfg=load_config()
    if args.mode=='research':
        from btc5.forward import verify
        import time
        frozen=verify(cfg)
        if frozen and time.time()*1000<frozen['end']:raise ValueError('Forward study active: model retraining is frozen')
    if args.mode=='paper':
        from btc5.paper_v2 import run_scenarios
        run_scenarios(cfg,args.quotes);return
    for mode in (['seconds','regimes'] if args.dataset=='all' else [args.dataset]):
        if not (ROOT/'runtime'/mode/'samples.parquet').exists():
            subprocess.run([sys.executable,str(ROOT/'research.py'),mode],cwd=ROOT,check=True)
        f=enriched(cfg) if mode=='seconds' else pd.read_parquet(ROOT/'runtime/regimes/samples.parquet')
        report=run_experiment(f,cfg,ROOT/'runtime/v2'/mode,micro=mode=='seconds')
        print(json.dumps({'mode':mode,'selected':report['selected_model'],
            'metrics':{k:v['metrics']['accuracy'] for k,v in report['models'].items()}},indent=2),flush=True)


if __name__=='__main__':main()
