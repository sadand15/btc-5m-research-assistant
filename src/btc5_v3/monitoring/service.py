"""Build causal observation views from stored evidence; never execute domain actions."""
from decimal import Decimal,localcontext
from collections import Counter
import json
import sqlite3

from btc5_v3.encoding import canonical,digest,timestamp
from btc5_v3.edge.numeric import CONTEXT
from btc5_v3.monitoring.models import MonitoringView,ViewFilter
from btc5_v3.monitoring.queries import ReadOnlyQueries
from btc5_v3.monitoring.audit import verify,amount,reconcile
from btc5_v3.monitoring.diagnostics import diagnostic,redact
from btc5_v3.monitoring.provenance import provenance,viewer_repository

D=Decimal
RESERVATION_STATES={'ACTIVE','PARTIALLY_CONSUMED','CONSUMED','RELEASED','EXPIRED'}
CONTROL_STATES={'ACTIVE','PAUSED_DATA','PAUSED_PROVIDER','PAUSED_DAILY_LOSS','PAUSED_DRAWDOWN','PAUSED_LOSS_STREAK','MANUALLY_PAUSED'}
RESET={
 'PAUSED_DAILY_LOSS':('Daily Reset Pause','Next UTC day, only when recorded by M6'),
 'PAUSED_DRAWDOWN':('Persistent Latch','No reset in this M6 run'),
 'PAUSED_LOSS_STREAK':('Persistent Latch','No reset in this M6 run'),
 'PAUSED_DATA':('Transient Pause','Explicit fresh valid archived health evidence'),
 'PAUSED_PROVIDER':('Transient Pause','Explicit healthy archived provider evidence'),
 'MANUALLY_PAUSED':('Manual Pause','Explicit M6 RESUME; no dashboard action')}
GUARD_REASONS={'DAILY_LOSS_LIMIT':'PAUSED_DAILY_LOSS','MAX_DRAWDOWN_REACHED':'PAUSED_DRAWDOWN',
 'CONSECUTIVE_LOSS_LIMIT':'PAUSED_LOSS_STREAK','DATA_KILL_SWITCH':'PAUSED_DATA',
 'PROVIDER_KILL_SWITCH':'PAUSED_PROVIDER','MANUALLY_PAUSED':'MANUALLY_PAUSED'}


def _match(row,f):
    at=row.get('timestamp')
    if f.start_at is not None and (at is None or at<f.start_at):return False
    if f.end_at is not None and (at is None or at>f.end_at):return False
    for key in ('market_id','candidate_id','permission','reservation_id','execution_id','position_status','health_state','risk_guard','category'):
        wanted=getattr(f,key)
        if wanted and row.get(key)!=wanted:return False
    if f.reason and f.reason not in row.get('all_reasons',[]) and f.reason!=row.get('reason'):return False
    return True


