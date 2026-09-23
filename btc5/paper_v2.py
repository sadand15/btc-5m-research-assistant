"""Offline quote execution scenarios. Synthetic quotes never imply real profit."""
from bisect import bisect_right
from copy import deepcopy
import hashlib
import json
import numpy as np
import pandas as pd
from btc5.config import ROOT
from btc5.market import MockQuoteProvider,ReplayQuoteProvider
from btc5.execution import prepare,execute,settle_fill
from btc5.strategy import decide
from btc5.database import Database,dumps


def simulate(frame,provider,cfg,policy,db=None,scenario='default',outcomes=None):
    rows=frame.sort_values('timestamp').to_dict('records');times=[r['timestamp'] for r in rows]
    events=set(times)|{t+policy['latency_ms'] for t in times}
    if isinstance(provider,ReplayQuoteProvider):events.update(t for t in provider.times if times[0]<=t<=times[-1]+300000)
    orders={};rejected={};filled=[]
    for now in sorted(events):
        i=bisect_right(times,now)-1
        if i<0:continue
        r=rows[i];cycle=int(r['cycle_id'])
        if now//300000*300000!=cycle:continue
        context={**r,'cycle_open':r['price']/(1+r['distance_percentage'])}
        book=provider.quote(now,context)
        if book is None:continue
        existing=orders.get(cycle)
        if existing:
            if existing.get('status')=='QUEUED':
                fill,status=execute(existing['order'],book,existing['order']['policy'])
                if fill is not None:
                    existing.update(fill=fill,status=status)
                    if fill['spent_usdt']>0:
                        # Archived BTC labels settle MOCK ONLY. Real quotes need venue payouts.
                        payout=(int(r['label']) if r['outcome']!='TIE' else .5) if provider.mode=='SIMULATED QUOTE' else (outcomes or {}).get(book['market_id'])
                        settlement=settle_fill(fill,existing['order']['direction'],payout) if payout is not None else None
                        existing['settlement']=settlement;filled.append(existing)
                    if db:
                        with db.conn:
                            db.conn.execute('UPDATE paper_positions_v2 SET fill=?,settlement=? WHERE scenario=? AND cycle_id=?',
                                (dumps(fill),dumps(existing.get('settlement')),scenario,cycle))
                        db.audit(now,cycle,'paper_fill',{'scenario':scenario,'quote':book,'fill':fill,'source':provider.mode})
            continue
        if now!=r['timestamp']:continue
        side,reason=decide(r['probability'],r,None,cfg,True,historical=True)
        if side=='WAIT':continue
        signal={'timestamp':now,'cycle_id':cycle,'cycle_open':context['cycle_open'],
            'direction':side,'probability':r['probability'] if side=='UP' else 1-r['probability'],
            'entry_remaining_seconds':r['remaining_seconds'],'features':{k:v for k,v in r.items() if k not in ('label','outcome')},
            'model_version':r.get('model_version','v2-heldout')}
        effective={**policy,'_volatility':r.get('rv_60s',r['volatility'])}
        order,reason=prepare(signal,book,effective)
        if not order:
            rejected[reason]=rejected.get(reason,0)+1;continue
        if db:
            with db.conn:
                cur=db.conn.execute('INSERT OR IGNORE INTO paper_positions_v2(scenario,cycle_id,signal) VALUES (?,?,?)',
                    (scenario,cycle,dumps(order)))
            if cur.rowcount==0:raise ValueError('Scenario already recorded; choose a new run ID')
            db.audit(now,cycle,'paper_signal',{'scenario':scenario,'features':signal['features'],'quote':book,'order':order,'source':provider.mode})
        orders[cycle]={'order':order,'status':'QUEUED','source':provider.mode}
        if policy['latency_ms']==0:
            fill,status=execute(order,book,effective)
            if fill is not None:
                orders[cycle].update(fill=fill,status=status)
                if fill['spent_usdt']>0:
                    payout=(int(r['label']) if r['outcome']!='TIE' else .5) if provider.mode=='SIMULATED QUOTE' else (outcomes or {}).get(book['market_id'])
                    orders[cycle]['settlement']=settle_fill(fill,side,payout) if payout is not None else None
                    filled.append(orders[cycle])
                if db:
                    with db.conn:db.conn.execute('UPDATE paper_positions_v2 SET fill=?,settlement=? WHERE scenario=? AND cycle_id=?',
                        (dumps(fill),dumps(orders[cycle].get('settlement')),scenario,cycle))
    settled=[o for o in filled if o.get('settlement')]
    pnl=[o['settlement']['net_pnl'] for o in settled];equity=np.r_[0,np.cumsum(pnl)]
    fees=sum(o['fill']['fee_usdt_equivalent'] for o in filled)
    def mean(key):return float(np.mean([o['fill'][key] for o in filled])) if filled else None
    return {'source':provider.mode,'label':'SIMULATED EXECUTION RESULT' if provider.mode=='SIMULATED QUOTE' else 'RECORDED QUOTE PAPER EXECUTION',
        'scenario':scenario,'latency_ms':policy['latency_ms'],'policy':policy,'total_trades':len(filled),'orders':len(orders),
        'settled':len(settled),'wins':sum(o['settlement']['result']=='WIN' for o in settled),
        'losses':sum(o['settlement']['result']=='LOSS' for o in settled),
        'win_rate':sum(o['settlement']['result']=='WIN' for o in settled)/len(settled) if settled else None,
        'coverage':len(filled)/frame.cycle_id.nunique(),'average_quote':mean('quoted_price'),'average_fill':mean('vwap'),
        'average_probability':float(np.mean([o['order']['probability'] for o in filled])) if filled else None,
        'effective_latency_ms':mean('effective_latency_ms'),'fees':fees,
        'spread_cost':sum(o['order']['spread']/2*o['fill']['gross_shares'] for o in filled),
        'slippage_cost':sum(o['fill']['slippage']*o['fill']['gross_shares'] for o in filled),
        'gross_pnl':sum(o['settlement']['gross_pnl'] for o in settled) if settled else None,
        'net_pnl':sum(pnl) if settled else None,'max_drawdown':float((np.maximum.accumulate(equity)-equity).max()) if settled else None,
        'rejections':rejected,'pending_settlement':len(filled)-len(settled),
        'assumptions':['Fee denomination/rounding assumed; no queue priority.',
            'Mock interpolates no BTC data; deterministic intra-snapshot quote oscillation is synthetic.',
            'Real quote import never settles against Binance labels without venue evidence.']}


