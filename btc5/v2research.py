"""Four disjoint temporal partitions; calibration chosen on validation, never test."""
import hashlib
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator
from btc5.research import classification, estimator, META
from btc5.features import FEATURE_SCHEMA
from btc5.micro import MICRO_COLUMNS
from btc5.validation import diagnostics

KINDS = ('naive','distance_time','logistic','lightgbm')


def audit(parts):
    seen=set(); last=None; result={}
    for name,p in parts.items():
        if p.empty or p.timestamp.duplicated().any():
            raise ValueError('Empty partition or duplicate timestamp')
        ids=set(p.cycle_id)
        if seen & ids or (last is not None and p.cycle_id.min()<=last):
            raise ValueError('Cycle leakage or nonchronological split')
        if ((p.timestamp<p.cycle_id)|(p.timestamp>=p.cycle_id+300000)|(p.cycle_id%300000!=0)).any():
            raise ValueError('Cycle alignment failure')
        seen |= ids; last=p.cycle_id.max()
        result[name]={'samples':len(p),'cycles':len(ids),'first_cycle':int(p.cycle_id.min()),'last_cycle':int(last)}
    return result


def split(frame, fractions=(.5,.15,.15,.2)):
    ids=np.sort(frame.cycle_id.unique())
    chunks=np.split(ids,[int(len(ids)*x) for x in np.cumsum(fractions)[:-1]])
    parts={name:frame[frame.cycle_id.isin(chunk)].reset_index(drop=True)
           for name,chunk in zip(('train','calibration','validation','test'),chunks)}
    audit(parts)
    return parts


def stats(f,p,total=None):
    n=len(f)
    if not n:
        return {'samples':0,'cycles':0,'coverage':0,'accuracy':None,'brier_score':None}
    confidence=np.maximum(p,1-p)
    return {**classification(f.label,p),'cycles':int(f.cycle_id.nunique()),
            'coverage':n/(total or n),'mean_confidence':float(confidence.mean()),
            'actual_up_frequency':float(f.label.mean())}


def buckets(f,p,values,edges):
    out=[]
    for i,(lo,hi) in enumerate(zip(edges[:-1],edges[1:])):
        mask=(values>=lo)&((values<=hi) if i==len(edges)-2 else (values<hi))
        out.append({'range':f'{lo:g}–{hi:g}',**stats(f.loc[mask],p[mask],len(f))})
    return out


def analyze(f,p):
    confidence=np.maximum(p,1-p)
    z=abs(f.distance_standardized.to_numpy())
    times=f.remaining_seconds.to_numpy()
    thresholds=[]
    for t in (.6,.65,.7,.75,.8,.85,.9):
        mask=confidence>=t
        first=f.loc[mask].assign(prob=p[mask]).sort_values('timestamp').drop_duplicates('cycle_id')
        thresholds.append({'threshold':t,**stats(f.loc[mask],p[mask],len(f)),
            'trades':len(first),'event_accuracy':float(((first.prob>=.5)==first.label).mean()) if len(first) else None,
            'cycle_coverage':len(first)/f.cycle_id.nunique(),
            'trade_definition':'first threshold crossing per cycle; hypothetical candidates, no quote fill'})
    heat=[]
    for lo,hi in zip([0,30,60,120,180,240],[30,60,120,180,240,300]):
        mask=(times>=lo)&(times<hi)
        for row in buckets(f.loc[mask],p[mask],z[mask],[0,.25,.5,1,1.5,np.inf]):
            heat.append({'remaining':f'{lo}–{hi}','distance':row.pop('range'),**row})
    return {'metrics':stats(f,p),
        'remaining':buckets(f,p,times,[0,30,60,120,180,240,300]),
        'distance':buckets(f,p,z,[0,.25,.5,1,1.5,np.inf]),
        'distance_pct':buckets(f,p,abs(f.distance_percentage.to_numpy()),[0,.0001,.0005,.001,.002,np.inf]),
        'confidence':buckets(f,p,confidence,[.5,.55,.6,.65,.7,.75,.8,.85,.9,1]),
        'thresholds':thresholds,'distance_time':heat}


def fit_suite(parts,cfg,micro=True):
    tr,ca,va,te=[parts[k] for k in ('train','calibration','validation','test')]
    allcols=sorted(set(tr.columns)-META-{'cycle_open','cycle_start','cycle_end','distance'})
    basecols=[c for c in allcols if c not in MICRO_COLUMNS]
    outputs={'naive':(te.distance_percentage.to_numpy()>0).astype(float)}
    reports={}; bundle={}
    kinds=['distance_time','logistic','lightgbm']+(['logistic_micro','lightgbm_micro'] if micro else [])
    for name in kinds:
        kind=name.replace('_micro','')
        cols=['distance_standardized','distance_remaining_z','remaining_seconds'] if name=='distance_time' else (allcols if name.endswith('_micro') else basecols)
        base=estimator(kind,cfg).fit(tr[cols],tr.label)
        models={'uncalibrated':base}
        for method,sk in [('platt','sigmoid'),('isotonic','isotonic')]:
            models[method]=CalibratedClassifierCV(FrozenEstimator(base),method=sk).fit(ca[cols],ca.label)
        selection={method:classification(va.label,m.predict_proba(va[cols])[:,1]) for method,m in models.items()}
        selected=min(selection,key=lambda k:selection[k]['brier_score'])
        test_probs={method:m.predict_proba(te[cols])[:,1] for method,m in models.items()}
        outputs[name]=test_probs[selected]
        reports[name]={'chosen_calibration':selected,'selection_data':'validation only',
                      'validation':selection,'test':{k:classification(te.label,p) for k,p in test_probs.items()}}
        bundle[name]={'model':models[selected],'columns':cols,'calibration':selected}
        print('fit',name,'calibration',selected,flush=True)
    return outputs,reports,bundle


