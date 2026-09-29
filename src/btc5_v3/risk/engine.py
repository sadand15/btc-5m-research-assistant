"""Pure event replay and permission sizing. M5 remains the money-flow authority."""
from dataclasses import asdict, replace
from decimal import Decimal, localcontext, ROUND_DOWN
import json

from btc5_v3.encoding import canonical, digest, timestamp
from btc5_v3.edge.numeric import CONTEXT, rounded
from btc5_v3.analytics.models import ResearchObservation, ResolvedOutcome
from btc5_v3.path.models import MarketPathPoint
from btc5_v3.execution.models import ExecutionConfig, ExitPolicy
from btc5_v3.execution.engine import validate_inputs, simulate
from btc5_v3.risk.models import RiskConfig, HealthEvidence, RiskDecision, CapitalReservation, PortfolioState

D = Decimal
ZERO = D(0)
PRECEDENCE = (
    'UPSTREAM_NO_TRADE', 'MANUALLY_PAUSED', 'DATA_KILL_SWITCH', 'PROVIDER_KILL_SWITCH',
    'INVALID_PORTFOLIO_STATE', 'STALE_PORTFOLIO_STATE', 'INSUFFICIENT_CAPITAL',
    'POSITION_LIMIT', 'MARKET_EXPOSURE_LIMIT', 'TOTAL_EXPOSURE_LIMIT', 'PENDING_EXPOSURE_LIMIT',
    'DAILY_LOSS_LIMIT', 'MAX_DRAWDOWN_REACHED', 'CONSECUTIVE_LOSS_LIMIT', 'SIZE_REDUCED', 'APPROVED')
CONTROL_REASONS = {
    'MANUALLY_PAUSED': 'MANUALLY_PAUSED', 'PAUSED_DATA': 'DATA_KILL_SWITCH',
    'PAUSED_PROVIDER': 'PROVIDER_KILL_SWITCH', 'PAUSED_DAILY_LOSS': 'DAILY_LOSS_LIMIT',
    'PAUSED_DRAWDOWN': 'MAX_DRAWDOWN_REACHED', 'PAUSED_LOSS_STREAK': 'CONSECUTIVE_LOSS_LIMIT'}


def collateral_bound(config):
    # The unchanged IOC may fill at any valid binary price up to one. Reserve its
    # worst-case entry cost; never assume the signal ask is an execution limit.
    for fee in (config.exit_fee, config.settlement_fee):
        if fee.denomination == 'COLLATERAL' and fee.collateral_per_share:
            raise ValueError('M6 does not support potentially negative exit/settlement proceeds')
    f = config.entry_fee
    return D(1) + f.rate + f.collateral_per_share if f.denomination == 'COLLATERAL' else D(1)


def _health_flags(health, at, config):
    if health is None:
        return ({'PAUSED_DATA'} if config.require_data_health else set()) | (
            {'PAUSED_PROVIDER'} if config.require_provider_health else set())
    h = HealthEvidence(**health)
    impossible = h.available_at > at or any(t is not None and t > h.available_at for t in (h.source_at, h.heartbeat_at))
    stale = (h.source_at is None or at - h.source_at > config.max_feed_age_ms
             or h.heartbeat_at is None or at - h.heartbeat_at > config.max_heartbeat_age_ms)
    flags = set()
    if config.require_data_health and (impossible or stale or not h.source_matches
                                       or h.validation_failures >= config.validation_failure_burst_limit):
        flags.add('PAUSED_DATA')
    if config.require_provider_health and (impossible or at - h.available_at > config.max_heartbeat_age_ms or not h.provider_healthy):
        flags.add('PAUSED_PROVIDER')
    return flags


def empty_context():
    return dict(approvals={}, reports={}, reservations={}, health=None, manual=False,
                last_at=None, control_states=['ACTIVE'])


def portfolio(ctx, config, at):
    with localcontext(CONTEXT):
        return _portfolio(ctx, config, at)


