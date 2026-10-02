"""Descriptive concentration and existing-M4 calibration drift; no feature selection."""
from decimal import Decimal as D,localcontext
from btc5_v3.edge.numeric import CONTEXT
from btc5_v3.analytics.statistics import calibration
from btc5_v3.robustness.bootstrap import bootstrap

DIMENSIONS=('probability','tte','spread','liquidity','btc_shock','side','market','day')


def label(r,dimension):return (r.get('side') or 'NO_SIDE') if dimension=='side' else r['regimes'][dimension]


def dependence(rows):
    with localcontext(CONTEXT):
        result={};total=sum((abs(D(r['edge'])) for r in rows if r['edge'] is not None),D(0))
        for dimension in DIMENSIONS:
            groups=[]
            for key in sorted({label(r,dimension) for r in rows}):
                sub=[r for r in rows if label(r,dimension)==key]
                contribution=sum((abs(D(r['edge'])) for r in sub if r['edge'] is not None),D(0))
                groups.append(dict(bucket=key,count=len(sub),sample_share=D(len(sub))/len(rows),
                                   metric_share=contribution/total if total else None,absolute_edge_contribution=contribution))
            result[dimension]=dict(buckets=groups,sample_hhi=sum((x['sample_share']**2 for x in groups),D(0)) if groups else None,
                metric_hhi=sum((x['metric_share']**2 for x in groups),D(0)) if total else None,
                interpretation='DESCRIPTIVE_CONCENTRATION_NOT_CAUSAL_FEATURE_IMPORTANCE')
        return result


def drift(development_rows,validation_rows,baseline,*,seed=42):
    def cal(rows):return calibration([(D(r['p_yes']),D(r['outcome'])) for r in rows if r['outcome'] is not None],baseline.analytics)
    def compare(a,b):
        left=cal(a);right=cal(b)
        return dict(development=left,validation=right,
                    brier_delta=right['brier_payout']-left['brier_payout'] if left['count'] and right['count'] else None,
                    ece_delta=right['ece']-left['ece'] if left['ece'] is not None and right['ece'] is not None else None,
                    uncertainty='INSUFFICIENT_SAMPLE' if min(left['count'],right['count'])<baseline.analytics.minimum_sample_count else 'DESCRIPTIVE_DIFFERENCE',
                    development_brier_interval=bootstrap(a,'brier',seed=seed),validation_brier_interval=bootstrap(b,'brier',seed=seed))
    with localcontext(CONTEXT):
        groups={}
        for dimension in ('tte','probability','spread','liquidity','day'):
            keys=sorted({label(r,dimension) for r in development_rows+validation_rows})
            groups[dimension]={key:compare([r for r in development_rows if label(r,dimension)==key],
                                          [r for r in validation_rows if label(r,dimension)==key]) for key in keys}
        return dict(overall=compare(development_rows,validation_rows),groups=groups,
                    method='UNCHANGED_M4_CALIBRATION_PAYOUT_BRIER_BINARY_ECE_NO_REFIT')
