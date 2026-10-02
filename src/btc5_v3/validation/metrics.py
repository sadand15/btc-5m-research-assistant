"""Explicit denominators; M4 calibration reused without retraining."""
from decimal import Decimal as D,localcontext
from btc5_v3.edge.numeric import CONTEXT
from btc5_v3.analytics.statistics import calibration,mean


def metrics(rows,baseline):
    with localcontext(CONTEXT):return _metrics(rows,baseline)


def _metrics(rows,baseline):
    n=len(rows);approved=[r for r in rows if r['permission']['action']!='REJECT']
    filled=[r for r in approved if r['execution'] and r['execution']['positions']]
    completed=[r for r in filled if r['execution']['accounting']['completed']]
    reports=[r['execution'] for r in rows if r['execution']]
    rate=lambda a,b:D(a)/b if b else None
    fees={k:sum((D(e['accounting']['total_fees'][k]) for e in reports),D(0)) for k in ('collateral','entry_shares','exit_shares','settlement_shares')}
    return dict(count=n,candidate_count=sum(r['decision']['final_action']!='NO_TRADE' for r in rows),
         permission_count=len(approved),reject_count=n-len(approved),reject_rate=rate(n-len(approved),n),
         reduce_count=sum(r['permission']['action']=='REDUCE' for r in rows),
         reduce_rate=rate(sum(r['permission']['action']=='REDUCE' for r in rows),n),
         average_approved_size=mean([D(r['permission']['approved_shares']) for r in approved]),
         fill_count=len(filled),fill_rate=rate(len(filled),len(approved)),fill_denominator=len(approved),
         partial_fill_rate=rate(sum(r['execution']['entry_status']=='PARTIAL_FILL' for r in filled),len(approved)),
         execution_cost=sum((D(e['accounting']['gross_entry_cost']) for e in reports),D(0)),fees=fees,
         completed_count=len(completed),simulated_pnl=sum((D(r['execution']['accounting']['net_simulated_pnl']) for r in completed),D(0)) if completed else None,
         mean_edge=mean([D(r['edge']) for r in rows if r['edge'] is not None]),
         risk_trigger_count=sum(x['action']=='TRIGGER' for r in rows for x in r['risk_events']),
         risk_trigger_frequency=rate(sum(x['action']=='TRIGGER' for r in rows for x in r['risk_events']),n),
         calibration=calibration([(D(r['p_yes']),D(r['outcome'])) for r in rows if r['outcome'] is not None],baseline.analytics),
         assumptions='UNCHANGED_M5_ASK_BID_IOC_LATENCY_FEES; M6_COST_BASIS_EQUITY; SYNTHETIC_ONLY',
         no_fill_pending_unresolved='NOT_INCLUDED_IN_COMPLETED_SIMULATED_PNL')


def grouped(rows,baseline,dimension):
    keys=sorted({r.get('side') or 'NO_SIDE' if dimension=='side' else r['regimes'][dimension] for r in rows})
    return {k:metrics([r for r in rows if (r.get('side') or 'NO_SIDE' if dimension=='side' else r['regimes'][dimension])==k],baseline) for k in keys}
