"""Reproducible archive research: python research.py seconds --days 14 --step 5."""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from btc5.archives import ArchiveDownloader, seconds_dataset, minute_bars
from btc5.config import ROOT, load_config
from btc5.research import dataset, train, fit_calibrated, META
from btc5.validation import diagnostics


def main():
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['seconds','regimes'])
    p.add_argument('--days', type=int)
    p.add_argument('--step', type=int, default=5)
    p.add_argument('--end', help='Exclusive UTC end date YYYY-MM-DD (default today)')
    p.add_argument('--config', default=str(ROOT/'config.yaml'))
    p.add_argument('--publish',action='store_true',help='Write model/report to paths in config.yaml')
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    days = args.days or (14 if args.mode == 'seconds' else 90)
    if days < 3:
        raise ValueError('At least 3 days required for train/calibration/test')
    end = datetime.fromisoformat(args.end).date() if args.end else datetime.now(timezone.utc).date()
    start = end-timedelta(days=days)
    cfg = deepcopy(load_config(args.config))
    directory = Path(cfg['storage']['model']).parent if args.publish else ROOT/'runtime'/args.mode
    directory.mkdir(parents=True, exist_ok=True)
    if not args.publish:
        cfg['storage']['model'] = str(directory/'model.joblib')
        cfg['storage']['report'] = str(directory/'report.json')
    archives = ArchiveDownloader(ROOT/'runtime'/'archives')
    frames = []
    previous = None
    dates = [start+timedelta(days=i) for i in range(-1,days)]
    for day in dates:
        data = archives.day(day, '1s' if args.mode == 'seconds' else '1m')
        if args.mode == 'seconds':
            if previous is not None:
                sample = seconds_dataset(pd.concat([previous.tail(5400), data], ignore_index=True), args.step)
                frames.append(sample)
                sample.to_parquet(directory/f'samples-{day}-{args.step}s.parquet', index=False)
            previous = data
        else:
            frames.append(data)
    frame = pd.concat(frames, ignore_index=True) if args.mode == 'seconds' else dataset(minute_bars(pd.concat(frames,ignore_index=True)))
    start_ms = int(datetime.combine(start,datetime.min.time(),tzinfo=timezone.utc).timestamp()*1000)
    frame = frame[frame.cycle_id >= start_ms].reset_index(drop=True)
    frame.attrs.update(source='Binance checksum-verified '+('real 1s archive replay' if args.mode=='seconds' else '1m multi-regime archives'),
                       sample_seconds=args.step if args.mode=='seconds' else 60)
    frame.to_parquet(directory/'samples.parquet', index=False)
    report = train(frame,cfg)
    artifact = joblib.load(cfg['storage']['model'])
    split = report['split']
    tr = frame[frame.cycle_id < split['calibration']['first_cycle']]
    ca = frame[(frame.cycle_id >= split['calibration']['first_cycle']) & (frame.cycle_id < artifact['fit_end'])]
    te = frame[frame.cycle_id >= artifact['fit_end']].reset_index(drop=True)
    probabilities = {}
    for kind in ('distance_time','logistic','lightgbm'):
        cols = ['distance_standardized','distance_remaining_z','remaining_seconds'] if kind=='distance_time' else sorted(set(frame.columns)-META)
        _, model = fit_calibrated(kind,tr,ca,cols,cfg)
        probabilities[kind] = model.predict_proba(te[cols])[:,1]
    report['regime_validation'] = diagnostics(frame, split['calibration']['first_cycle'], te, probabilities, cfg['model']['seed'])
    report['archive_window'] = {'start_inclusive':str(start),'end_exclusive':str(end),'days':days}
    Path(cfg['storage']['report']).write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'mode':args.mode,'days':days,'samples':len(frame),'cycles':int(frame.cycle_id.nunique()),
                      'report':cfg['storage']['report'], 'model':cfg['storage']['model'],
                      'scores':{name:{k:v[k] for k in ['accuracy','brier_score']} for name,v in report['models'].items()}},indent=2))


if __name__=='__main__':
    main()
