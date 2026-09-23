"""python forward.py start | report -- fixed seven-day prospective study."""
import argparse
import json
from btc5.config import load_config,ROOT
from btc5.database import Database
from btc5.forward import MANIFEST,freeze,verify,report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['start','report'])
    args=p.parse_args();cfg=load_config()
    if args.command=='start':
        m=freeze(cfg);print(json.dumps({k:m[k] for k in ('run_id','start','end','model_version','planned_cycles')},indent=2))
    else:
        m=verify(cfg)
        if not m:raise SystemExit('No frozen study: run forward.py start')
        db=Database(cfg['storage']['database'])
        result=report(db,m);db.close()
        (ROOT/'runtime/forward/status.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result,indent=2))