def _health(originals,market,health,health_event,health_recorded_at,state,cfg,as_of,diagnostics):
    result=[]
    def add(component,status,at,source,reason):
        known=timestamp(at) and at<=as_of
        result.append(dict(component=component,status=status,timestamp=at if known else None,
                           age_ms=as_of-at if known else None,source=source,reason=reason,health_state=status))
    last=state.get('at')
    add('database','DEGRADED' if diagnostics else 'HEALTHY',last,'read-only SQLite archive',
        'Archive integrity issue' if diagnostics else 'Selected archive readable; not a live service probe')
    add('data completeness','UNKNOWN',last,'explicit archive','Whole-collector completeness is not recorded')
    age=as_of-last if timestamp(last) else None
    flags=state.get('control_states',[])
    status='UNKNOWN' if not state else 'PAUSED' if state.get('paused') else 'STALE' if age>cfg['max_portfolio_age_ms'] else 'HEALTHY'
    add('risk engine',status,last,'M6 recorded state','; '.join(flags) or 'No recorded state')
    p=originals[-1]['prediction'] if originals else {}
    at=p.get('available_at')
    status='UNKNOWN' if not timestamp(at) else 'STALE' if as_of-at>cfg.get('max_portfolio_age_ms',0) else 'HEALTHY' if p.get('support_status')=='SUPPORTED' else 'DEGRADED'
    add('prediction source',status,at,p.get('model_version','UNKNOWN'),'Archived support status and observation age only')
    at=market.get('source_at') if market else None
    status='UNKNOWN' if not timestamp(at) or at>as_of else 'STALE' if as_of-at>cfg.get('max_feed_age_ms',0) else 'HEALTHY'
    add('market source',status,at,market.get('source','UNKNOWN') if market else 'UNKNOWN','Archived source age, not live connection health')
    for name,gate in (('spread','SPREAD'),('depth','LIQUIDITY')):
        d=originals[-1]['decision'] if originals else {}
        evidence=next((x for x in d.get('gate_results',[]) if x.get('gate')==gate),{})
        status={'PASS':'HEALTHY','REJECT':'DEGRADED','NOT_APPLICABLE':'UNKNOWN'}.get(evidence.get('status'),'UNKNOWN')
        if timestamp(d.get('evaluated_at')) and as_of-d['evaluated_at']>cfg.get('max_feed_age_ms',0):status='STALE'
        add(name,status,d.get('evaluated_at'),'M3 '+gate,'; '.join(evidence.get('reasons',[])) or 'Recorded gate only')
    try:
        if health is None:raise ValueError('missing evidence')
        at=health['available_at'];source=health['source_at'];heartbeat=health['heartbeat_at']
        if (not timestamp(at) or at>as_of or not timestamp(health_recorded_at) or at>health_recorded_at
                or any(x is not None and (not timestamp(x) or x>at) for x in (source,heartbeat))
                or type(health['provider_healthy']) is not bool or type(health['source_matches']) is not bool
                or type(health['validation_failures']) is not int or health['validation_failures']<0):
            raise ValueError('malformed health')
        stale=source is None or heartbeat is None or as_of-source>cfg['max_feed_age_ms'] or as_of-heartbeat>cfg['max_heartbeat_age_ms']
        data_status='STALE' if stale else 'DEGRADED' if not health['source_matches'] or health['validation_failures']>=cfg['validation_failure_burst_limit'] else 'HEALTHY'
        provider_status='STALE' if as_of-at>cfg['max_heartbeat_age_ms'] else 'HEALTHY' if health['provider_healthy'] else 'DEGRADED'
        add('data health',data_status,at,health_event or 'UNKNOWN','Existing typed health evidence only')
        add('provider',provider_status,at,health_event or 'UNKNOWN','No network/account probe')
    except (ValueError,TypeError,KeyError):
        add('data health','UNKNOWN',None,'UNKNOWN','Missing or malformed health evidence')
        add('provider','UNKNOWN',None,'UNKNOWN','No trustworthy provider evidence')
        if health is not None:diagnostics.append(diagnostic('MALFORMED_HEALTH','risk_events',health_event))
    return result


