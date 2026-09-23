"""Extend saved archive experiments with chronological multi-model walk-forward diagnostics."""
import argparse
import json
from pathlib import Path
import pandas as pd
from btc5.config import ROOT
from btc5.research import fit_calibrated,META,classification
from btc5.validation import diagnostics


def evaluate(mode):
    directory=ROOT/'runtime'/mode
    report=json.loads((directory/'report.json').read_text(encoding='utf-8'))
    frame=pd.read_parquet(directory/'samples.parquet')
    cfg=report['config']
    output={'mode':mode,'data_sha256':report['data_sha256'],'folds':[]}
    predictions=[]
    for number,fold in enumerate(report['walk_forward']):
        tr=frame[frame.cycle_id<fold['calibration_first_cycle']]
        ca=frame[(frame.cycle_id>=fold['calibration_first_cycle']) & (frame.cycle_id<=fold['calibration_last_cycle'])]
        te=frame[(frame.cycle_id>=fold['test_first_cycle']) & (frame.cycle_id<=fold['test_last_cycle'])].reset_index(drop=True)
        assert tr.cycle_id.max()<ca.cycle_id.min() and ca.cycle_id.max()<te.cycle_id.min()
        probs={}
        for kind in ('distance_time','logistic','lightgbm'):
            cols=['distance_standardized','distance_remaining_z','remaining_seconds'] if kind=='distance_time' else sorted(set(frame.columns)-META)
            _,model=fit_calibrated(kind,tr,ca,cols,cfg)
            probs[kind]=model.predict_proba(te[cols])[:,1]
        item={k:fold[k] for k in ('train_last_cycle','calibration_first_cycle','calibration_last_cycle','test_first_cycle','test_last_cycle')}
        item['models']={name:classification(te.label,p) for name,p in probs.items()}
        item['diagnostics']=diagnostics(frame,fold['calibration_first_cycle'],te,probs,cfg['model']['seed'])
        output['folds'].append(item)
        predicted=te[['timestamp','cycle_id','label','remaining_seconds']].copy()
        predicted['fold']=number
        for name,p in probs.items():
            predicted[name]=p
        predictions.append(predicted)
        print(mode,'fold',number,{name:round(v['brier_score'],6) for name,v in item['models'].items()},flush=True)
    combined=pd.concat(predictions,ignore_index=True)
    assert not combined.timestamp.duplicated().any(), 'Walk-forward test windows overlap'
    combined.to_parquet(directory/'walkforward_predictions.parquet',index=False)
    output['pooled_walkforward']={name:classification(combined.label,combined[name]) for name in ('distance_time','logistic','lightgbm')}
    (directory/'validation.json').write_text(json.dumps(output,indent=2,allow_nan=False),encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['seconds','regimes','all'],default='all',nargs='?')
    args=p.parse_args()
    for mode in (['seconds','regimes'] if args.mode=='all' else [args.mode]):
        evaluate(mode)
