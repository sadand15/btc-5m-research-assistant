"""Fixed local perturbations; every row retained and no selection API."""
from dataclasses import replace
from decimal import Decimal as D
from btc5_v3.m8.models import Baseline,fixed_decimal
from btc5_v3.validation.replay import replay

OFFSETS=tuple(map(D,('-.01','-.005','0','.005','.01')))


@fixed_decimal
def shape(counts,denominator):
    delta=[b-a for a,b in zip(counts,counts[1:])]
    return dict(plateau_intervals=[i for i,d in enumerate(delta) if d==0],
                cliff_intervals=[i for i,d in enumerate(delta) if denominator and D(abs(d))/denominator>=D('.25')],
                spike_points=[i for i in range(1,len(counts)-1) if counts[i]>max(counts[i-1],counts[i+1]) or counts[i]<min(counts[i-1],counts[i+1])],
                definition='COUNTS_ONLY: equal adjacent=plateau; >=25% cohort change=cliff; strict local extremum=spike')


def sensitivity(dataset,*,cutoff,code_git):
    if dataset.manifest.role!='DEVELOPMENT':raise ValueError('sensitivity requires development role')
    b=Baseline();rows=[]
    for offset in OFFSETS:
        value=b.edge.minimum_net_edge_per_share+offset
        variant=replace(b,edge=replace(b.edge,minimum_net_edge_per_share=value),variant='BASELINE' if offset==0 else 'EDGE_'+str(value))
        result=replay(dataset,variant,cutoff=cutoff,code_git=code_git,research_variant=True)
        rows.append(dict(parameter=value,config_hash=variant.hash,variant=variant.variant,summary=result['summary'],rows=result['rows'],diagnostics=result['diagnostics']))
    counts=[r['summary']['candidate_count'] for r in rows]
    stability=shape(counts,rows[2]['summary']['count'])
    stability['plateau_intervals']=[i for i in stability['plateau_intervals'] if rows[i]['summary']['permission_count']==rows[i+1]['summary']['permission_count']]
    means=[D(r['summary']['mean_edge']) if r['summary']['mean_edge'] is not None else None for r in rows]
    return dict(baseline_hash=b.hash,parameter='minimum_net_edge_per_share',units='collateral_per_gross_share',grid=rows,
                stability=stability,
                sign_change_intervals=[i for i,(a,b) in enumerate(zip(means,means[1:])) if a is not None and b is not None and a*b<0],
                interpretation='MEASURE_STABILITY_ONLY_NO_SELECTION')
