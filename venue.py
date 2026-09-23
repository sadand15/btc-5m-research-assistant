import argparse
import asyncio
import json
from pathlib import Path
from btc5.config import load_config
from btc5.database import Database
from btc5.venue import VenueService,replay

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('command',choices=['record','replay','probe'])
    p.add_argument('--config',default='config.yaml')
    args=p.parse_args()
    cfg=load_config(args.config)
    db=Database(cfg['storage']['database'])
    service=VenueService(cfg,db)
    try:
        if args.command=='record':
            asyncio.run(service.run())
        elif args.command=='probe':
            if not service.client.key:
                print('PREDICT_API_KEY_MISSING: set this market-data key locally, then restart app.py')
            else:
                import time
                market,_,_=service.client.discover(int(time.time()*1000))
                book,_=service.client.book(market)
                print(json.dumps(book,indent=2))
        else:
            result=replay(db,cfg)
            path=Path(cfg['storage']['database']).parent/'predictfun_replay.json'
            path.write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
            print(json.dumps({k:v for k,v in result.items() if k!='results'},indent=2))
    finally:
        db.close()
