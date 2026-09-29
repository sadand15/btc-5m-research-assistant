"""Full fixed grids, including failure denominators; no winner selection."""
from collections import defaultdict
from decimal import Decimal,localcontext
from btc5_v3.encoding import digest,canonical
from btc5_v3.edge.numeric import CONTEXT
from btc5_v3.analytics.statistics import mean,median
from btc5_v3.path.models import IntracyclePathConfig
from btc5_v3.path.engine import bucket
from btc5_v3.execution.models import LATENCY_GRID,SIZE_GRID,REBOUND_GRID,TTE_GRID

D=Decimal


def metrics(r):
    entry=[x for x in r['fills'] if x['purpose']=='ENTRY'];exits=r['exit_attempts'];a=r['accounting']
    requested=sum((D(x['requested_shares']) for x in r['orders'] if x['purpose']=='ENTRY'),D(0))
    filled=sum((D(x['filled_shares_gross']) for x in entry),D(0))
    return dict(order_intents=sum(x['purpose']=='ENTRY' for x in r['orders']),full_fills=int(r['entry_status']=='FULL_FILL'),
        partial_fills=int(r['entry_status']=='PARTIAL_FILL'),no_fills=int(r['entry_status']=='NO_FILL'),
        pending_entries=int(r['entry_status']=='PENDING_CAUSAL_BOOK'),m3_rejected=int(r['entry_status']=='M3_REJECTED'),
        size_not_authorized=int(r['entry_status']=='SIZE_NOT_AUTHORIZED_BY_M3'),
        order_fill_rate=D(bool(entry)) if requested else None,share_fill_fraction=filled/requested if requested else None,
        requested_shares=requested,filled_shares=filled,entry_vwap=D(entry[0]['vwap']) if entry else None,
        exit_vwap=(sum((D(x['notional']) for x in r['fills'] if x['purpose']=='EXIT'),D(0))/sum((D(x['filled_shares_gross']) for x in r['fills'] if x['purpose']=='EXIT'),D(0))) if any(x['purpose']=='EXIT' for x in r['fills']) else None,
        spread_paid=sum((D(x['spread_impact_per_traded_share'])*D(x['filled_shares_gross']) for x in r['fills']),D(0)),
        depth_impact=sum((D(x['depth_impact_per_traded_share'])*D(x['filled_shares_gross']) for x in r['fills']),D(0)),
        fee_impact_collateral=D(a['total_fees']['collateral']),
        triggered=sum(x['kind']=='EXIT_TRIGGER' for x in r['order_events']),
        stale_trigger_observations=sum(x['kind']=='TRIGGER_QUOTE_REJECTED' for x in r['order_events']),
        attempted=len(exits),fresh_execution_books=sum(x['snapshot_id'] is not None for x in exits),
        rebound_survived_latency=sum(x['rebound_survived_latency'] is True for x in exits),
        sufficient_depth=sum(x['sufficient_depth'] for x in exits),full_exits=sum(x['status']=='FULL_EXIT' for x in exits),
        partial_exits=sum(x['status']=='PARTIAL_EXIT' for x in exits),failed_exits=sum(x['status']=='NO_EXIT_FILL' for x in exits),
        pending_exits=sum(x['status']=='PENDING_EXIT_BOOK' for x in exits),
        simulated_early_exit_pnl=D(a['net_simulated_pnl']) if a['net_simulated_pnl'] is not None else None,
        hypothetical_hold_pnl=D(a['hold_to_settlement_pnl']) if a['hold_to_settlement_pnl'] is not None else None,
        difference=D(a['exit_advantage']) if a['exit_advantage'] is not None else None)


def study_report(rows,*,experiment_id,code_git):
    with localcontext(CONTEXT):return _study(rows,experiment_id,code_git)


