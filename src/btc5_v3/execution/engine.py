"""Causal offline IOC execution with immutable business events and balanced movements."""
from dataclasses import asdict
from decimal import Decimal,localcontext,ROUND_DOWN,ROUND_CEILING
import json

from btc5_v3.encoding import canonical,digest,timestamp
from btc5_v3.edge.numeric import CONTEXT,number
from btc5_v3.analytics.models import ResearchObservation,ResolvedOutcome,validate_run_identity
from btc5_v3.path.models import MarketPathPoint
from btc5_v3.execution.models import ExecutionConfig,ExitPolicy,ExecutionResult,SimulatedOrderIntent,SimulatedPosition
from btc5_v3.execution.depth import walk_depth

D=Decimal
Q=D('1e-18')


def book_key(s):return (s['available_at'],s['received_at'],s['sequence'],s['snapshot_id'])


def freshness(s,at,c):
    reasons=[]
    if s['available_at']>at:reasons.append('NOT_AVAILABLE')
    if not 0<=at-s['source_at']<=c.max_execution_quote_age_ms:reasons.append('STALE_SOURCE')
    if not 0<=at-s['received_at']<=c.max_execution_quote_age_ms:reasons.append('STALE_RECEIPT')
    if at>=s['expiry']:reasons.append('EXPIRED')
    if s.get('market_status')!='OPEN':reasons.append('MARKET_NOT_KNOWN_OPEN')
    status_at=s.get('market_status_at');status_available=s.get('market_status_available_at')
    if (not timestamp(status_at) or not timestamp(status_available) or status_at>status_available
            or status_available>at or not 0<=at-status_at<=c.max_market_status_age_ms):reasons.append('STATUS_STALE_OR_UNAVAILABLE')
    return reasons


def fee_amounts(fee,quantity,notional):
    return (notional*fee.rate+quantity*fee.collateral_per_share,D(0)) if fee.denomination=='COLLATERAL' else (D(0),(quantity*fee.rate).quantize(Q,rounding=ROUND_CEILING))


def validate_inputs(observation,books,outcome,experiment_id):
    if not isinstance(observation,ResearchObservation):raise TypeError('original research observation required')
    data=observation.data();p,s,e,d=(data[k] for k in ('prediction','snapshot','edge','decision'))
    if any(x is None for x in (s,e,d)):raise ValueError('complete original M1-M3 chain required')
    MarketPathPoint(canonical(s),canonical(d))
    if any(x['experiment_id']!=experiment_id for x in (p,s,e,d)):raise ValueError('cross-experiment original inputs')
    target=p['target_definition']
    if (p['market_id']!=s['market_id'] or target['expiry']!=s['expiry'] or target['rule_hash']!=s['rule_hash']
            or target['outcome_mapping']!=s['outcome_mapping'] or target['probability_semantics']!='MARKET_YES'
            or p['support_status']!='SUPPORTED'):raise ValueError('incompatible original target')
    if (e['prediction_id']!=p['prediction_id'] or e['snapshot_id']!=s['snapshot_id']
            or D(e['p_yes'])!=D(p['p_yes']) or e['edge_id']!=digest(dict(experiment_id=experiment_id,
                prediction_id=p['prediction_id'],snapshot_id=s['snapshot_id'],evaluated_at=e['evaluated_at'],config_hash=e['config_hash']))
            or d['edge_id']!=e['edge_id'] or d['prediction_id']!=p['prediction_id']
            or d['input_hash']!=digest([canonical(s),canonical(p),canonical(e)])):
        raise ValueError('original edge/decision lineage mismatch')
    if not (max(s['available_at'],p['available_at'])<=e['evaluated_at']<=d['evaluated_at']<s['expiry']):
        raise ValueError('noncausal original chain')
    parsed=[]
    for b in books:
        if not isinstance(b,MarketPathPoint):raise TypeError('validated book archive required')
        q=json.loads(b.snapshot_json)
        if any(q[k]!=s[k] for k in ('experiment_id','market_id','expiry','source','feed','rule_hash','outcome_mapping')):
            raise ValueError('cross-experiment or market contract in execution book')
        parsed.append(q)
    if len({b['snapshot_id'] for b in parsed})!=len(parsed):raise ValueError('duplicate execution book')
    if len({(b['received_at'],b['sequence']) for b in parsed})!=len(parsed):raise ValueError('ambiguous execution order')
    if outcome is not None:
        if not isinstance(outcome,ResolvedOutcome):raise TypeError('explicit resolved outcome required')
        if outcome.experiment_id!=experiment_id or outcome.market_id!=s['market_id'] or outcome.rule_hash!=s['rule_hash']:
            raise ValueError('incompatible settlement reference')
        if outcome.source!='synthetic-settlement' or outcome.settlement_version!='synthetic-settlement-v1' or outcome.resolution_at<s['expiry']:
            raise ValueError('unverified or premature settlement')
    return p,s,e,d,sorted(parsed,key=book_key)