def _portfolio(ctx, c, at):
    if not timestamp(at):
        raise ValueError('invalid portfolio time')
    cash = c.starting_capital
    open_by_market = {}; open_by_side = {'YES': ZERO, 'NO': ZERO}
    realized_events = []; completed = []; ledger_ids = set(); settled_pnl = ZERO
    for rid, report in sorted(ctx['reports'].items()):
        ledger = report['ledger_entries']
        if any(x['at'] > at for x in ledger):
            raise ValueError('future ledger in portfolio prefix')
        for x in ledger:
            if x['ledger_id'] in ledger_ids:
                raise ValueError('duplicate money movement across positions')
            ledger_ids.add(x['ledger_id'])
            if x['asset'] == 'COLLATERAL' and x['account'] == 'CASH':
                cash += D(x['amount'])
        if not report['positions']:
            continue
        opening = report['positions'][0]
        initial = D(opening['filled_shares_net'])
        # M5 collateral_spent already includes its collateral entry fee.
        cost = D(opening['collateral_spent'])
        inventory = initial; basis = cost; net_realized = ZERO
        events = {}
        for x in ledger:
            events.setdefault((x['at'], x['event_id']), []).append(x)
        # Entry cost and net inventory are already known from M5's opening record.
        if initial == 0:
            realized_events.append((opening['opened_at'], rid, -cost, 'ENTRY_FEE'))
            net_realized = -cost; basis = ZERO
        for (time, event_id), legs in sorted(events.items()):
            if not any(x['reason'].startswith(('EXIT_', 'SETTLEMENT_', 'SETTLED_')) for x in legs):
                continue
            removed = -sum((D(x['amount']) for x in legs if x['account'] == 'INVENTORY'), ZERO)
            flow = sum((D(x['amount']) for x in legs if x['account'] == 'CASH' and x['asset'] == 'COLLATERAL'), ZERO)
            if removed < 0 or removed > inventory:
                raise ValueError('invalid M5 inventory movement')
            released_basis = basis if removed == inventory else min(basis, rounded(cost * removed / initial))
            profit = flow - released_basis
            basis -= released_basis; inventory -= removed; net_realized += profit
            kind = 'SETTLEMENT' if any(x['reason'].startswith(('SETTLEMENT_', 'SETTLED_')) for x in legs) else 'EXIT'
            realized_events.append((time, rid + event_id, profit, kind))
            if kind == 'SETTLEMENT': settled_pnl += profit
        accounting = report['accounting']
        if inventory != D(accounting['remaining_shares']):
            raise ValueError('M5 inventory reconciliation failed')
        if accounting['completed']:
            if inventory != 0 or net_realized != D(accounting['net_simulated_pnl']):
                raise ValueError('M5 completed PnL reconciliation failed')
            completed.append((max(x['at'] for x in ledger), rid, net_realized))
        market = report['market_id']; side = report['side']
        open_by_market[market] = open_by_market.get(market, ZERO) + basis
        open_by_side[side] += basis
    equity = c.starting_capital; peak = equity; max_dd = ZERO
    daily = ZERO; realized = ZERO; day = at // 86400000
    day_running = ZERO; day_minimum = ZERO
    # Aggregate simultaneous realizations: no arbitrary ID-order intratick peaks.
    by_time = {}
    for time, _, amount, _ in realized_events:
        by_time[time] = by_time.get(time, ZERO) + amount
        realized += amount
        if time // 86400000 == day: daily += amount
    for time, amount in sorted(by_time.items()):
        equity += amount; peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
        if time // 86400000 == day:
            day_running += amount; day_minimum = min(day_minimum, day_running)
    drawdown = (peak - equity) / peak
    streak = 0; max_streak = 0
    # Completion at equal milliseconds uses immutable risk-decision ID as tie-break.
    for _, _, pnl in sorted(completed):
        streak = streak + 1 if pnl < 0 else 0  # Zero resets; incomplete positions never count.
        max_streak = max(max_streak, streak)
    reserved = ZERO; pending_market = {}; pending_side = {'YES': ZERO, 'NO': ZERO}
    for rid, res in ctx['reservations'].items():
        amount = D(res['remaining_collateral']); reserved += amount
        approval = ctx['approvals'][rid]
        market = approval['original']['snapshot']['market_id']; side = approval['original']['decision']['side']
        pending_market[market] = pending_market.get(market, ZERO) + amount
        pending_side[side] += amount
    open_exposure = sum(open_by_market.values(), ZERO)
    flags = _health_flags(ctx['health'], at, c)
    if ctx['manual']: flags.add('MANUALLY_PAUSED')
    if -day_minimum >= c.max_daily_simulated_loss: flags.add('PAUSED_DAILY_LOSS')
    if max_dd >= c.max_drawdown: flags.add('PAUSED_DRAWDOWN')
    if max_streak >= c.max_consecutive_losses: flags.add('PAUSED_LOSS_STREAK')
    if cash < 0 or reserved < 0 or cash - reserved < 0 or equity != cash + open_exposure:
        raise ValueError('invalid portfolio accounting')
    value = dict(at=at, starting_capital=c.starting_capital, cash=cash, reserved_cash=reserved,
                 available_cash=cash-reserved, open_exposure=open_exposure, pending_exposure=reserved,
                 total_exposure=open_exposure+reserved, realized_pnl=realized, settled_pnl=settled_pnl,
                 daily_pnl=daily, daily_maximum_loss=-day_minimum, loss_day=day, equity=equity, peak_equity=peak, drawdown=drawdown,
                 maximum_drawdown=max_dd, consecutive_losses=streak, maximum_consecutive_losses=max_streak,
                 open_by_market=open_by_market, pending_by_market=pending_market,
                 open_by_side=open_by_side, pending_by_side=pending_side,
                 paused=bool(flags), control_states=sorted(flags) or ['ACTIVE'],
                 as_of=at, last_event_at=ctx['last_at'], ledger_count=len(ledger_ids))
    # Rounded display values never feed back into replay, cost accounting or sizing.
    return value


