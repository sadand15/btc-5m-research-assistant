"""Descriptive portfolio audit, without strategy or sizing recommendations."""
from collections import Counter
from decimal import localcontext, Decimal
from btc5_v3.encoding import canonical
from btc5_v3.edge.numeric import CONTEXT
from btc5_v3.risk.models import RiskConfig
from btc5_v3.risk.engine import portfolio


def report(run, ctx, outputs, at):
    with localcontext(CONTEXT):
        c = RiskConfig(**run['config']); state = portfolio(ctx, c, at)
        decisions = [o['risk_decision'] for o in outputs if 'risk_decision' in o]
        actions = Counter(d['action'] for d in decisions)
        reasons = Counter(r for d in decisions for r in d['all_reasons'])
        changes = [r for o in outputs for r in o.get('reservation_changes', [])]
        statuses = Counter(r['status'] for r in changes)
        return dict(mode='OFFLINE_SYNTHETIC_PORTFOLIO_PERMISSION_ONLY', run_id=run['run_id'],
            code_git=run['code_git'], risk_config_hash=c.hash, as_of=at, capital=state,
            original_candidates=[dict(risk_decision_id=rid, original=value['original'],
                                      execution_config=value['execution_config'], policy=value['policy'])
                                 for rid, value in sorted(ctx['approvals'].items())],
            permissions=dict(actions), reason_counts=dict(reasons),
            utilization=dict(total_exposure=state['total_exposure']/c.max_total_open_exposure,
                             daily_loss=max(Decimal(0), -state['daily_pnl'])/c.max_daily_simulated_loss,
                             position=[dict(risk_decision_id=d['risk_decision_id'],
                                            fraction=Decimal(d['approved_notional'])/c.max_position_notional) for d in decisions]),
            controls=[x for o in outputs for x in o['control_events']],
            reservations=dict(created=len(ctx['reservations']), transitions=dict(statuses),
                              current=dict(Counter(x['status'] for x in ctx['reservations'].values())),
                              records=ctx['reservations']),
            funnel=dict(m3_candidates=len(decisions), risk_approved=actions['APPROVE'], risk_reduced=actions['REDUCE'],
                        risk_rejected=actions['REJECT'], reserved=len(ctx['reservations']),
                        m5_started=len(ctx['reports']), m5_with_position=sum(bool(x['positions']) for x in ctx['reports'].values()),
                        reconciliations=sum('execution' in o for o in outputs)),
            events=outputs,
            limitations=['simulation only; no live accounts or orders',
                         'worst-case binary collateral bound, not recommended stake',
                         'cost-basis equity excludes unrealized market gains and losses',
                         'M5 fills are simulated and do not establish fillability or profitability',
                         'exit/settlement fixed collateral-per-share fees unsupported in portfolio mode',
                         'financial drawdown and loss-streak pauses latch for this research run'])


def markdown(value):
    return '# M6 Synthetic Risk Evidence\n\nNo real account, order or profitability claim.\n\n' + '\n\n'.join(
        '## '+name+'\n\n```json\n'+canonical(value[name])+'\n```' for name in ('capital', 'permissions', 'reason_counts', 'funnel', 'reservations', 'controls', 'limitations'))+'\n'