def _study(rows,experiment_id,code_git):
    cfg=IntracyclePathConfig();output=[];benchmarks={}
    for row in rows:
        if row['dimension']=='LATENCY' and row['value']=='0':benchmarks[row['case']]=metrics(row['result'])
    groups=defaultdict(list)
    for row in rows:
        r=row['result'];m=metrics(r);s=row['original']['snapshot'];d=row['original']['decision'];side=r['side'] or 'UNSPECIFIED'
        price=(D(s[side.lower()+'_bids'][0]['price'])+D(s[side.lower()+'_asks'][0]['price']))/2 if side!='UNSPECIFIED' else None
        pi=bucket(price,cfg.price_buckets) if price is not None else None;ti=bucket(s['expiry']-d['evaluated_at'],cfg.tte_buckets_ms)
        zero=benchmarks.get(row['case']);impact=None;status='UNCOMPARABLE_QUANTITY_OR_NO_FILL'
        if zero and m['entry_vwap'] is not None and zero['entry_vwap'] is not None and m['filled_shares']==zero['filled_shares']:
            impact=m['entry_vwap']-zero['entry_vwap'];status='PAIRED_RECORDED_BOOK_COUNTERFACTUAL'
        item=dict(case=row['case'],dimension=row['dimension'],value=row['value'],execution_id=row['execution_id'],
            side=side,initial_price_bucket=pi,tte_bucket=ti,policy=r['policy'],metrics=m,latency_impact=impact,
            latency_impact_status=status,zero_latency_counterfactual=bool(row['dimension']=='LATENCY' and row['value']=='0'),
            observed_rebound_grid=r['observed_rebound_grid'],trace=r)
        output.append(item)
        groups[(row['dimension'],row['value'],pi,ti,side)].append(item)
    grouped=[]
    for key,values in sorted(groups.items(),key=lambda item:canonical(item[0])):
        ms=[x['metrics'] for x in values];differences=[x['difference'] for x in ms if x['difference'] is not None]
        counts={k:sum(x[k] for x in ms) for k in ('order_intents','full_fills','partial_fills','no_fills','pending_entries','m3_rejected','size_not_authorized',
            'triggered','stale_trigger_observations','attempted','fresh_execution_books','rebound_survived_latency',
            'sufficient_depth','full_exits','partial_exits','failed_exits','pending_exits')}
        grouped.append(dict(dimension=key[0],value=key[1],initial_price_bucket=key[2],tte_bucket=key[3],side=key[4],
            research_runs=len(values),unique_markets=len({x['case'] for x in values}),funnel=counts,
            resolved_comparison_count=len(differences),mean_exit_advantage=mean(differences),median_exit_advantage=median(differences),
            status='SYNTHETIC_DESCRIPTIVE_ONLY'))
    # Post-hoc bid observations are diagnostic only, never input to policy triggering.
    h1=[]
    for x in output:
        if x['dimension']!='EXIT_POLICY' or x['policy']['kind']!='BID_REBOUND':continue
        target=D(x['policy']['rebound']);observed=next((v for v in x['observed_rebound_grid'] if D(v['threshold'])==target),None)
        h1.append(dict(case=x['case'],initial_price_bucket=x['initial_price_bucket'],tte_bucket=x['tte_bucket'],side=x['side'],
            rebound_threshold=target,observed_path_rebound=observed,**{k:x['metrics'][k] for k in (
                'triggered','stale_trigger_observations','attempted','fresh_execution_books','rebound_survived_latency',
                'sufficient_depth','full_exits','partial_exits','failed_exits','pending_exits',
                'simulated_early_exit_pnl','hypothetical_hold_pnl','difference')}))
    return dict(mode='SYNTHETIC_EXECUTION_RESEARCH_ONLY',experiment_id=experiment_id,code_git=code_git,
        cases=len({r['case'] for r in rows}),grids=dict(latency_ms=LATENCY_GRID,shares=SIZE_GRID,rebound=REBOUND_GRID,fixed_tte_ms=TTE_GRID,
            price_bucket_edges=cfg.price_buckets,tte_bucket_edges_ms=cfg.tte_buckets_ms),
        funnel_units='OBSERVED_REBOUND_IS_PER_POSITION_PATH; TRIGGER/ATTEMPT/FILL_COUNTS_ARE_ATTEMPTS; REPEATED_EXITS_NOT_INDEPENDENT',
        grid_design='ONE_FACTOR_AT_A_TIME; BASE 250MS, M3_APPROVED_SIZE; LATENCY/SIZE USE BID_REBOUND_.20; EXIT GRID INCLUDES HOLD',
        rows=output,grouped_results=grouped,intracycle_reversal_execution_study=h1,
        limitations=['NO_REAL_MARKET_PROFITABILITY_CLAIM','NO_POLICY_RANKING_OR_OPTIMIZATION','NO_INDEPENDENT_SAMPLE_CLAIM',
            'NO_QUEUE_FILL_GUARANTEE','NO_M6_RISK_ENGINE','FULL_FAILURE_AND_UNRESOLVED_DENOMINATORS_RETAINED',
            'COUNTERFACTUAL_ROWS_NOT_ADDITIVE_PORTFOLIO_PNL'],report_hash=digest([x['execution_id'] for x in output]))


def markdown(report):
    lines=['# M5 Execution Simulation — synthetic research','',f"Code `{report['code_git']}`; experiment `{report['experiment_id']}`.",
        '',report['grid_design'],'','All preregistered alternatives are shown. No policy ranking or recommendation.','',
        '| Case | Grid | Value | Entry | Shares fraction | Entry VWAP | Exit full/partial/failed | Simulated PnL | Hold | Difference |',
        '|---|---|---|---|---:|---:|---|---:|---:|---:|']
    def show(x):return 'null' if x is None else str(round(D(x),6))
    for x in report['rows']:
        m=x['metrics']
        lines.append(f"| {x['case']} | {x['dimension']} | {x['value']} | {x['trace']['entry_status']} | {show(m['share_fill_fraction'])} | {show(m['entry_vwap'])} | {m['full_exits']}/{m['partial_exits']}/{m['failed_exits']} | {show(m['simulated_early_exit_pnl'])} | {show(m['hypothetical_hold_pnl'])} | {show(m['difference'])} |")
    lines+=['','## Intracycle Reversal Execution Study','',
        'H1 is unconfirmed. Post-hoc observed bid rebound is separate from causal trigger, delayed fresh book, depth and actual simulated exit. Failure and partial outcomes are retained.',
        '| Case | Side | Price/TTE bins | Rebound | Observed | Triggered | Attempts | Fresh books | Survived latency | Full / partial / failed |',
        '|---|---|---|---:|---|---:|---:|---:|---:|---|']
    for x in report['intracycle_reversal_execution_study']:
        observed=x['observed_path_rebound']
        lines.append(f"| {x['case']} | {x['side']} | {x['initial_price_bucket']}/{x['tte_bucket']} | {x['rebound_threshold']} | {observed['observed_bid_rebound'] if observed else 'null'} | {x['triggered']} | {x['attempted']} | {x['fresh_execution_books']} | {x['rebound_survived_latency']} | {x['full_exits']}/{x['partial_exits']}/{x['failed_exits']} |")
    lines+=['','JSON preserves each intent, latency, selected book, fill legs, opening position, exit attempt, remaining shares, settlement and balanced ledger.',
        'Gross PnL uses actual quantity flows after share fees but before collateral fees. Share fees are separately counted, not deducted from collateral twice.',
        'Spread/depth/latency are diagnostics of prices already paid, not additional cash charges. Zero latency is an explicitly labeled counterfactual.','',
        '## Limitations','']+['- '+x for x in report['limitations']]
    return '\n'.join(lines)+'\n'
