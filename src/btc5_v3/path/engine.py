"""Explicit post-hoc paths. No outcome or future quote is fed to M1-M3."""
from collections import Counter, defaultdict
from dataclasses import asdict
from decimal import Decimal, localcontext
import json

from btc5_v3.encoding import canonical, digest
from btc5_v3.edge.numeric import CONTEXT
from btc5_v3.analytics.models import validate_run_identity, ResolvedOutcome
from btc5_v3.analytics.statistics import mean, median
from btc5_v3.path.models import MarketPathPoint, PathAnalysisResult

D=Decimal


def bucket(value,edges):
    if value<edges[0] or value>edges[-1]: raise ValueError('outside registered bucket range')
    for i, high in enumerate(edges[1:]):
        if value<high or i==len(edges)-2: return i


def fresh(p,at,cfg):
    return (p['available_at']<=at<p['expiry']
            and 0<=at-p['source_at']<=cfg.max_quote_age_ms
            and 0<=at-p['received_at']<=cfg.max_quote_age_ms)


def gaps(points,start,end,cfg):
    times=sorted(set([start,end]+[p['received_at'] for p in points if start<=p['received_at']<=end]))
    return [dict(after=a,before=b,duration_ms=b-a) for a,b in zip(times,times[1:]) if b-a>cfg.max_missing_interval_ms]


def turns(points,key,epsilon,cfg):
    """Directional-change confirmations; restart at a missing-data gap."""
    direction=0;extreme=None;previous=None;count=0
    for p in points:
        x=p[key]
        if previous is None or p['received_at']-previous>cfg.max_missing_interval_ms:
            direction=0;extreme=x
        elif direction==0:
            if abs(x-extreme)>=epsilon: direction=1 if x>extreme else -1;extreme=x
        elif direction==1:
            if x>extreme: extreme=x
            elif extreme-x>=epsilon: count+=1;direction=-1;extreme=x
        else:
            if x<extreme: extreme=x
            elif x-extreme>=epsilon: count+=1;direction=1;extreme=x
        previous=p['received_at']
    return count


def observation(p,future,side,view,cutoff,cfg,payout,*,anchor_at=None):
    at=p['observation_at'] if anchor_at is None else anchor_at
    rows=[x for x in future if x['available_at']>=at and x['received_at']>=at]
    mid=p[side+'_mid'];bid=p[side+'_bid']
    maxmid=max(rows,key=lambda x:x[side+'_mid']) if rows else None
    minmid=min(rows,key=lambda x:x[side+'_mid']) if rows else None
    maxbid=max(rows,key=lambda x:x[side+'_bid']) if rows else None
    minbid=min(rows,key=lambda x:x[side+'_bid']) if rows else None
    missing=gaps(rows,at,min(p['expiry'],cutoff),cfg)
    source_age=at-p['source_at'];receipt_age=at-p['received_at']
    complete=cutoff>=p['expiry'] and bool(rows) and not missing
    return dict(market_id=p['market_id'],snapshot_id=p['snapshot_id'],side=side.upper(),view=view,
                at=at,sequence=p['sequence'],remaining_ms=p['expiry']-at,
                initial_mid=mid,initial_bid=bid,price_bucket=bucket(mid,cfg.price_buckets),
                bid_price_bucket=bucket(bid,cfg.price_buckets),tte_bucket=bucket(p['expiry']-at,cfg.tte_buckets_ms),
                future_max_mid=maxmid[side+'_mid'] if rows else None,future_min_mid=minmid[side+'_mid'] if rows else None,
                future_max_bid=maxbid[side+'_bid'] if rows else None,future_min_bid=minbid[side+'_bid'] if rows else None,
                max_mid_rebound=maxmid[side+'_mid']-mid if rows else None,
                max_bid_rebound=maxbid[side+'_bid']-bid if rows else None,
                max_drawdown=mid-minmid[side+'_mid'] if rows else None,
                max_bid_drawdown=bid-minbid[side+'_bid'] if rows else None,
                time_to_max_rebound=maxmid['received_at']-at if rows else None,
                time_to_max_bid_rebound=maxbid['received_at']-at if rows else None,
                time_to_max_drawdown=minmid['received_at']-at if rows else None,
                settlement_payout=payout,future_observation_count=len(rows),missing_quote_intervals=missing,
                observed_future=bool(rows),complete_observation_window=complete,right_censored=cutoff<p['expiry'],
                spread=p[side+'_spread'],normalized_spread=p[side+'_spread']/mid,
                visible_bid_depth=p[side+'_visible_bid_depth'],visible_ask_depth=p[side+'_visible_ask_depth'],
                source_age_ms=source_age,receipt_age_ms=receipt_age,m3_status=p['m3_status'],
                no_derived=p['no_derived'],liquidity_independent=False)


