"""Record public quotes, simulate delayed fills, settle only from venue evidence."""
import asyncio
from bisect import bisect_right
from dataclasses import asdict
import json
import logging
import time
from btc5.predictfun import PredictClient
from btc5.execution import prepare, execute, settle_fill
from btc5.strategy import decide
from btc5.database import dumps

LOG = logging.getLogger(__name__)


def candidate(pred: dict, now: int, cfg: dict) -> dict | None:
    if not cfg['paper_trading']['enabled']:
        return None
    if pred.get('decision') and not pred['decision'].startswith('CANDIDATE'):
        return None
    if not pred['cycle_id']<=now<pred['cycle_id']+300000:
        return None
    if not 0 <= now-pred['timestamp'] <= cfg['data']['stale_seconds']*1000:
        return None
    f = json.loads(pred['features']) if isinstance(pred['features'],str) else pred['features']
    f={**f,'remaining_seconds':(pred['cycle_id']+300000-now)/1000}
    ages=f.get('freshness_at')
    if ages:
        from btc5.inference import recheck
        if recheck(pred['cycle_id'],pred['timestamp'],now,ages,cfg):return None
    f={k:v for k,v in f.items() if k!='freshness_at'}
    side, _ = decide(pred['up_probability'],f,f.get('orderbook'),cfg,bool(pred['supported']))
    if side=='WAIT':
        return None
    opening = pred['price']-f['distance_absolute'] if 'distance_absolute' in f else None
    return {'timestamp':now,'feature_at':pred['timestamp'],'cycle_id':pred['cycle_id'],'cycle_open':opening,
            'direction':side, 'probability':pred['up_probability'] if side=='UP' else 1-pred['up_probability'],
            'model_version':pred['model_version'],'features':f}


class VenueService:
    def __init__(self,cfg,db):
        self.cfg,self.db = cfg,db
        self.policy = cfg['predictfun']
        self.client = PredictClient(self.policy)
        self.market = None
        self.last_settle = 0
        self.settlement_task=None
        from btc5.forward import verify
        self.forward_manifest=verify(cfg)

    async def run(self):
        if not self.policy.get('enabled'):
            return
        while True:
            try:
                if not self.client.key:
                    self.db.state(venue_status='PREDICT_API_KEY_MISSING',venue_decision='WAIT',quote_data_mode='DISABLED')
                    await asyncio.sleep(30)
                    continue
                now = int(time.time()*1000)
                if now-self.last_settle > 30000 and (self.settlement_task is None or self.settlement_task.done()):
                    self.settlement_task=asyncio.create_task(self.settle_safe())
                    self.last_settle = now
                if not self.market or now >= self.market.end:
                    self.market,raw,category = await asyncio.to_thread(self.client.discover,now)
                    with self.db.conn:
                        self.db.conn.execute('INSERT OR REPLACE INTO venue_markets VALUES (?,?,?,?,?)',
                            (self.market.id,now,dumps(asdict(self.market)),dumps(raw),dumps(category)))
                book,raw = await asyncio.to_thread(self.client.book,self.market)
                self.record(book,raw)
                from btc5.forward import observe
                observe(self.db,self.cfg,book,self.forward_manifest)
                self.process(book)
                self.db.state(venue_status='CONNECTED',quote_data_mode='LIVE DATA',venue_market=asdict(self.market),venue_quote={
                    'received_at':book['received_at'],'up_ask':book['up_asks'][0][0] if book['up_asks'] else None,
                    'down_ask':book['down_asks'][0][0] if book['down_asks'] else None,'fee_bps':book['fee_bps']})
                await asyncio.sleep(self.policy['poll_seconds'])
            except asyncio.CancelledError:
                if self.settlement_task:
                    self.settlement_task.cancel()
                    await asyncio.gather(self.settlement_task,return_exceptions=True)
                raise
            except Exception as exc:
                # Never include headers or API key in logs/state.
                reason = str(exc) if isinstance(exc,(ValueError,PermissionError)) else type(exc).__name__
                self.db.state(venue_status=reason,venue_decision='WAIT')
                LOG.warning('[PREDICT] %s',reason)
                await asyncio.sleep(15)

    async def settle_safe(self):
        try:await self.settle()
        except asyncio.CancelledError:raise
        except Exception as exc:
            self.db.state(venue_settlement_status=type(exc).__name__)
            LOG.warning('[PREDICT SETTLEMENT] %s',type(exc).__name__)

    def record(self,book,raw):
        with self.db.conn:
            self.db.conn.execute('INSERT OR IGNORE INTO venue_books (market_id,received_at,source_at,normalized,raw) VALUES (?,?,?,?,?)',
                (book['market_id'],book['received_at'],book['source_at'],dumps(book),dumps(raw)))

    def process(self,book):
        now = book['received_at']
        state={r[0]:json.loads(r[1]) for r in self.db.conn.execute('SELECT key,value FROM state')}
        if 'event_time' in state:
            fresh=(state.get('connection')=='CONNECTED' and 0<=now-state['event_time']<=self.cfg.get('freshness',{}).get('btc_price_max_age_ms',10000))
            if not fresh:
                self.db.state(venue_decision='STALE_BTC_NO_TRADE')
                self.db.audit(now,book['market']['start'],'venue_rejected',{'reason':'STALE_BTC','quote':book})
                return
        with self.db.conn:
            for row in self.db.conn.execute("SELECT * FROM venue_orders WHERE status='QUEUED'").fetchall():
                order = json.loads(row['signal'])
                if now >= order['cycle_id']+300000:
                    self.db.conn.execute("UPDATE venue_orders SET status='EXPIRED' WHERE id=?",(row['id'],))
                    continue
                fill,status = execute(order,book,order['policy'])
                if fill is not None:
                    self.db.conn.execute('UPDATE venue_orders SET status=?,fill=? WHERE id=?',(status,dumps(fill),row['id']))
                    self.db.state(venue_decision=status)
                    self.db.audit(now,order['cycle_id'],'venue_fill',{'quote':book,'order':order,'fill':fill,'status':status})
            row = self.db.conn.execute('SELECT * FROM predictions WHERE timestamp<=? AND COALESCE(available_at,timestamp)<=? ORDER BY timestamp DESC LIMIT 1',(now,now)).fetchone()
            signal = candidate(dict(row),now,self.cfg) if row else None
            if not signal:
                reason=row['reason'] if row else 'NO_PREDICTION'
                if row and now-row['timestamp']>self.cfg['data']['stale_seconds']*1000:reason='STALE_PREDICTION'
                self.db.state(venue_decision=reason)
                self.db.audit(now,book['market']['start'],'venue_wait',{'reason':reason,'prediction_id':row['id'] if row else None,'quote_at':now})
                return
            order,reason = prepare(signal,book,self.policy)
            self.db.state(venue_decision=reason)
            self.db.audit(now,signal['cycle_id'],'venue_decision',{'signal':signal,'quote':book,'order':order,'reason':reason})
            if order:
                self.db.conn.execute('INSERT OR IGNORE INTO venue_orders (cycle_id,market_id,status,signal) VALUES (?,?,?,?)',
                                    (order['cycle_id'],order['market_id'],'QUEUED',dumps(order)))

    async def settle(self):
        # Resolve every recorded market, even if live policy did not trade it.
        # This lets later offline policy comparisons use genuine venue labels.
        markets = self.db.conn.execute('''SELECT m.* FROM venue_markets m
            LEFT JOIN venue_outcomes o ON m.market_id=o.market_id WHERE o.market_id IS NULL
            ORDER BY COALESCE((SELECT MAX(received_at) FROM venue_resolution_checks r WHERE r.market_id=m.market_id),0)
            LIMIT 20''').fetchall()
        for market in markets:
            if int(time.time()*1000) < json.loads(market['binding'])['end']:
                continue
            payout,raw = await asyncio.to_thread(self.client.settlement,market['market_id'])
            checked_at=int(time.time()*1000)
            with self.db.conn:
                self.db.conn.execute('INSERT INTO venue_resolution_checks(market_id,received_at,payout,raw) VALUES (?,?,?,?)',
                    (market['market_id'],checked_at,payout,dumps(raw)))
            if payout is None:
                continue
            with self.db.conn:
                self.db.conn.execute('INSERT OR REPLACE INTO venue_outcomes VALUES (?,?,?,?)',
                    (market['market_id'],int(time.time()*1000),payout,dumps(raw)))
        rows = self.db.conn.execute('''SELECT v.*,o.yes_payout FROM venue_orders v JOIN venue_outcomes o
            ON v.market_id=o.market_id WHERE v.status IN ('FILLED','PARTIAL') AND v.settlement IS NULL''').fetchall()
        for row in rows:
            fill,order = json.loads(row['fill']),json.loads(row['signal'])
            result = settle_fill(fill,order['direction'],row['yes_payout'])
            with self.db.conn:
                self.db.conn.execute('UPDATE venue_orders SET settlement=? WHERE id=?',(dumps(result),row['id']))
            LOG.info('[PREDICT RESULT] %s',result)
        self.db.state(venue_settlement_status='CHECKED',venue_settlement_checked_at=int(time.time()*1000))