def evaluate(ctx, run, inputs):
    c = RiskConfig(**run['config']); exp = run['experiment_id']; at = inputs['at']
    original = ResearchObservation(canonical(inputs['original']))
    _, s, edge, d, _ = validate_inputs(original, (), None, exp)
    if d['final_action'] != 'NO_TRADE':
        side = d['side']
        if (side not in ('YES', 'NO') or d['final_action'] != 'BUY_'+side or d['all_reasons']
                or edge['candidate_action'] != d['final_action'] or edge['preferred_side'] != side
                or not edge[side.lower()] or not edge[side.lower()]['eligible']
                or D(d['requested_shares']) != D(edge['requested_shares'])
                or not ZERO < D(d['executable_shares'] or 0) <= D(d['requested_shares'])):
            raise ValueError('M3 permission lineage invalid')
    ec = ExecutionConfig.from_dict(inputs['execution_config']); ExitPolicy(**inputs['policy'])
    bound = collateral_bound(ec)
    if ec.requested_shares is not None:
        raise ValueError('M6 alone supplies the approved M5 quantity')
    if c.reservation_timeout < ec.decision_to_order_latency_ms + ec.maximum_wait_for_next_book_ms:
        raise ValueError('reservation timeout must cover M5 entry deadline')
    if at != d['evaluated_at']:
        raise ValueError('M6 must evaluate at original M3 time without shifting M5 latency')
    if inputs['health'] is not None:
        HealthEvidence(**inputs['health'])
        ctx['health'] = inputs['health']
    before = portfolio(ctx, c, at)
    state_id = digest(before); reasons = []
    requested = D(d['executable_shares'] or 0)
    rid = digest([run['run_id'], d['decision_id']])
    if d['final_action'] == 'NO_TRADE': reasons.append('UPSTREAM_NO_TRADE')
    reasons += [CONTROL_REASONS[x] for x in before['control_states'] if x != 'ACTIVE']
    if ctx['last_at'] is not None and at - ctx['last_at'] > c.max_portfolio_age_ms:
        reasons.append('STALE_PORTFOLIO_STATE')
    limits = {
        'INSUFFICIENT_CAPITAL': before['available_cash'] - c.minimum_available_cash,
        'POSITION_LIMIT': min(c.max_position_notional, c.max_position_fraction * before['equity']),
        'MARKET_EXPOSURE_LIMIT': c.max_market_exposure - before['open_by_market'].get(s['market_id'], ZERO) - before['pending_by_market'].get(s['market_id'], ZERO),
        'TOTAL_EXPOSURE_LIMIT': min(c.max_total_open_exposure, c.max_total_open_exposure_fraction * before['equity']) - before['total_exposure'],
        'PENDING_EXPOSURE_LIMIT': c.max_pending_exposure - before['pending_exposure']}
    requested_notional = requested * bound
    reasons += [reason for reason, limit in limits.items() if requested_notional > limit]
    allowance = max(ZERO, min([requested_notional, *limits.values()]))
    shares = (allowance / bound / c.minimum_share_unit).to_integral_value(rounding=ROUND_DOWN) * c.minimum_share_unit
    blocking = [r for r in reasons if r not in limits]
    if blocking or shares < c.minimum_share_unit or requested <= 0:
        action = 'REJECT'; shares = ZERO
        if not reasons: reasons.append('POSITION_LIMIT')
    elif shares < requested:
        action = 'REDUCE'; reasons.append('SIZE_REDUCED')
    else:
        action = 'APPROVE'; reasons.append('APPROVED')
    reasons = tuple(r for r in PRECEDENCE if r in reasons)
    decision = RiskDecision(rid, exp, d['decision_id'], at, requested, requested_notional,
                            shares, shares*bound, action, reasons[0], reasons, state_id, c.hash)
    record = dict(inputs, risk_decision=asdict(decision), state_before=before)
    ctx['approvals'][rid] = record
    reservation = None
    if action != 'REJECT':
        reservation = asdict(CapitalReservation(digest([rid, 'reservation']), d['decision_id'], shares,
            shares*bound, at, at+c.reservation_timeout, 'ACTIVE', remaining_collateral=shares*bound))
        ctx['reservations'][rid] = reservation
    return dict(risk_decision=asdict(decision), reservation=reservation, state_before=before)