def simulate(observation,books,outcome,config,policy,*,experiment_id,code_git,cutoff,created_at):
    validate_run_identity(experiment_id,code_git,cutoff,created_at)
    if not isinstance(config,ExecutionConfig) or not isinstance(policy,ExitPolicy):raise TypeError('explicit execution config/policy required')
    with localcontext(CONTEXT):
        return _simulate(observation,tuple(books),outcome,config,policy,experiment_id,code_git,cutoff,created_at)


def _simulate(observation,books,outcome,c,policy,experiment_id,code_git,cutoff,created_at):
    p,s,e,d,ordered=validate_inputs(observation,books,outcome,experiment_id)
    inputs=dict(original=json.loads(observation.payload_json),books=sorted((asdict(b) for b in books),key=digest),
                outcome=json.loads(outcome.to_json()) if outcome else None)
    input_hash=digest(inputs);runid=digest([experiment_id,code_git,c.hash,policy.hash,cutoff,input_hash])
    # Business identity never depends on future book/outcome archive or run cutoff.
    namespace=digest([experiment_id,code_git,d['decision_id'],c.hash,policy.hash])
    orders=[];events=[];fills=[];positions=[];exits=[];settlements=[];ledger=[];consumed={};checks=[]
    def emit(kind,at,**fields):
        event=dict(kind=kind,at=at,**fields);event['event_id']=digest([namespace,event]);events.append(event);return event['event_id']
    def movement(event,at,asset,account,counterparty,amount,reason):
        if not amount:return
        for name,value in ((account,amount),(counterparty,-amount)):
            item=dict(event_id=event,at=at,asset=asset,account=name,amount=value,reason=reason)
            item['ledger_id']=digest([namespace,item]);ledger.append(item)
    def intent(purpose,qty,at,trigger,position_id=None,attempt=0):
        delay=c.decision_to_order_latency_ms if purpose=='ENTRY' else c.exit_latency_ms
        ready=at+delay;deadline=min(ready+c.maximum_wait_for_next_book_ms,s['expiry'])
        order=SimulatedOrderIntent(digest([namespace,purpose,attempt]),experiment_id,s['market_id'],d['decision_id'],
            position_id,purpose,d['side'],qty,at,ready,deadline,trigger,c.hash,policy.hash)
        orders.append(asdict(order));emit('ORDER_INTENT',at,order_id=order.order_id,purpose=purpose,requested_shares=qty)
        if ready<=min(cutoff,s['expiry']):emit('ORDER_READY',ready,order_id=order.order_id)
        return order
    def select(order,after_key,allow_same=False):
        rejected=[]
        for b in ordered:
            key=book_key(b)
            if key<after_key or (key==after_key and not allow_same) or b['snapshot_id']==s['snapshot_id']:continue
            if b['available_at']<order.ready_at:continue
            at=b['available_at']
            if at>min(order.deadline,cutoff) or at>=s['expiry']:continue
            if b['source_at']<order.ready_at or b['received_at']<order.ready_at:
                rejected.append(dict(snapshot_id=b['snapshot_id'],at=at,reasons=['NOT_POST_LATENCY_SOURCE_OR_RECEIPT']));continue
            reasons=freshness(b,at,c)
            if reasons:
                rejected.append(dict(snapshot_id=b['snapshot_id'],at=at,reasons=reasons));continue
            checks.append(dict(order_id=order.order_id,rejected_books=rejected,selected_snapshot_id=b['snapshot_id']))
            return b
        checks.append(dict(order_id=order.order_id,rejected_books=rejected,selected_snapshot_id=None))
        if cutoff>=order.deadline:
            emit('ORDER_NO_FILL',order.deadline,order_id=order.order_id,reason='NO_CAUSAL_BOOK',unfilled_shares=order.requested_shares)
        return None
    def perform(order,b,fee):
        at=b['available_at'];isbuy=order.purpose=='ENTRY';side=order.side.lower()
        # Exit share fee is an additional inventory debit per share actually sold.
        quantity=order.requested_shares if isbuy or fee.denomination=='COLLATERAL' else (order.requested_shares/(1+fee.rate)).quantize(Q,rounding=ROUND_DOWN)
        walk=walk_depth(b[side+('_asks' if isbuy else '_bids')],quantity,direction='BUY' if isbuy else 'SELL',consumed=consumed)
        cashfee,sharefee=fee_amounts(fee,walk.filled_shares,walk.notional)
        removed=walk.filled_shares+sharefee if not isbuy else D(0)
        # Decimal division may leave a sub-precision residual; never remove more inventory than requested.
        if removed>order.requested_shares:raise ValueError('share-fee inventory overflow')
        inventory_unfilled=order.requested_shares-(walk.filled_shares if isbuy else removed)
        fillid=digest([order.order_id,b['snapshot_id'],'fill'])
        status='NO_FILL' if not walk.filled_shares else 'PARTIAL_FILL' if inventory_unfilled else 'FULL_FILL'
        event=emit('ORDER_EXECUTED',at,order_id=order.order_id,fill_id=fillid if walk.filled_shares else None,
                   status=status,unfilled_shares=inventory_unfilled,snapshot_id=b['snapshot_id'])
        if inventory_unfilled:emit('IOC_REMAINDER_CANCELLED',at,order_id=order.order_id,shares=inventory_unfilled)
        if not walk.filled_shares:return None
        best=number(b[side+('_asks' if isbuy else '_bids')][0]['price']);opposite=number(b[side+('_bids' if isbuy else '_asks')][0]['price'])
        value=dict(fill_id=fillid,order_id=order.order_id,position_id=order.position_id,snapshot_id=b['snapshot_id'],
            at=at,purpose=order.purpose,side=order.side,status=status,requested_shares=order.requested_shares,
            filled_shares_gross=walk.filled_shares,unfilled_shares=inventory_unfilled,
            inventory_removed=removed,net_acquired_shares=walk.filled_shares-sharefee if isbuy else D(0),
            notional=walk.notional,vwap=walk.vwap,fee_collateral=cashfee,fee_shares=sharefee,
            fee_version=fee.version,fee_denomination=fee.denomination,legs=walk.legs,
            execution_best_ask=best if isbuy else opposite,execution_best_bid=opposite if isbuy else best,
            spread_impact_per_traded_share=abs(best-opposite)/2,
            depth_impact_per_traded_share=walk.vwap-best if isbuy else best-walk.vwap,
            slippage_vs_decision_ask=walk.vwap-number(s[side+'_asks'][0]['price']) if isbuy else None,
            artificial_latency_cost_charged=D(0))
        fills.append(value)
        if isbuy:
            movement(event,at,'COLLATERAL','CASH','MARKET',-walk.notional,'ENTRY_NOTIONAL')
            movement(event,at,order.side,'INVENTORY','MARKET',walk.filled_shares,'ENTRY_SHARES')
            movement(event,at,order.side,'INVENTORY','FEE_SHARES',-sharefee,'ENTRY_SHARE_FEE')
        else:
            movement(event,at,'COLLATERAL','CASH','MARKET',walk.notional,'EXIT_NOTIONAL')
            movement(event,at,order.side,'INVENTORY','MARKET',-walk.filled_shares,'EXIT_SHARES')
            movement(event,at,order.side,'INVENTORY','FEE_SHARES',-sharefee,'EXIT_SHARE_FEE')
        movement(event,at,'COLLATERAL','CASH','FEES',-cashfee,order.purpose+'_COLLATERAL_FEE')
        return value

    status='M3_REJECTED';entry=None;pos=None;remaining=D(0);exit_removed=D(0);settled=D(0);payout=None
    approved=d['final_action'] in ('BUY_YES','BUY_NO') and not d['all_reasons'] and d['final_action']==e['candidate_action']
    if approved and (d['side'] not in ('YES','NO') or d['final_action']!='BUY_'+d['side']):raise ValueError('invalid approved side')
    if approved and (not e[d['side'].lower()] or not e[d['side'].lower()]['eligible']
                     or d['side']!=e['preferred_side'] or D(d['requested_shares'])!=D(e['requested_shares'])):
        raise ValueError('approved size/side inconsistent with original edge')
    requested=number(c.requested_shares if c.requested_shares is not None else (d['requested_shares'] or 0),minimum=0)
    if approved and requested>number(d['requested_shares']):status='SIZE_NOT_AUTHORIZED_BY_M3'
    elif approved and d['evaluated_at']>cutoff:status='DECISION_NOT_YET_AVAILABLE'
    elif approved:
        if requested<=0:raise ValueError('positive approved size required')
        order=intent('ENTRY',requested,d['evaluated_at'],s['snapshot_id'])
        b=select(order,book_key(s))
        if b is None:status='NO_FILL' if cutoff>=order.deadline else 'PENDING_CAUSAL_BOOK'
        else:
            entry=perform(order,b,c.entry_fee)
            status=entry['status'] if entry else 'NO_FILL'
            if entry:
                remaining=entry['net_acquired_shares']
                pos=SimulatedPosition(digest([order.order_id,'position']),experiment_id,s['market_id'],d['side'],
                    entry['filled_shares_gross'],remaining,entry['vwap'],entry['notional']+entry['fee_collateral'],
                    entry['fee_collateral'],entry['fee_shares'],entry['at'],order.order_id,entry['fill_id'])
                positions.append(asdict(pos));cursor=book_key(b);next_after=entry['at'];attempts=0
                emit('POSITION_OPENED',entry['at'],position_id=pos.position_id,fill_id=entry['fill_id'],net_shares=remaining)
                while remaining>0 and policy.kind!='HOLD' and attempts<c.max_exit_attempts:
                    trigger=None;trigger_at=None;triggerbid=None
                    if policy.kind=='FIXED_TTE':
                        if attempts:break
                        target=s['expiry']-policy.tte_ms
                        if target<pos.opened_at or target>cutoff:break
                        trigger_at=target;trigger=s['snapshot_id'];after=cursor
                    else:
                        for q in ordered:
                            if book_key(q)<=cursor or q['available_at']<next_after or q['available_at']>cutoff or q['available_at']>=s['expiry']:continue
                            bid=number(q[d['side'].lower()+'_bids'][0]['price'])
                            if bid-pos.entry_vwap<policy.rebound:continue
                            why=freshness(q,q['available_at'],c)
                            if why:
                                emit('TRIGGER_QUOTE_REJECTED',q['available_at'],snapshot_id=q['snapshot_id'],reasons=why)
                                cursor=book_key(q);continue
                            trigger_at=q['available_at'];trigger=q['snapshot_id'];triggerbid=bid;after=book_key(q);break
                        if trigger is None:break
                    attempts+=1
                    trigger_id=emit('EXIT_TRIGGER',trigger_at,position_id=pos.position_id,kind_policy=policy.kind,
                                    trigger_snapshot_id=trigger,reference_entry_vwap=pos.entry_vwap,trigger_bid=triggerbid,attempt=attempts)
                    sell=intent('EXIT',remaining,trigger_at,trigger,pos.position_id,attempts)
                    allow=policy.kind=='BID_REBOUND' and c.exit_latency_ms==0 and c.allow_same_book_zero_exit_latency
                    q=select(sell,after,allow_same=allow)
                    fill=perform(sell,q,c.exit_fee) if q else None
                    at=q['available_at'] if q else sell.deadline
                    if fill:
                        remaining-=fill['inventory_removed'];exit_removed+=fill['inventory_removed']
                    state='NO_EXIT_FILL' if q is not None or cutoff>=sell.deadline else 'PENDING_EXIT_BOOK'
                    if fill:state='FULL_EXIT' if remaining==0 else 'PARTIAL_EXIT'
                    exits.append(dict(exit_id=digest([sell.order_id,'attempt']),order_id=sell.order_id,trigger_event_id=trigger_id,
                        trigger_at=trigger_at,ready_at=sell.ready_at,status=state,fill_id=fill['fill_id'] if fill else None,
                        snapshot_id=q['snapshot_id'] if q else None,remaining_shares=remaining,
                        trigger_bid=triggerbid,execution_bid=number(q[d['side'].lower()+'_bids'][0]['price']) if q else None,
                        rebound_survived_latency=(number(q[d['side'].lower()+'_bids'][0]['price'])-pos.entry_vwap>=policy.rebound)
                            if q and policy.kind=='BID_REBOUND' else None,
                        sufficient_depth=bool(fill and fill['status']=='FULL_FILL')))
                    if at>cutoff:break
                    if q:cursor=book_key(q)
                    else:cursor=after
                    next_after=at+1
                if outcome and outcome.available_at<=cutoff:
                    payout=outcome.yes_payout if d['side']=='YES' else 1-outcome.yes_payout
                    if remaining:
                        cashfee,sharefee=fee_amounts(c.settlement_fee,remaining,remaining*payout)
                        proceeds=(remaining-sharefee)*payout
                        settled=remaining
                        settlement_id=digest([pos.position_id,outcome.outcome_id,'settlement'])
                        event=emit('POSITION_SETTLED',outcome.available_at,settlement_id=settlement_id,position_id=pos.position_id,outcome_id=outcome.outcome_id)
                        settlements.append(dict(settlement_id=settlement_id,position_id=pos.position_id,outcome_id=outcome.outcome_id,
                            at=outcome.available_at,shares=remaining,yes_payout=outcome.yes_payout,side_payout=payout,
                            gross_proceeds=remaining*payout,proceeds_after_share_fee=proceeds,fee_collateral=cashfee,fee_shares=sharefee,
                            net_proceeds=proceeds-cashfee,fee_version=c.settlement_fee.version,fee_denomination=c.settlement_fee.denomination))
                        movement(event,outcome.available_at,'COLLATERAL','CASH','SETTLEMENT',proceeds,'SETTLEMENT_PROCEEDS')
                        movement(event,outcome.available_at,'COLLATERAL','CASH','FEES',-cashfee,'SETTLEMENT_COLLATERAL_FEE')
                        movement(event,outcome.available_at,d['side'],'INVENTORY','REDEEMED',-(remaining-sharefee),'SETTLED_SHARES')
                        movement(event,outcome.available_at,d['side'],'INVENTORY','FEE_SHARES',-sharefee,'SETTLEMENT_SHARE_FEE')
                        remaining=D(0)

    cash=sum((x['amount'] for x in ledger if x['asset']=='COLLATERAL' and x['account']=='CASH'),D(0))
    fee_cash=sum((f['fee_collateral'] for f in fills),D(0))+sum((x['fee_collateral'] for x in settlements),D(0))
    exit_fills=[f for f in fills if f['purpose']=='EXIT']
    if pos:
        assert pos.filled_shares_net==exit_removed+settled+remaining
        inventory=sum((x['amount'] for x in ledger if x['asset']==pos.side and x['account']=='INVENTORY'),D(0))
        assert inventory==remaining
    for asset in {x['asset'] for x in ledger}:assert sum((x['amount'] for x in ledger if x['asset']==asset),D(0))==0
    completed=bool(pos and remaining==0) or status=='NO_FILL'
    hold=D(0) if status=='NO_FILL' else None
    if pos and payout is not None:
        hf,hs=fee_amounts(c.settlement_fee,pos.filled_shares_net,pos.filled_shares_net*payout)
        hold=(pos.filled_shares_net-hs)*payout-hf-pos.collateral_spent
    gross= cash+fee_cash if completed else None
    observed_grid=[]
    if pos:
        from btc5_v3.execution.models import REBOUND_GRID
        available=[b for b in ordered if pos.opened_at<b['available_at']<=cutoff and b['available_at']<s['expiry']]
        for threshold in REBOUND_GRID:
            hits=[b for b in available if number(b[pos.side.lower()+'_bids'][0]['price'])-pos.entry_vwap>=threshold]
            observed_grid.append(dict(threshold=threshold,observed_bid_rebound=bool(hits),observation_count=len(hits),
                fresh_observation_count=sum(not freshness(b,b['available_at'],c) for b in hits)))
    report=dict(mode='OFFLINE_SIMULATED_EXECUTION_ONLY',decision_id=d['decision_id'],market_id=s['market_id'],side=d['side'],
        entry_status=status,config=asdict(c),policy=asdict(policy),orders=orders,order_events=events,fills=fills,
        positions=positions,exit_attempts=exits,settlements=settlements,ledger_entries=ledger,book_selection_audit=checks,
        accounting=dict(gross_entry_cost=entry['notional'] if entry else D(0),
            entry_fee=dict(collateral=entry['fee_collateral'] if entry else D(0),shares=entry['fee_shares'] if entry else D(0)),
            gross_exit_proceeds=sum((f['notional'] for f in exit_fills),D(0)),
            exit_fee=dict(collateral=sum((f['fee_collateral'] for f in exit_fills),D(0)),shares=sum((f['fee_shares'] for f in exit_fills),D(0))),
            settlement_proceeds=sum((x['net_proceeds'] for x in settlements),D(0)),
            gross_pnl=gross,gross_pnl_basis='ACTUAL_QUANTITY_FLOWS_AFTER_SHARE_FEES_BEFORE_COLLATERAL_FEES',
            total_fees=dict(collateral=fee_cash,entry_shares=entry['fee_shares'] if entry else D(0),
                exit_shares=sum((f['fee_shares'] for f in exit_fills),D(0)),settlement_shares=sum((x['fee_shares'] for x in settlements),D(0))),
            net_simulated_pnl=cash if completed else None,realized_cash_flow=cash,
            hold_to_settlement_pnl=hold,exit_advantage=cash-hold if completed and hold is not None else None,
            initial_net_shares=pos.filled_shares_net if pos else D(0),exited_inventory_shares=exit_removed,
            settled_inventory_shares=settled,remaining_shares=remaining,completed=completed,
            ledger_balanced=True,share_conservation=True),
        execution_diagnostics=dict(decision_mid=(number(s[d['side'].lower()+'_bids'][0]['price'])+number(s[d['side'].lower()+'_asks'][0]['price']))/2 if d['side'] else None,
            decision_ask=number(s[d['side'].lower()+'_asks'][0]['price']) if d['side'] else None,
            m2_expected_vwap=e[d['side'].lower()]['depth_vwap'] if d['side'] and e[d['side'].lower()] else None,
            entry_vwap=entry['vwap'] if entry else None,latency_impact=None,latency_impact_status='REQUIRES_PAIRED_ZERO_LATENCY_COUNTERFACTUAL',
            artificial_latency_cost_charged=D(0),fee_impact_collateral=fee_cash,
            share_fee_value_at_event_price=sum((f['fee_shares']*f['vwap'] for f in fills),D(0))
                +sum((x['fee_shares']*x['side_payout'] for x in settlements),D(0)),
            share_fee_value_basis='DIAGNOSTIC_MARK_AT_FILL_VWAP_OR_PAYOUT_NOT_ADDITIONAL_CASH_CHARGE'),
        observed_rebound_grid=observed_grid,
        limitations=['SYNTHETIC_SETTLEMENT_AND_FEE_ASSUMPTIONS','NO_REAL_ACCOUNT_OR_ORDER','NO_QUEUE_OR_HIDDEN_LIQUIDITY',
            'RECORDED_DISPLAYED_DEPTH_NOT_FILL_GUARANTEE','INDEPENDENT_COUNTERFACTUAL_RUN_NOT_PORTFOLIO',
            'NO_OPTIMIZATION_OR_RECOMMENDED_POLICY','NO_M6_RISK_PERMISSION','NO_ADDED_ARTIFICIAL_LATENCY_COST'])
    return ExecutionResult(runid,experiment_id,code_git,cutoff,created_at,c.hash,policy.hash,input_hash,canonical(report))
