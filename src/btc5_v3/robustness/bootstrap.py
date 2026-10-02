"""Seeded moving blocks of market clusters; never iid quote resampling."""
from decimal import Decimal as D,localcontext
from math import ceil
import random
from btc5_v3.edge.numeric import CONTEXT
from btc5_v3.analytics.statistics import mean,median


def bootstrap(rows,metric,*,seed=42,replicates=200,block_length=2,minimum_markets=8):
    if type(seed) is not int or type(replicates) is not int or not 20<=replicates<=2000:raise ValueError('explicit bounded sampling required')
    if type(block_length) is not int or block_length<1 or type(minimum_markets) is not int or minimum_markets<4:raise ValueError('invalid cluster budget')
    if metric not in ('mean_edge','fill_rate','reject_rate','brier','mean_return'):raise ValueError('unsupported inference metric')
    def value(r):
        if metric=='mean_edge':return D(r['edge']) if r['edge'] is not None else None
        if metric=='fill_rate':return D(bool(r['execution'] and r['execution']['positions'])) if r['permission']['action']!='REJECT' else None
        if metric=='reject_rate':return D(r['permission']['action']=='REJECT')
        if metric=='brier':return (D(r['p_yes'])-D(r['outcome']))**2 if r['outcome'] is not None else None
        if r['execution'] and r['execution']['positions'] and r['execution']['accounting']['completed']:
            cost=D(r['execution']['positions'][0]['collateral_spent'])
            return D(r['execution']['accounting']['net_simulated_pnl'])/cost if cost>0 else None
        return None
    with localcontext(CONTEXT):
        groups={}
        for r in sorted(rows,key=lambda r:(r['at'],r['market_id'],r['record_id'])):
            groups.setdefault(r['market_id'],[])
            v=value(r)
            if v is not None:groups[r['market_id']].append(v)
        clusters=list(groups.values());values=[v for c in clusters for v in c];effective=sum(bool(c) for c in clusters)
        base=dict(metric=metric,method='MOVING_BLOCK_MARKET_CLUSTER_PERCENTILE',seed=seed,replicates=replicates,
                  block_length=block_length,market_count=len(clusters),effective_markets=effective,sample_count=len(values),
                  point_estimate=mean(values),confidence_level='.95',interval=None,
                  limitation='Conditional empirical uncertainty; fixed block length does not prove independence; no resampled portfolio.')
        if effective<minimum_markets or len(clusters)<block_length:
            return dict(base,status='INSUFFICIENT_SAMPLE',distribution=None)
        rng=random.Random(seed);draws=[];n=len(clusters)
        for _ in range(replicates):
            chosen=[]
            while len(chosen)<n:
                start=rng.randrange(n-block_length+1);chosen.extend(clusters[start:start+block_length])
            sample=[v for c in chosen[:n] for v in c]
            if sample:draws.append(mean(sample))
        if len(draws)!=replicates:return dict(base,status='INSUFFICIENT_SAMPLE',distribution=None)
        ordered=sorted(draws);low=ordered[max(0,ceil(replicates*.025)-1)];high=ordered[ceil(replicates*.975)-1]
        base['interval']=[low,high]
        return dict(base,status='ESTIMATE',distribution=dict(mean=mean(draws),median=median(draws),p025=low,p975=high),
                    draws=draws)