def execute(ctx, run, inputs):
    rid = inputs['risk_decision_id']; at = inputs['at']
    if rid not in ctx['approvals'] or rid not in ctx['reservations']:
        raise ValueError('M6 execution requires approved decision and reservation')
    approval = ctx['approvals'][rid]; res = ctx['reservations'][rid]
    if res['status'] in ('EXPIRED', 'RELEASED') and rid not in ctx['reports']:
        raise ValueError('inactive entry reservation')
    old = ctx['reports'].get(rid)
    if res['status'] == 'EXPIRED' or (res['status'] == 'RELEASED' and (not old or not old['positions'])):
        raise ValueError('closed entry reservation')
    ec = replace(ExecutionConfig.from_dict(approval['execution_config']),
                 requested_shares=D(approval['risk_decision']['approved_shares']))
    result = simulate(ResearchObservation(canonical(approval['original'])),
                      tuple(MarketPathPoint(**x) for x in inputs['books']),
                      ResolvedOutcome.from_dict(inputs['outcome']) if inputs['outcome'] else None,
                      ec, ExitPolicy(**approval['policy']), experiment_id=run['experiment_id'],
                      code_git=run['code_git'], cutoff=at, created_at=at)
    report = result.data()
    if old:
        for field, key in (('ledger_entries', 'ledger_id'), ('fills', 'fill_id'), ('order_events', 'event_id'),
                           ('orders', 'order_id'), ('positions', 'position_id'), ('settlements', 'settlement_id')):
            current = {x[key]: x for x in report[field]}
            if any(current.get(x[key]) != x for x in old[field]):
                raise ValueError('M5 causal prefix rewrite')
    known = {x['ledger_id'] for x in old['ledger_entries']} if old else set()
    if ctx['last_at'] is not None and any(x['ledger_id'] not in known and x['at'] < ctx['last_at'] for x in report['ledger_entries']):
        raise ValueError('backdated reconciliation would invalidate portfolio permissions')
    fills = [x for x in report['fills'] if x['purpose'] == 'ENTRY']
    changes = []
    if fills:
        fill = fills[0]
        if fill['at'] > res['expires_at']:
            raise ValueError('entry after reservation deadline')
        if old is None or not old['positions']:
            if portfolio(ctx, RiskConfig(**run['config']), fill['at'])['paused']:
                raise ValueError('risk control blocks new entry; existing exits remain permitted')
        consumed = -sum((D(x['amount']) for x in report['ledger_entries']
                         if x['account'] == 'CASH' and x['reason'].startswith('ENTRY_')), ZERO)
        if consumed > D(res['reserved_collateral']):
            raise ValueError('M5 entry exceeded reserved collateral')
        release = D(res['reserved_collateral']) - consumed
        if res['status'] == 'ACTIVE':
            if fill['status'] == 'PARTIAL_FILL':
                partial = dict(res, status='PARTIALLY_CONSUMED', consumed_collateral=consumed,
                               remaining_collateral=release)
                changes.append(partial)
            res = dict(res, status='CONSUMED', consumed_collateral=consumed,
                       released_collateral=release, remaining_collateral=ZERO)
            changes.append(res)
    elif report['entry_status'] == 'NO_FILL' and res['status'] == 'ACTIVE':
        res = dict(res, status='RELEASED', released_collateral=res['reserved_collateral'], remaining_collateral=ZERO)
        changes.append(res)
    ctx['reservations'][rid] = res; ctx['reports'][rid] = report
    return dict(execution=result.data(), execution_id=result.execution_id,
                reservation_changes=changes, reservation=res)


