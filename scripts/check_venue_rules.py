"""Archive official API rule evidence without touching credentials."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from btc5.config import load_config,ROOT
from btc5.database import Database
from btc5.forward import rule_profile

cfg=load_config();db=Database(cfg['storage']['database'])
rows=db.conn.execute('SELECT * FROM venue_markets ORDER BY received_at').fetchall()
evidence=[]
for row in rows:
    raw=json.loads(row['raw_market']);cat=json.loads(row['raw_category'])
    evidence.append({'market_id':row['market_id'],'received_at':row['received_at'],
        'market_source':f'https://api.predict.fun/v1/markets/{row["market_id"]}',
        'category_source':'https://api.predict.fun/v1/categories/'+raw['categorySlug'],
        'profile':rule_profile(raw,cat),'raw_market':raw,'raw_category':cat})
db.close();directory=ROOT/'runtime/forward';directory.mkdir(parents=True,exist_ok=True)
(directory/'rules-evidence.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
print(json.dumps({'markets_checked':len(evidence),'latest_profile':evidence[-1]['profile'] if evidence else None},indent=2))