def run_experiment(frame,cfg,directory,micro=True):
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
    parts=split(frame); te=parts['test']; partitions=audit(parts)
    probs,cal,bundle=fit_suite(parts,cfg,micro)
    report={'schema':'v2-review-1','dataset':{'samples':len(frame),'cycles':int(frame.cycle_id.nunique()),
        'first_timestamp':int(frame.timestamp.min()),'last_timestamp':int(frame.timestamp.max())},
        'split':partitions,'leakage_audit':'PASS: disjoint complete cycle IDs; chronological train/calibration/validation/test',
        'naive_probability_note':'Hard sign has probabilities 0/1 only for scoring; not calibrated confidence.',
        'models':{name:analyze(te,p) for name,p in probs.items()},'calibration':cal,'folds':[]}
    naive=report['models']['naive']['metrics']
    for name in report['models']:
        met=report['models'][name]['metrics']
        met['accuracy_delta_vs_naive_pp']=100*(met['accuracy']-naive['accuracy'])
        met['brier_delta_vs_naive']=met['brier_score']-naive['brier_score']
    report['regimes']=diagnostics(frame,partitions['calibration']['first_cycle'],te,probs,cfg['model']['seed'])
    pred=te.copy()
    for name,p in probs.items(): pred['p_'+name]=p
    pred.to_parquet(directory/'heldout.parquet',index=False)
    fold_predictions=[]
    ids=np.sort(frame.cycle_id.unique())
    for fold,start in enumerate((.5,.6,.7)):
        i,j=int(len(ids)*start),int(len(ids)*(start+.1))
        prefix=frame[frame.cycle_id<ids[i]]
        train_ids=np.sort(prefix.cycle_id.unique()); a,b=int(len(train_ids)*.65),int(len(train_ids)*.825)
        fp={'train':prefix[prefix.cycle_id<train_ids[a]],
            'calibration':prefix[(prefix.cycle_id>=train_ids[a])&(prefix.cycle_id<train_ids[b])],
            'validation':prefix[prefix.cycle_id>=train_ids[b]],
            'test':frame[(frame.cycle_id>=ids[i])&(frame.cycle_id<ids[j])].reset_index(drop=True)}
        ranges=audit(fp); ps,cs,_=fit_suite(fp,cfg,micro)
        metrics={name:stats(fp['test'],p) for name,p in ps.items()}
        for name,p in ps.items():
            mask=np.maximum(p,1-p)>=.8
            metrics[name]['high_confidence']=stats(fp['test'].loc[mask],p[mask],len(p))
        report['folds'].append({'fold':fold,'split':ranges,'models':metrics,'calibration':{k:v['chosen_calibration'] for k,v in cs.items()}})
        f=fp['test'][['timestamp','cycle_id','label']].copy();f['fold']=fold
        for name,p in ps.items():f['p_'+name]=p
        fold_predictions.append(f)
    combined=pd.concat(fold_predictions)
    if combined.timestamp.duplicated().any(): raise ValueError('Overlapping fold tests')
    combined.to_parquet(directory/'walkforward.parquet',index=False)
    report['fold_summary']={}
    for name in probs:
        report['fold_summary'][name]={}
        for metric in ('accuracy','brier_score','log_loss'):
            v=np.array([f['models'][name][metric] for f in report['folds']])
            report['fold_summary'][name][metric]={'mean':float(v.mean()),'median':float(np.median(v)),
                'std':float(v.std()),'worst':float(v.min() if metric=='accuracy' else v.max()),
                'best':float(v.max() if metric=='accuracy' else v.min())}
    # Prespecified choice: base model only, smallest validation Brier. No test-driven promotion.
    chosen=min(KINDS[1:],key=lambda n:cal[n]['validation'][cal[n]['chosen_calibration']]['brier_score'])
    fingerprint=hashlib.sha256(pd.util.hash_pandas_object(frame,index=False).values.tobytes()).hexdigest()
    version='v2-'+hashlib.sha256((fingerprint+json.dumps(cfg['model'],sort_keys=True)+'four-way-v1').encode()).hexdigest()[:12]
    artifact={**bundle[chosen],'bundle':bundle,'version':version,'schema':FEATURE_SCHEMA,'symbol':cfg['symbol'],
        'fit_end':int(parts['validation'].cycle_id.max())+300000,'sample_seconds':5 if micro else 60,
        'elapsed_support':sorted(frame.elapsed_seconds.round(3).unique().tolist()),'config':cfg,
        'fingerprint':fingerprint,'data_source':'V2 archived causal observations','selected_name':chosen}
    joblib.dump(artifact,directory/'model.joblib');frame.to_parquet(directory/'samples.parquet',index=False)
    report.update(model_version=version,selected_model=chosen,selection_rule='base model validation Brier only; micro ablation not promoted',data_sha256=fingerprint)
    (directory/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    return report