def apply_event(ctx, run, kind, inputs):
    """Only this deterministic reducer may advance portfolio event state."""
    with localcontext(CONTEXT):
        at = inputs['at']; c = RiskConfig(**run['config'])
        if not timestamp(at) or at < run['created_at'] or (ctx['last_at'] is not None and at < ctx['last_at']):
            raise ValueError('portfolio events must be causal and nondecreasing')
        previous = ctx['control_states']
        if kind == 'EVALUATE':
            output = evaluate(ctx, run, inputs)
        elif kind == 'EXECUTE':
            output = execute(ctx, run, inputs)
        elif kind == 'CONTROL':
            action = inputs['action']
            if action == 'PAUSE': ctx['manual'] = True
            elif action == 'RESUME': ctx['manual'] = False
            elif action == 'HEALTH':
                HealthEvidence(**inputs['health']); ctx['health'] = inputs['health']
            elif action != 'RECONCILE': raise ValueError('unsupported control action')
            output = dict(action=action)
        elif kind == 'EXPIRE':
            rid = inputs['risk_decision_id']; res = ctx['reservations'][rid]
            if at < res['expires_at'] or res['status'] != 'ACTIVE':
                raise ValueError('only overdue active reservations can expire')
            res = dict(res, status='EXPIRED', released_collateral=res['reserved_collateral'], remaining_collateral=ZERO)
            ctx['reservations'][rid] = res; output = dict(reservation=res)
        else:
            raise ValueError('unsupported risk event')
        ctx['last_at'] = at
        state = portfolio(ctx, c, at)
        # A permission pause revokes still-unfilled capital permissions. It does
        # not alter any M5 fill, existing position, exit policy or settlement.
        cancelled = []
        if state['paused']:
            for rid, res in list(ctx['reservations'].items()):
                if res['status'] == 'ACTIVE':
                    value = dict(res, status='RELEASED', remaining_collateral=ZERO,
                                 released_collateral=res['reserved_collateral'], release_reason='RISK_PAUSE')
                    ctx['reservations'][rid] = value; cancelled.append(value)
            if cancelled:
                output.setdefault('reservation_changes', []).extend(cancelled)
                state = portfolio(ctx, c, at)
        if kind == 'EXECUTE':
            output['reservation'] = ctx['reservations'][inputs['risk_decision_id']]
        current = state['control_states']; ctx['control_states'] = current
        transitions = []
        for flag in sorted(set(previous) ^ set(current)):
            if flag == 'ACTIVE': continue
            transitions.append(dict(action='TRIGGER' if flag in current else 'CLEAR',
                                    at=at, previous_state=previous, new_state=current,
                                    reason=CONTROL_REASONS[flag], trigger_reference=digest([kind, inputs]),
                                    config_version=c.version, config_hash=c.hash))
        if kind == 'CONTROL' and inputs['action'] in ('PAUSE', 'RESUME'):
            transitions.append(dict(action=inputs['action'], at=at, previous_state=previous, new_state=current,
                reason='MANUALLY_PAUSED' if inputs['action']=='PAUSE' else 'EXPLICIT_MANUAL_RESUME',
                trigger_reference=digest([kind, inputs]), config_version=c.version, config_hash=c.hash))
        for transition in transitions:
            transition['event_id'] = digest([run['run_id'], transition])
        output.update(state_after=state, control_events=transitions)
        return json.loads(canonical(output))