def run_scenarios(cfg,quotes=None):
    directory=ROOT/'runtime/v2/seconds'
    report=json.loads((directory/'report.json').read_text())
    frame=pd.read_parquet(directory/'heldout.parquet')
    frame['probability']=frame['p_'+report['selected_model']]
    frame['model_version']=report['model_version']
    provider=ReplayQuoteProvider.from_file(quotes) if quotes else MockQuoteProvider(cfg.get('simulation',{}))
    outputs=[];db=Database(str(ROOT/'runtime/v2/paper.sqlite'))
    import time
    run=str(time.time_ns())
    cases=[(f'latency-{ms}',{'latency_ms':ms}) for ms in (0,100,250,500,1000)]
    cases += [('fee-zero',{'fee_discount_multiplier':0}),('fixed-slip-10bps',{'slippage_model':'fixed','fixed_slippage_bps':10}),
              ('volatility-slip',{'slippage_model':'volatility','fixed_slippage_bps':0,'volatility_slippage_multiplier':1})]
    for name,overrides in cases:
        policy={**cfg['predictfun'],**overrides}
        if provider.mode=='SIMULATED QUOTE':policy['allow_basis_risk']=True
        result=simulate(frame,provider,cfg,policy,db,run+'-'+name)
        outputs.append(result);print(name,'trades',result['total_trades'],'synthetic pnl' if not quotes else 'pnl',result['net_pnl'],flush=True)
    if not quotes:
        widened=MockQuoteProvider({**cfg.get('simulation',{}),'mock_spread':.04})
        result=simulate(frame,widened,cfg,{**cfg['predictfun'],'allow_basis_risk':True},db,run+'-spread-double')
        outputs.append(result)
    db.close()
    base=outputs[0]['net_pnl']
    for r in outputs:r['pnl_difference_vs_zero_latency']=r['net_pnl']-base if r['net_pnl'] is not None and base is not None else None
    path=ROOT/'runtime/v2'/('paper_replay.json' if quotes else 'paper_scenarios.json')
    path.write_text(json.dumps(outputs,indent=2,allow_nan=False),encoding='utf-8')
