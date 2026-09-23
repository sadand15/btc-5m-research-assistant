"""Rebuild the original V1 study from stored finalized minutes; verify its hash."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hashlib
import json
import joblib
import numpy as np
import pandas as pd
from btc5.config import ROOT
from btc5.database import Database
from btc5.research import dataset,classification
from btc5.v2research import audit

r=json.loads((ROOT/'runtime/report.json').read_text())
start=r['split']['train']['first_cycle'];end=r['split']['test']['last_cycle']+300000
db=Database(str(ROOT/'runtime/research.sqlite'))
bars=[c for c in db.read_minutes(start-90*60000) if c.timestamp<end];db.close()
f=dataset(bars);f=f[(f.cycle_id>=start)&(f.cycle_id<end)].reset_index(drop=True)
digest=hashlib.sha256(pd.util.hash_pandas_object(f,index=False).values.tobytes()).hexdigest()
parts={name:f[(f.cycle_id>=s['first_cycle'])&(f.cycle_id<=s['last_cycle'])] for name,s in r['split'].items()}
ranges=audit(parts);artifact=joblib.load(ROOT/'runtime/model.joblib');te=parts['test']
p=artifact['model'].predict_proba(te[artifact['columns']])[:,1]
out={'original_model':artifact['version'],'hash_matches':digest==r['data_sha256'],
    'reconstructed_sha256':digest,'original_sha256':r['data_sha256'],'split':ranges,
    'metrics':classification(te.label,p),'naive':classification(te.label,(te.distance_percentage.to_numpy()>0).astype(float)),
    'cycle_overlap':False,'note':'Actual reconstructed finalized-minute frame; no model refitting.'}
(ROOT/'runtime/v2/original_v1_audit.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
print(json.dumps({k:out[k] for k in ('original_model','hash_matches','reconstructed_sha256','cycle_overlap')},indent=2))
print('original accuracy',out['metrics']['accuracy'],'naive',out['naive']['accuracy'])