def summary(rows,metric,cfg):
    values=[x[metric] for x in rows if x[metric] is not None]
    observed=[x for x in rows if x[metric] is not None]
    complete=[x for x in observed if x['complete_observation_window']]
    markets=len({x['market_id'] for x in observed})
    grid=[]
    for threshold in cfg.rebound_thresholds:
        hits=[x for x in observed if x[metric]>=threshold]
        # Each market contributes one within-market fraction, avoiding tick-count weighting.
        grouped=defaultdict(list)
        for x in observed: grouped[x['market_id']].append(D(x[metric]>=threshold))
        binary=[x for x in hits if x['settlement_payout'] in (D(0),D(1))]
        draw='max_bid_drawdown' if metric=='max_bid_rebound' else 'max_drawdown'
        grid.append(dict(threshold=threshold,hit_count=len(hits),observed_future_denominator=len(observed),
                         observed_hit_fraction=D(len(hits))/len(observed) if observed else None,
                         market_balanced_hit_fraction=mean([mean(v) for v in grouped.values()]),
                         complete_window_denominator=len(complete),
                         complete_window_hit_fraction=mean([D(x[metric]>=threshold) for x in complete]),
                         rebound_then_losing_settlement=sum(x['settlement_payout']==0 for x in hits),
                         rebound_then_winning_settlement=sum(x['settlement_payout']==1 for x in hits),
                         rebound_then_split=sum(x['settlement_payout']==D('.5') for x in hits),
                         rebound_unresolved=sum(x['settlement_payout'] is None for x in hits),
                         rebound_binary_settlement_denominator=len(binary),
                         observed_downward_extension_count=sum(x[draw]>=threshold for x in observed),
                         low_price_continuation_count=sum(x['initial_'+('bid' if metric=='max_bid_rebound' else 'mid')]<D('.5') and x[draw]>=threshold for x in observed),
                         high_price_continuation_count=sum(x['initial_'+('bid' if metric=='max_bid_rebound' else 'mid')]>D('.5') and x[metric]>=threshold for x in observed)))
    drawmetric='max_bid_drawdown' if metric=='max_bid_rebound' else 'max_drawdown'
    return dict(count=len(rows),observed_future_count=len(values),no_future_count=len(rows)-len(values),unique_markets=markets,
                median_max_rebound=median(values),mean_max_rebound=mean(values),
                median_max_drawdown=median([x[drawmetric] for x in observed]),
                negative_rebound_count=sum(x<0 for x in values),zero_rebound_count=sum(x==0 for x in values),
                complete_window_count=len(complete),grid=grid,
                status='DESCRIPTIVE_ONLY' if markets>=cfg.minimum_sample_count else 'INSUFFICIENT_SAMPLE',
                inference='NO_INDEPENDENCE_OR_SIGNIFICANCE_CLAIM; OBSERVED_PATH_HIT_FRACTIONS_NOT_FULL_PATH_PROBABILITIES')


