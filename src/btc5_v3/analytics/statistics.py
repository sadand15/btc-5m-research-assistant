"""Deterministic descriptive metrics. No fit, shuffle, optimizer or independence claim."""
from decimal import Decimal, localcontext
from btc5_v3.edge.numeric import CONTEXT, rounded, number

D=Decimal


def mean(values):return sum(values,D(0))/len(values) if values else None


def median(values):
    if not values:return None
    ordered=sorted(values);n=len(ordered)
    return ordered[n//2] if n%2 else (ordered[n//2-1]+ordered[n//2])/2


def probability_bin(p,edges):
    for i,upper in enumerate(edges[1:]):
        if p<upper or i==len(edges)-2:return i
    raise ValueError('invalid probability bin')


def edge_bucket(value):
    if value<0:return 'NEGATIVE'
    if value==0:return 'ZERO'
    for high,label in ((D('.02'),'POS_LT_02'),(D('.05'),'02_TO_05'),(D('.10'),'05_TO_10'),(D('.15'),'10_TO_15')):
        if value<high:return label
    return 'GE_15'


EDGE_BUCKETS=('NEGATIVE','ZERO','POS_LT_02','02_TO_05','05_TO_10','10_TO_15','GE_15')
TTE_BUCKETS=('0_TO_30S','30_TO_60S','60_TO_120S','120_TO_180S','GE_180S')


def tte_bucket(ms):
    if ms<0:raise ValueError('negative TTE is excluded')
    for high,label in zip((30000,60000,120000,180000),TTE_BUCKETS):
        if ms<high:return label
    return TTE_BUCKETS[-1]


def calibration(pairs,config):
    """Brier against payout including split; LL/ECE/MCE strictly binary only."""
    with localcontext(CONTEXT):
        values=[(number(p,minimum=0,maximum=1),number(y)) for p,y in pairs]
        if any(y not in (D(0),D('.5'),D(1)) for _,y in values):raise ValueError('unsupported payout')
        binary=[(p,y) for p,y in values if y!=D('.5')]
        bins=[]
        for i in range(len(config.calibration_bin_edges)-1):
            all_rows=[(p,y) for p,y in values if probability_bin(p,config.calibration_bin_edges)==i]
            rows=[(p,y) for p,y in all_rows if y!=D('.5')]
            predicted=mean([p for p,_ in rows]);observed=mean([y for _,y in rows])
            gap=observed-predicted if rows else None
            bins.append(dict(lower=config.calibration_bin_edges[i],upper=config.calibration_bin_edges[i+1],
                             count=len(all_rows),binary_count=len(rows),split_count=len(all_rows)-len(rows),
                             mean_predicted_probability=predicted,observed_yes_rate=observed,calibration_gap=gap))
        eps=config.log_loss_epsilon;losses=[];clipped=0
        for p,y in binary:
            numeric=min(max(p,eps),1-eps);clipped+=numeric!=p
            losses.append(-(y*numeric.ln()+(1-y)*(1-numeric).ln()))
        gaps=[abs(b['calibration_gap']) for b in bins if b['binary_count']]
        return dict(count=len(values),binary_settled_count=len(binary),split_count=len(values)-len(binary),
                    split_frequency=mean([D(y==D('.5')) for _,y in values]),
                    brier_payout=mean([(p-y)**2 for p,y in values]),
                    brier_binary=mean([(p-y)**2 for p,y in binary]),log_loss=rounded(mean(losses)) if losses else None,
                    log_loss_epsilon=eps,log_loss_clipped_count=clipped,log_loss_split_excluded_count=len(values)-len(binary),
                    ece=sum((abs(b['calibration_gap'])*b['binary_count'] for b in bins if b['binary_count']),D(0))/len(binary) if binary else None,
                    mce=max(gaps) if gaps else None,bins=bins,
                    weighting='BINARY_OBSERVATION_COUNT; SPLIT EXCLUDED FROM LL/ECE/MCE; BRIER_PAYOUT INCLUDES 0.5',
                    status='AVAILABLE' if values else 'NO_RESOLVED_SAMPLE')


def ranks(values):
    output=[D(0)]*len(values);order=sorted(range(len(values)),key=lambda i:values[i]);i=0
    while i<len(order):
        j=i+1
        while j<len(order) and values[order[j]]==values[order[i]]:j+=1
        rank=D(i+1+j)/2
        for k in order[i:j]:output[k]=rank
        i=j
    return output


def spearman(xs,ys,*,minimum_sample_count,unique_markets):
    with localcontext(CONTEXT):
        if len(xs)!=len(ys):raise ValueError('paired series required')
        if len(xs)<minimum_sample_count or unique_markets<minimum_sample_count:
            return dict(status='INSUFFICIENT_SAMPLE',count=len(xs),unique_markets=unique_markets,correlation=None)
        x=ranks(xs);y=ranks(ys);mx=mean(x);my=mean(y)
        xx=sum(((v-mx)**2 for v in x),D(0));yy=sum(((v-my)**2 for v in y),D(0))
        corr=sum(((a-mx)*(b-my) for a,b in zip(x,y)),D(0))/(xx*yy).sqrt() if xx and yy else None
        return dict(status='DESCRIPTIVE_ONLY' if corr is not None else 'CONSTANT_SERIES',count=len(xs),unique_markets=unique_markets,
                    correlation=rounded(corr) if corr is not None else None)


def bucket_summary(rows):
    edges=[x['net_edge'] for x in rows];returns=[x['hypothetical_realized_return'] for x in rows if x['hypothetical_realized_return'] is not None]
    binary=[x for x in rows if x['payout'] in (D(0),D(1))]
    avg=mean(returns)
    variance=sum(((x-avg)**2 for x in returns),D(0))/(len(returns)-1) if len(returns)>1 else None
    return dict(count=len(rows),resolved_count=len(returns),unique_markets=len({x['market_id'] for x in rows}),
                mean_predicted_edge=mean(edges),median_predicted_edge=median(edges),
                mean_hypothetical_realized_return=avg,median_hypothetical_realized_return=median(returns),
                binary_win_fraction=mean([D(x['payout']==1) for x in binary]),binary_win_denominator=len(binary),
                split_count=sum(x['payout']==D('.5') for x in rows),
                hypothetical_return_standard_deviation=variance.sqrt() if variance is not None else None,
                standard_error=None,confidence_interval=None,inference_status='CLUSTER_INFERENCE_NOT_IMPLEMENTED')