class MonitoringService:
    def __init__(self,project_root,database,*,max_events=1000):
        self.queries=ReadOnlyQueries(project_root,database,max_events=max_events)

    def catalog(self):
        try:return redact(self.queries.catalog())
        except (OSError,ValueError,sqlite3.Error):return []

    def latest_at(self,run_id):
        try:return self.queries.latest_at(run_id)
        except (OSError,ValueError,sqlite3.Error):return None

    def view(self,run_id,filters,*,viewer=None):
        if not isinstance(filters,ViewFilter):raise TypeError('explicit view filter required')
        viewer=viewer if viewer is not None else viewer_repository(self.queries.root)
        try:
            bundle=self.queries.fetch(run_id,filters.as_of)
            with localcontext(CONTEXT):return self._build(bundle,run_id,filters,viewer)
        except (OSError,sqlite3.Error,ValueError,TypeError,KeyError,ArithmeticError,AttributeError,IndexError,RecursionError):
            return MonitoringView.create(dict(mode='RESEARCH MODE / READ ONLY',evidence_mode='UNKNOWN',
                as_of=filters.as_of,overview=dict(overall_health='UNKNOWN',reconciliation='INCOMPLETE',capital=None),
                diagnostics=[diagnostic('UNAVAILABLE','read-only archive',run_id)],
                health=[],risk=[],permissions=[],reservations=[],reservation_history=[],positions=[],executions=[],ledger=[],timeline=[],
                provenance=dict(m7_version='monitoring-v1',viewer_repository=viewer),pagination={}))

    def _build(self,bundle,run_id,f,viewer):
        run,metadata,events,diags=verify(bundle,run_id,f.as_of)
        cfg=run.get('config',{});permissions={};originals=[];original_by_id={};revisions=[];reservations={};executions={}
        controls=[];timeline=[];seen=set();market={};health=None;health_event=None;state={};event_ids={}
        def emit(category,at,source_id,source,detail,seq,available_at,**links):
            if not timestamp(at) or at>f.as_of or available_at>f.as_of:raise ValueError('noncausal display event')
            key=(category,source_id)
            if key in seen:return
            seen.add(key);timeline.append(dict(timestamp=at,available_at=available_at,sequence=seq,category=category,
                source_id=source_id,source=source,details=detail,**links))
        for event in events:
            at=event['at'];seq=event['sequence'];identity=event['id'];kind=event['kind']
            i=event['inputs'];o=event['output'];event_ids[identity]=at
            try:
                candidate_id=i.get('risk_decision_id')
                if kind=='EVALUATE':
                    original=i['original'];d=original['decision'];p=original['prediction'];s=original['snapshot'];e=original['edge'];r=o['risk_decision']
                    if (any(x['experiment_id']!=run['experiment_id'] for x in (d,p,s,e,r))
                        or d['decision_id']!=r['decision_id'] or r['risk_decision_id']!=digest([run_id,d['decision_id']])
                        or d['input_hash']!=digest([canonical(s),canonical(p),canonical(e)])
                        or not all(timestamp(t) and t<=at for t in (s['available_at'],p['available_at'],e['evaluated_at'],d['evaluated_at']))
                        or e['prediction_id']!=p['prediction_id'] or e['snapshot_id']!=s['snapshot_id']
                        or d['edge_id']!=e['edge_id'] or d['prediction_id']!=p['prediction_id']
                        or r['risk_config_hash']!=run['config_hash'] or r['portfolio_state_id']!=digest(o['state_before'])):
                        raise LookupError('original lineage')
                    if r['action'] not in ('APPROVE','REDUCE','REJECT'):
                        diags.append(diagnostic('UNKNOWN_ENUM','risk_decisions',r['risk_decision_id'],at=at));break
                    for name in ('requested_shares','approved_shares','requested_notional','approved_notional'):amount(r[name])
                    candidate_id=r['risk_decision_id'];res=o.get('reservation')
                    permission=dict(timestamp=at,market_id=s['market_id'],candidate_id=candidate_id,
                        source_m3_decision_id=d['decision_id'],prediction_id=p['prediction_id'],edge_id=e['edge_id'],side=d['side'],
                        requested_size=r['requested_shares'],approved_size=r['approved_shares'],
                        requested_capital=r['requested_notional'],approved_capital=r['approved_notional'],
                        permission=r['action'],reason=r['primary_reason'],all_reasons=r['all_reasons'],
                        reservation_id=res['reservation_id'] if res else None,risk_config_hash=r['risk_config_hash'],
                        source_event_id=identity,m3_evidence=d,source_prediction=p,source_snapshot=s,source_edge=e,
                        state_before=o['state_before'],execution_config=i['execution_config'],policy=i['policy'])
                    permissions[candidate_id]=permission;originals.append(original);original_by_id[candidate_id]=original;market=s
                    links={k:permission[k] for k in ('market_id','candidate_id','permission','reservation_id','reason','all_reasons')}
                    emit('prediction',p['available_at'],p['prediction_id'],'M2 archive',p,seq,at,**links)
                    emit('candidate',d['evaluated_at'],d['decision_id'],'M3 archive',d,seq,at,**links)
                    emit('permission',at,candidate_id,'risk_decisions',r,seq,at,**links)
                if i.get('health') is not None:
                    health=i['health'];health_event=identity
                    # Do not expose raw/future timestamp content in this event.
                    emit('health',at,identity,'risk_events','Archived health evidence received',seq,at)
                changed=[]
                if kind!='EXECUTE' and o.get('reservation'):changed.append(o['reservation'])
                changed+=o.get('reservation_changes',[])
                for revision in changed:
                    permission=next((x for x in permissions.values() if x['source_m3_decision_id']==revision['decision_id']),None)
                    if permission is None:raise LookupError('reservation permission')
                    if revision['status'] not in RESERVATION_STATES:
                        diags.append(diagnostic('UNKNOWN_ENUM','capital_reservations',revision['reservation_id'],at=at));raise ValueError('status')
                    for k in ('reserved_collateral','consumed_collateral','released_collateral','remaining_collateral'):amount(revision[k])
                    if amount(revision['reserved_collateral'])!=sum((amount(revision[k]) for k in ('consumed_collateral','released_collateral','remaining_collateral')),D(0)):
                        diags.append(diagnostic('MISMATCH','capital_reservations',revision['reservation_id'],at=at))
                    n=1+sum(x['reservation_id']==revision['reservation_id'] for x in revisions)
                    item=dict(revision,timestamp=at,revision=n,source_event_id=identity,market_id=permission['market_id'],
                        candidate_id=permission['candidate_id'],permission=permission['permission'],requested_capital=permission['requested_capital'])
                    revisions.append(item);reservations[item['reservation_id']]=item
                    emit('reservation',at,digest([identity,item['reservation_id'],n]),'capital_reservations',item,seq,at,
                         candidate_id=item['candidate_id'],market_id=item['market_id'],reservation_id=item['reservation_id'])
                if kind=='EXECUTE':
                    if candidate_id not in permissions:raise LookupError('execution permission')
                    perm=permissions[candidate_id];report=o['execution'];eid=o['execution_id']
                    if report['decision_id']!=perm['source_m3_decision_id'] or report['market_id']!=perm['market_id']:
                        raise LookupError('execution original')
                    expected_config=dict(perm['execution_config'],requested_shares=perm['approved_size'])
                    archived_input=dict(original=original_by_id[candidate_id],books=i['books'],outcome=i['outcome'])
                    expected_id=digest([run['experiment_id'],run['code_git'],digest(expected_config),digest(perm['policy']),at,digest(archived_input)])
                    if (perm['permission']=='REJECT' or report['config']!=expected_config or report['policy']!=perm['policy']
                            or report['side']!=perm['side'] or eid!=expected_id
                            or any(amount(x['requested_shares'])!=amount(perm['approved_size']) for x in report['orders'] if x['purpose']=='ENTRY')):
                        raise LookupError('execution permission binding')
                    for field,key in (('orders','order_id'),('order_events','event_id'),('fills','fill_id'),('positions','position_id'),('settlements','settlement_id'),('ledger_entries','ledger_id')):
                        for x in report[field]:
                            t=x.get('at',x.get('opened_at',x.get('created_at')))
                            if not timestamp(t) or t>at:raise ValueError('future execution result')
                    result,cash,basis=reconcile(report)
                    if result!='RECONCILED':diags.append(diagnostic(result,'M5 ledger',eid,at=at))
                    old=executions.get(candidate_id)
                    if old:
                        for field,key in (('ledger_entries','ledger_id'),('fills','fill_id'),('positions','position_id'),('settlements','settlement_id')):
                            current={x[key]:x for x in report[field]}
                            if any(current.get(x[key])!=x for x in old['evidence'][field]):raise ValueError('changed execution prefix')
                    entry=next((x for x in report['fills'] if x['purpose']=='ENTRY'),None)
                    exit_fills=[x for x in report['fills'] if x['purpose']=='EXIT']
                    execution=dict(timestamp=at,execution_id=eid,candidate_id=candidate_id,market_id=perm['market_id'],
                        reservation_id=perm['reservation_id'],permission=perm['permission'],candidate_size=perm['requested_size'],
                        approved_size=perm['approved_size'],attempted_size=report['orders'][0]['requested_shares'] if report['orders'] else None,
                        filled_size=entry['filled_shares_gross'] if entry else None,
                        unfilled_size=entry['unfilled_shares'] if entry else None,entry_price=entry['vwap'] if entry else None,
                        exit_prices=[x['vwap'] for x in exit_fills],entry_fees=report['accounting']['entry_fee'],
                        exit_fees=report['accounting']['exit_fee'],total_fees=report['accounting']['total_fees'],
                        latency_ms=report['config']['decision_to_order_latency_ms'],exit_latency_ms=report['config']['exit_latency_ms'],
                        fill_status=report['entry_status'],policy=report['policy'],settlement_state='SETTLED' if report['settlements'] else 'NOT RECORDED',
                        reconciliation=result,source_event_id=identity,evidence=report,cash_flow=cash,remaining_cost_basis=basis,
                        execution_config_hash=digest(report['config']))
                    executions[candidate_id]=execution
                    links={k:execution[k] for k in ('market_id','candidate_id','execution_id','reservation_id','permission')}
                    for x in report['order_events']:emit('execution',x['at'],x['event_id'],'M5 order_events',x,seq,at,**links)
                    for x in report['positions']:emit('position',x['opened_at'],x['position_id'],'M5 positions',x,seq,at,**links)
                    for x in report['settlements']:emit('settlement',x['at'],x['settlement_id'],'M5 settlements',x,seq,at,**links)
                    for x in report['ledger_entries']:emit('ledger',x['at'],x['ledger_id'],'M5 ledger',x,seq,at,**links)
                    emit('reconciliation',at,identity,'M6 archive',dict(status=result,state=o['state_after']),seq,at,**links)
                    # Only already available snapshot metadata, never the supplied future outcome.
                    for archived in i['books']:
                        s=json.loads(archived['snapshot_json'])
                        if s['available_at']<=at and s['source_at']<=at and s['available_at']>=market.get('available_at',0):market=s
                for control in o['control_events']:
                    if control['at']>at:raise ValueError('future control')
                    controls.append(control)
                    emit('risk',control['at'],control['event_id'],'risk_events',control,seq,at,
                         risk_guard=GUARD_REASONS.get(control['reason'],control['reason']),reason=control['reason'])
                state=o['state_after']
                if any(x not in CONTROL_STATES for x in state['control_states']):
                    diags.append(diagnostic('UNKNOWN_ENUM','portfolio_snapshots',identity,at=at));break
                for name in ('cash','available_cash','reserved_cash','open_exposure','pending_exposure','equity','daily_pnl','daily_maximum_loss','drawdown'):
                    amount(state[name])
            except LookupError:
                diags.append(diagnostic('INVALID_REFERENCE','risk_events',identity,at=at));break
            except (ValueError,TypeError,KeyError,OverflowError,RecursionError):
                diags.append(diagnostic('CORRUPTED','risk_events',identity,at=at));break
        ledger=[];positions=[];ledger_ids=set();total_cash=D(0);total_basis=D(0)
        try:
            for candidate_id,execution in executions.items():
                report=execution['evidence'];perm=permissions[candidate_id];links={k:execution[k] for k in ('market_id','candidate_id','execution_id','reservation_id','permission')}
                total_cash+=execution['cash_flow']
                if execution['remaining_cost_basis'] is None:raise ValueError('unknown basis')
                total_basis+=execution['remaining_cost_basis']
                for x in report['ledger_entries']:
                    if x['ledger_id'] in ledger_ids:raise ValueError('duplicate ledger')
                    ledger_ids.add(x['ledger_id']);ledger.append(dict(x,**links,timestamp=x['at'],source='M5 ledger',source_id=x['ledger_id']))
                for opening in report['positions']:
                    a=report['accounting'];remaining=amount(a['remaining_shares'])
                    status='SETTLED' if report['settlements'] else 'EXITED' if a['completed'] else 'PARTIAL' if amount(a['exited_inventory_shares']) or execution['fill_status']=='PARTIAL_FILL' else 'OPEN'
                    positions.append(dict(**links,position_id=opening['position_id'],timestamp=execution['timestamp'],entry_timestamp=opening['opened_at'],
                        side=opening['side'],shares=a['remaining_shares'],initial_net_shares=a['initial_net_shares'],
                        acquisition_cost=opening['collateral_spent'],remaining_cost_basis=execution['remaining_cost_basis'],
                        position_status=status,source_event_id=execution['source_event_id']))
            for perm in permissions.values():
                res=reservations.get(perm['reservation_id'])
                if res and res['status']=='ACTIVE' and (perm['candidate_id'] not in executions or not executions[perm['candidate_id']]['evidence']['positions']):
                    positions.append(dict(timestamp=res['timestamp'],market_id=perm['market_id'],candidate_id=perm['candidate_id'],
                        reservation_id=perm['reservation_id'],permission=perm['permission'],position_id=None,execution_id=None,
                        side=perm['side'],shares=None,remaining_cost_basis=None,position_status='PENDING',reason='Permission pending; not a filled position'))
            if state:
                reserved=sum((amount(r['remaining_collateral']) for r in reservations.values()),D(0))
                if (amount(state['cash'])!=amount(cfg['starting_capital'])+total_cash or amount(state['reserved_cash'])!=reserved
                    or amount(state['available_cash'])!=amount(state['cash'])-reserved or amount(state['open_exposure'])!=total_basis
                    or amount(state['equity'])!=amount(state['cash'])+total_basis or amount(state['pending_exposure'])!=reserved):
                    diags.append(diagnostic('MISMATCH','portfolio_snapshots',run_id,at=state['at']))
            balance=amount(cfg['starting_capital']) if cfg else None
            for row in sorted(ledger,key=lambda x:(x['timestamp'],x['candidate_id'],x['ledger_id'])):
                if row['account']=='CASH' and row['asset']=='COLLATERAL':balance+=amount(row['amount'])
                row['resulting_cash_balance']=balance
                row['cash_delta']=row['amount'] if row['account']=='CASH' and row['asset']=='COLLATERAL' else None
                row['shares_delta']=row['amount'] if row['account']=='INVENTORY' else None
        except (ValueError,TypeError,KeyError):diags.append(diagnostic('MISMATCH','portfolio audit',run_id))
        valid=bool(state) and not diags
        health_rows=_health(originals,market,health,health_event,event_ids.get(health_event),state if valid else {},cfg,f.as_of,diags)
        risk=[]
        for flag,(category,reset) in RESET.items():
            triggers=[x for x in controls if x['action']=='TRIGGER' and GUARD_REASONS.get(x['reason'])==flag]
            source=triggers[-1] if triggers else {}
            keys={'PAUSED_DAILY_LOSS':('daily_maximum_loss','max_daily_simulated_loss'),
                  'PAUSED_DRAWDOWN':('drawdown','max_drawdown'),'PAUSED_LOSS_STREAK':('consecutive_losses','max_consecutive_losses')}
            value,limit=keys.get(flag,('',''))
            active=valid and flag in state.get('control_states',[])
            risk.append(dict(risk_guard=flag,category=category,status=('LATCHED' if category=='Persistent Latch' else 'PAUSED') if active else 'INACTIVE' if valid else 'UNKNOWN',
                current_value=state.get(value) if valid else None,threshold=cfg.get(limit),triggered_at=source.get('at') if active else None,
                timestamp=state.get('at'),source_event_id=source.get('event_id') if active else None,
                evidence_reference=source.get('trigger_reference') if active else None,reset_semantics=reset))
        status='CORRUPTED' if any(x['type'] in ('CORRUPTED','INVALID_REFERENCE','UNKNOWN_ENUM') for x in diags) else 'MISMATCH' if any(x['type']=='MISMATCH' for x in diags) else 'INCOMPLETE' if not valid else 'RECONCILED'
        overall='DEGRADED' if diags else 'PAUSED' if state.get('paused') else 'STALE' if any(x['status']=='STALE' for x in health_rows) else 'UNKNOWN' if any(x['status']=='UNKNOWN' and x['component']!='data completeness' for x in health_rows) else 'HEALTHY'
        p=provenance(run,metadata,originals,bundle['schema'],f.as_of,viewer)
        p['m5_versions']=sorted({x['execution_config']['version'] for x in permissions.values()}) or ['UNKNOWN']
        p['execution_config_hashes']=sorted({x['execution_config_hash'] for x in executions.values()})
        p['evidence_mode']='SYNTHETIC' if run else 'UNKNOWN'
        overview=dict(overall_health=overall,evidence_mode=p['evidence_mode'],last_known_event_at=state.get('at'),
            archive_integrity='VERIFIED PREFIX' if valid else 'INCOMPLETE / DIAGNOSTIC',data_completeness='UNKNOWN',repository_state=viewer,
            capital=state if valid else None,capital_semantics='M6 CASH PLUS ACQUISITION COST; MTM UNAVAILABLE',
            risk_limits={k:cfg.get(k) for k in ('max_daily_simulated_loss','max_drawdown','max_consecutive_losses')},
            permission_counts=dict(Counter(x['permission'] for x in permissions.values())),candidate_count=len(permissions),
            open_positions=sum(x['position_status'] in ('OPEN','PARTIAL') for x in positions),execution_count=len(executions),
            active_reservations=sum(x['status']=='ACTIVE' for x in reservations.values()),reconciliation=status,
            reconciliation_issues=len(diags),scope='SELECTED RUN TOTALS; detail filters do not resize portfolio')
        tables=dict(permissions=list(permissions.values()),reservations=list(reservations.values()),reservation_history=revisions,
            positions=positions,executions=list(executions.values()),ledger=ledger,
            timeline=sorted(timeline,key=lambda x:(x['timestamp'],x['sequence'],x['category'],x['source_id'])),health=health_rows,risk=risk)
        pagination={}
        for name,rows in tables.items():
            selected=[x for x in rows if _match(x,f)]
            pagination[name]=dict(total=len(rows),matched=len(selected),page=f.page,page_size=f.page_size)
            tables[name]=selected[f.page*f.page_size:(f.page+1)*f.page_size]
        return MonitoringView.create(dict(mode='RESEARCH MODE / READ ONLY',evidence_mode=p['evidence_mode'],
            as_of=f.as_of,run_id=run_id,overview=overview,diagnostics=diags,provenance=p,pagination=pagination,**tables))