def _analyze(points,outcomes,cfg,experiment_id,code_git,cutoff,created_at):
    validate_run_identity(experiment_id,code_git,cutoff,created_at)
    if any(not isinstance(p,MarketPathPoint) for p in points) or any(not isinstance(o,ResolvedOutcome) for o in outcomes):
        raise TypeError('typed path archives and outcomes required')
    allpoints=[p.data() for p in points]
    if any(p['experiment_id']!=experiment_id for p in allpoints) or any(o.experiment_id!=experiment_id for o in outcomes):
        raise ValueError('cross-experiment path analysis forbidden')
    if len({p['snapshot_id'] for p in allpoints})!=len(allpoints): raise ValueError('duplicate snapshot')
    if len({(p['market_id'],p['received_at'],p['sequence']) for p in allpoints})!=len(allpoints): raise ValueError('ambiguous path ordering')
    if len({o.market_id for o in outcomes})!=len(outcomes): raise ValueError('ambiguous outcome')
    # A market means one five-minute contract, not just a reused venue label.
    contracts={}
    for p in allpoints:
        contract=tuple(p[k] for k in ('expiry','source','feed','rule_hash','outcome_mapping'))
        if p['market_id'] in contracts and contracts[p['market_id']]!=contract: raise ValueError('market contract changed')
        contracts[p['market_id']]=contract
    input_hash=digest(dict(points=sorted((asdict(p) for p in points),key=lambda x:digest(x)),
                           outcomes=sorted((json.loads(o.to_json()) for o in outcomes),key=lambda x:x['outcome_id'])))
    identity=digest([experiment_id,code_git,cutoff,cfg.hash,input_hash])
    paths=defaultdict(list);excluded=Counter()
    for p in allpoints:
        if p['observation_at']>cutoff: excluded['NOT_YET_AVAILABLE']+=1
        elif not 0<=p['remaining_ms']<=300000 or p['received_at']<p['expiry']-300000 or p['remaining_ms']==0:
            excluded['OUTSIDE_FIVE_MINUTE_CYCLE']+=1
        else: paths[p['market_id']].append(p)
    outmap={o.market_id:o for o in outcomes};label_status={};observations=[];marketrows=[];fixed=[];gaprows=[]
    clean_count=stale_count=0
    for market in sorted(paths):
        rows=sorted(paths[market],key=lambda x:(x['received_at'],x['sequence']))
        expiry=rows[0]['expiry'];o=outmap.get(market);payout=None
        label_status[market]='UNRESOLVED'
        if o:
            if (o.rule_hash!=rows[0]['rule_hash'] or o.source!='synthetic-settlement' or o.settlement_version!='synthetic-settlement-v1'):
                label_status[market]='INCOMPATIBLE_OUTCOME'
            elif o.resolution_at<expiry: label_status[market]='PREMATURE_RESOLUTION'
            elif max(o.resolution_at,o.available_at)>cutoff: label_status[market]='OUTCOME_NOT_YET_AVAILABLE'
            else: payout=o.yes_payout;label_status[market]='SYNTHETIC_RESEARCH_RESOLVED'
        clean=[p for p in rows if fresh(p,p['observation_at'],cfg)]
        clean_count+=len(clean);stale_count+=len(rows)-len(clean)
        for view,series in (('ALL_STRUCTURALLY_VALID',rows),('FRESHNESS_FILTERED',clean)):
            missing=gaps(series,expiry-300000,min(expiry,cutoff),cfg)
            gaprows.append(dict(market_id=market,view=view,missing_intervals=missing,right_censored=cutoff<expiry))
            for side in ('yes','no'):
                sidepayout=payout if side=='yes' or payout is None else 1-payout
                own=[]
                for i,p in enumerate(series):
                    item=observation(p,series[i+1:],side,view,cutoff,cfg,sidepayout)
                    item.update(path_observation_count=len(series),stale_quote_count=len(rows)-len(clean))
                    observations.append(item);own.append(item)
                vals=[p[side+'_mid'] for p in series];bids=[p[side+'_bid'] for p in series]
                changes=turns(series,side+'_mid',cfg.minimum_move_epsilon,cfg)
                large=turns(series,side+'_mid',cfg.large_reversal_move,cfg)
                rebounds=[x['max_mid_rebound'] for x in own if x['observed_future']]
                draws=[x['max_drawdown'] for x in own if x['observed_future']]
                marketrows.append(dict(market_id=market,side=side.upper(),view=view,path_observation_count=len(series),
                    stale_quote_count=len(rows)-len(clean),intracycle_high=max(vals) if vals else None,
                    intracycle_low=min(vals) if vals else None,total_range=max(vals)-min(vals) if vals else None,
                    bid_high=max(bids) if bids else None,bid_low=min(bids) if bids else None,
                    number_of_direction_changes=changes,number_of_large_reversals=large,whipsaw_observed=large>=2,
                    maximum_rebound=max(rebounds) if rebounds else None,maximum_drawdown=max(draws) if draws else None,
                    settlement_payout=sidepayout,missing_interval_count=len(missing),
                    movement_scope='SEGMENTED_AT_MISSING_GAPS; RANGE_AND_EXTREMA_OBSERVED_ONLY'))
            for tte in cfg.fixed_tte_ms:
                at=expiry-tte
                eligible=[p for p in series if p['received_at']<=at and p['observation_at']<=at and fresh(p,at,cfg)] if at<=cutoff else []
                p=eligible[-1] if eligible else None
                for side in ('yes','no'):
                    if p is None:
                        fixed.append(dict(market_id=market,view=view,side=side.upper(),target_tte_ms=tte,
                                          status='MISSING',reason='TARGET_AFTER_CUTOFF' if at>cutoff else 'NO_FRESH_CAUSALLY_AVAILABLE_QUOTE'))
                    else:
                        future=[x for x in series if (x['received_at'],x['sequence'])>(p['received_at'],p['sequence']) and x['received_at']>at]
                        value=observation(p,future,side,view,cutoff,cfg,payout if side=='yes' or payout is None else 1-payout,anchor_at=at)
                        fixed.append(dict(market_id=market,view=view,side=side.upper(),target_tte_ms=tte,status='OBSERVED_ASOF',
                                          quote_received_at=p['received_at'],quote_available_at=p['available_at'],metrics=value))
    tables=[]
    for view in ('ALL_STRUCTURALLY_VALID','FRESHNESS_FILTERED'):
        for side in ('YES','NO'):
            selected=[x for x in observations if x['view']==view and x['side']==side]
            for price in ('mid','bid'):
                for pi in range(len(cfg.price_buckets)-1):
                    for ti in range(len(cfg.tte_buckets_ms)-1):
                        group=[x for x in selected if x['price_bucket' if price=='mid' else 'bid_price_bucket']==pi and x['tte_bucket']==ti]
                        tables.append(dict(view=view,side=side,price_view=price,price_bucket=pi,tte_bucket=ti,
                                           **summary(group,'max_'+price+'_rebound',cfg)))
    conditioning=[]
    dimensions={'spread':(D(0),D('.02'),D('.05'),D('.10'),D(1)),
                'normalized_spread':(D(0),D('.1'),D('.5'),D(1),D(2)),
                'visible_bid_depth':(D(0),D(1),D(10),D(100),D('1e22')),
                'visible_ask_depth':(D(0),D(1),D(10),D(100),D('1e22')),
                'source_age_ms':(-60000,0,1000,5000,253402300799999),
                'receipt_age_ms':(0,1000,5000,253402300799999)}
    for view in ('ALL_STRUCTURALLY_VALID','FRESHNESS_FILTERED'):
        for side in ('YES','NO'):
            selected=[x for x in observations if x['view']==view and x['side']==side]
            for dimension,edges in dimensions.items():
                for i in range(len(edges)-1):
                    group=[x for x in selected if bucket(x[dimension],edges)==i]
                    conditioning.append(dict(view=view,side=side,dimension=dimension,lower=edges[i],upper=edges[i+1],
                        mid=summary(group,'max_mid_rebound',cfg),bid=summary(group,'max_bid_rebound',cfg)))
            for status in ('UNAVAILABLE','NOT_YET_AVAILABLE','ADMISSIBLE','REJECTED'):
                group=[x for x in selected if x['m3_status']==status]
                conditioning.append(dict(view=view,side=side,dimension='m3_status',value=status,
                    mid=summary(group,'max_mid_rebound',cfg),bid=summary(group,'max_bid_rebound',cfg)))
    report=dict(mode='SYNTHETIC_OR_EXPLICIT_ARCHIVE_PATH_RESEARCH',config=asdict(cfg),
        coverage=dict(input_markets=len(contracts),markets=len(paths),input_path_points=len(allpoints),
            path_points=sum(map(len,paths.values())),freshness_filtered_points=clean_count,stale_quote_count=stale_count,
            exclusions=dict(sorted(excluded.items())),input_scope='EXPLICIT_ARCHIVE_NOT_WHOLE_DATABASE',
            missing_intervals=gaprows,outcome_status=label_status),
        points=sorted([p for rows in paths.values() for p in rows],key=lambda p:(p['market_id'],p['received_at'],p['sequence'])),
        observations=observations,market_metrics=marketrows,study_tables=tables,conditioning=conditioning,fixed_tte=fixed,
        btc_shock_status='UNAVAILABLE_NO_CAUSAL_BTC_SERIES',
        limitations=['POST_HOC_ONLY','NO_EXECUTION_SIMULATION','BID_DOES_NOT_GUARANTEE_FILL','NO_QUEUE_MODELING',
            'NO_LATENCY_OR_FEES_OR_PARTIAL_FILL','NO_STRATEGY_RECOMMENDATION','NO_THRESHOLD_OPTIMIZATION',
            'SYNTHETIC_SETTLEMENT_ONLY','MID_IS_DESCRIPTIVE_BID_IS_OBSERVABLE_PROXY',
            'NO_INTERPOLATION_OR_FUTURE_BACKFILL','SPARSE_PATH_EXTREMA_ARE_OBSERVED_ONLY',
            'REPEATED_POINTS_ARE_NOT_INDEPENDENT','NO_CLUSTER_CONFIDENCE_INTERVALS',
            'NO_CLAIM_OF_REPRODUCIBLE_REAL_MARKET_PATTERN_FROM_SYNTHETIC_FIXTURES'])
    return PathAnalysisResult(identity,experiment_id,code_git,cutoff,created_at,cfg.hash,input_hash,canonical(report))


def analyze_paths(points,outcomes,config,*,experiment_id,code_git,cutoff,created_at):
    with localcontext(CONTEXT):
        return _analyze(tuple(points),tuple(outcomes),config,experiment_id,code_git,cutoff,created_at)
