"""A fixed prospective window. Never relabel proxy predictions as oracle-calibrated."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import time
from btc5.config import ROOT
from btc5.database import dumps

MANIFEST=ROOT/'runtime/forward/manifest.json'


def rule_profile(raw,category):
    text=raw.get('description','')
    details=raw.get('variantData') or {}
    source='https://data.chain.link/streams/btc-usdt-topofbook-datalink'
    valid=(source in text and 'greater than the price at the beginning' in text and
           'lower than the price at the beginning' in text and 'exactly equal' in text and
           'resolve 50-50' in text and 'close price of the 5m candlestick' in text and
           details.get('priceFeedProvider')=='CHAINLINK' and details.get('priceFeedSymbol')=='BTCUSDT')
    return {'verified':valid,'feed':'CHAINLINK','symbol':'BTCUSDT',
        'feed_id':details.get('priceFeedId'),'source':source,'tie_payout':.5 if valid else None,
        'description_sha256':hashlib.sha256(text.encode()).hexdigest(),
        'start':category.get('startsAt'),'end':category.get('endsAt'),
        'opening':details.get('startPrice'),'final':details.get('endPrice')}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def policy(cfg):
    return {k:cfg[k] for k in ('symbol','data','model','entry','paper_trading','predictfun','freshness','inference')}


def sources():
    return {str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'btc5').glob('*.py'))} | {'app.py':sha(ROOT/'app.py')}


def freeze(cfg,path=MANIFEST,now=None,days=7):
    path=Path(path)
    if path.exists():raise ValueError('A frozen study already exists; do not overwrite or shift its window')
    if days!=7:raise ValueError('This prespecified study lasts seven days')
    now=int(time.time()*1000) if now is None else now
    start=(now//300000+1)*300000
    path.parent.mkdir(parents=True,exist_ok=True)
    artifact=Path(cfg['storage']['model'])
    digest=sha(artifact)
    copy=path.parent/'frozen-model.joblib';shutil.copyfile(artifact,copy)
    import joblib
    version=joblib.load(artifact)['version']
    record={'run_id':'forward-'+str(start),'created_at':now,'start':start,'end':start+days*86400000,
        'database':cfg['storage']['database'],
        'model_sha256':digest,'model_version':version,'policy':policy(cfg),'source_sha256':sources(),
        'model_backup':str(copy),'planned_cycles':2016,
        'primary':'First eligible joint quote/prediction per cycle with remaining seconds in [115,120].',
        'max_prediction_age_ms':10000,'max_quote_age_ms':5000,
        'target':'Official predict.fun payout, not Binance close. 50/50 excluded from binary accuracy and reported separately.',
        'comparisons':['frozen Binance-model proxy','Binance naive sign proxy','UP book midpoint'],
        'rules':'No retraining, threshold changes or basis-risk override; missing cycles are reported, not backfilled.',
        'end_behavior':'Keep raw recording; evaluation admits only the fixed study window. No automatic real orders.'}
    from btc5.database import Database
    db=Database(cfg['storage']['database'])
    row=db.conn.execute('SELECT raw_market,raw_category FROM venue_markets ORDER BY received_at DESC LIMIT 1').fetchone()
    db.close()
    if not row:raise ValueError('No official rule evidence recorded')
    profile=rule_profile(json.loads(row[0]),json.loads(row[1]))
    if not profile['verified']:raise ValueError('Unverified market rules')
    record['rule_profile']=profile
    path.write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
    return record


def verify(cfg,path=MANIFEST,now=None):
    path=Path(path)
    if not path.exists():return None
    m=json.loads(path.read_text())
    if cfg['storage']['database']!=m['database']:return None
    now=int(time.time()*1000) if now is None else now
    if now<m['end']:
        if sha(cfg['storage']['model'])!=m['model_sha256']:raise ValueError('FROZEN_MODEL_CHANGED')
        if policy(cfg)!=m['policy']:raise ValueError('FROZEN_POLICY_CHANGED')
        if sources()!=m['source_sha256']:raise ValueError('FROZEN_SOURCE_CHANGED')
    return m


def observe(db,cfg,book,manifest):
    if not manifest:return
    now=book['received_at'];cycle=book['market']['start']
    if not manifest['start']<=cycle<manifest['end'] or not cycle<=now<cycle+300000:return
    pred=db.conn.execute('SELECT * FROM predictions WHERE timestamp<=? AND available_at<=? AND cycle_id=? ORDER BY timestamp DESC LIMIT 1',(now,now,cycle)).fetchone()
    b=db.conn.execute('SELECT id FROM venue_books WHERE market_id=? AND received_at=?',(book['market_id'],now)).fetchone()
    if not b:return
    market_row=db.conn.execute('SELECT raw_market,raw_category FROM venue_markets WHERE market_id=?',(book['market_id'],)).fetchone()
    profile=rule_profile(json.loads(market_row[0]),json.loads(market_row[1])) if market_row else {'verified':False}
    rules_match=(profile['verified'] and profile.get('description_sha256')==manifest['rule_profile']['description_sha256'] and
        profile.get('feed_id')==manifest['rule_profile']['feed_id'])
    bids,asks=book['yes_bids'],book['yes_asks']
    midpoint=(bids[0][0]+asks[0][0])/2 if bids and asks else None
    if midpoint is not None and not book['market']['yes_is_up']:midpoint=1-midpoint
    reason='NO_PREDICTION';eligible=False;prob=naive=None;features={}
    if pred:
        features=json.loads(pred['features']);prob=pred['up_probability']
        naive=int(features['distance_absolute']>0) if 'distance_absolute' in features else None
        reason=pred['reason']
        eligible=(rules_match and pred['model_version']==manifest['model_version'] and
            0<=now-pred['timestamp']<=manifest['max_prediction_age_ms'] and
            0<=now-book['source_at']<=manifest['max_quote_age_ms'] and midpoint is not None and naive is not None and bool(pred['supported']))
    venue_reason='NO_PREDICTION'
    if pred:
        from btc5.venue import candidate
        from btc5.execution import prepare
        signal=candidate(dict(pred),now,cfg)
        venue_reason=prepare(signal,book,cfg['predictfun'])[1] if signal else reason
    if not rules_match:venue_reason='MARKET_RULES_CHANGED_OR_UNVERIFIED'
    payload={'model_probability':prob,'naive_direction':naive,'up_book_midpoint':midpoint,
        'remaining_seconds':(cycle+300000-now)/1000,'prediction_reason':reason,'venue_reason':venue_reason,
        'probability_scope':'BINANCE_PROXY_UNCALIBRATED_FOR_VENUE','feed':book['market']['feed'],
        'venue_open':book['market']['start_price'],'btc_price':pred['price'] if pred else None,
        'btc_open':pred['price']-features['distance_absolute'] if pred and 'distance_absolute' in features else None,
        'quote_source_at':book['source_at'],'prediction_at':pred['timestamp'] if pred else None,
        'prediction_available_at':pred['available_at'] if pred else None,
        'model_version':pred['model_version'] if pred else None,'fee_bps':book['fee_bps']}
    with db.conn:
        db.conn.execute('INSERT OR IGNORE INTO forward_observations(run_id,timestamp,cycle_id,market_id,book_id,prediction_id,eligible,payload) VALUES (?,?,?,?,?,?,?,?)',
            (manifest['run_id'],now,cycle,book['market_id'],b[0],pred['id'] if pred else None,int(eligible),dumps(payload)))
    db.state(forward_run=manifest['run_id'],forward_start=manifest['start'],forward_end=manifest['end'],forward_last_quote=now)


def report(db,manifest,now=None):
    now=int(time.time()*1000) if now is None else now
    rows=db.conn.execute('''SELECT f.*,o.yes_payout,m.binding FROM forward_observations f
        LEFT JOIN venue_outcomes o ON f.market_id=o.market_id
        JOIN venue_markets m ON f.market_id=m.market_id
        WHERE run_id=? AND eligible=1 AND json_extract(payload,'$.remaining_seconds') BETWEEN 115 AND 120
        ORDER BY f.timestamp,f.id''',(manifest['run_id'],)).fetchall()
    counts=db.conn.execute('SELECT COUNT(*),COUNT(DISTINCT cycle_id) FROM forward_observations WHERE run_id=?',(manifest['run_id'],)).fetchone()
    reasons={r[0]:r[1] for r in db.conn.execute("SELECT json_extract(payload,'$.venue_reason'),COUNT(*) FROM forward_observations WHERE run_id=? GROUP BY 1",(manifest['run_id'],))}
    selected={}
    for row in rows:
        p=json.loads(row['payload'])
        if row['eligible'] and 115<=p['remaining_seconds']<=120 and row['cycle_id'] not in selected:
            selected[row['cycle_id']]={**dict(row),'payload':p}
    metrics={};binary=[];splits=0;pending=0
    for row in selected.values():
        payout=row['yes_payout']
        if payout is None:pending+=1;continue
        if payout not in (0,1):splits+=1;continue
        y=payout if json.loads(row['binding'])['yes_is_up'] else 1-payout
        binary.append((y,row['payload']))
    for name,key in [('model','model_probability'),('naive','naive_direction'),('market_midpoint','up_book_midpoint')]:
        metrics[name]={'cycles':len(binary),'accuracy':sum((p[key]>=.5)==bool(y) for y,p in binary)/len(binary) if binary else None,
            'brier':sum((p[key]-y)**2 for y,p in binary)/len(binary) if binary else None}
    completed=max(0,(min(now,manifest['end'])-manifest['start'])//300000)
    complete_selected=sum(c+300000<=now for c in selected)
    return {'run_id':manifest['run_id'],'start_utc':datetime.fromtimestamp(manifest['start']/1000,timezone.utc).isoformat(),
        'end_utc':datetime.fromtimestamp(manifest['end']/1000,timezone.utc).isoformat(),
        'status':'SCHEDULED' if now<manifest['start'] else 'COLLECTING' if now<manifest['end'] else 'WINDOW_ENDED',
        'quotes_joined':counts[0],'observed_cycles':counts[1],
        'planned_cycles':manifest['planned_cycles'],'completed_clock_cycles':completed,
        'primary_cycles':len(selected),'primary_coverage_completed':complete_selected/completed if completed else None,
        'missing_primary_completed_cycles':max(0,completed-complete_selected),
        'binary_settled_cycles':len(binary),'split_settlements':splits,'pending_settlements':pending,
        'paired_metrics':metrics,'waiting_reasons':reasons,
        'net_pnl':None,'pnl_note':'Cross-source guard retained. No fabricated fills or proxy-settled profits.',
        'interpretation':'Seven days is a pipeline check; proxy probabilities are not yet venue-calibrated.'}