def replay(db,cfg) -> dict:
    """Only stored quotes available at each decision, then a NEW quote after latency."""
    predictions = [dict(r) for r in db.conn.execute('SELECT * FROM predictions ORDER BY timestamp')]
    times = [r['timestamp'] for r in predictions]
    orders, rejected, n = {},{},0
    for row in db.conn.execute('SELECT normalized FROM venue_books ORDER BY received_at,id'):
        book = json.loads(row[0]); n += 1
        now,cycle = book['received_at'],book['market']['start']
        existing = orders.get(cycle)
        if existing:
            if existing['status']=='QUEUED':
                if now >= cycle+300000:
                    existing['status']='EXPIRED'
                else:
                    fill,status = execute(existing['order'],book,existing['order']['policy'])
                    if fill is not None:
                        existing.update(status=status,fill=fill)
            continue
        i = bisect_right(times,now)-1
        signal = candidate(predictions[i],now,cfg) if i>=0 else None
        if signal:
            order,reason = prepare(signal,book,cfg['predictfun'])
            if order:
                orders[cycle]={'order':order,'status':'QUEUED'}
            else:
                rejected[reason] = rejected.get(reason,0)+1
    results = []
    for o in orders.values():
        if o['status']=='QUEUED' and n and now >= o['order']['cycle_id']+300000:
            o['status']='EXPIRED'
        if o.get('fill') and o['fill']['net_shares']>0:
            resolved = db.conn.execute('SELECT yes_payout FROM venue_outcomes WHERE market_id=?',(o['order']['market_id'],)).fetchone()
            if resolved:
                o['settlement'] = settle_fill(o['fill'],o['order']['direction'],resolved[0])
        results.append(o)
    settled = [o['settlement'] for o in results if o.get('settlement')]
    return {'venue':'predict.fun','quotes':n,'orders':len(results),'settled':len(settled),
            'pnl_usdt':sum(r['pnl_usdt'] for r in settled) if settled else None,
            'rejections':rejected,'results':results,
            'status':'NO_RECORDED_QUOTES' if not n else 'REPLAY_COMPLETE',
            'assumptions':{'fee_deduction':cfg['predictfun']['fee_deduction'],
                           'probabilities':'Binance proxy; venue target may differ',
                           'fills':'Displayed depth after latency; queue priority and hidden liquidity not modeled'}}
