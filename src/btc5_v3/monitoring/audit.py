"""Verify recorded archives without replaying any domain engine."""
import json
import re
from decimal import Decimal
from btc5_v3.encoding import canonical, digest, timestamp
from btc5_v3.monitoring.diagnostics import diagnostic


def parse(text):
    def invalid(_): raise ValueError('nonfinite JSON')
    value=json.loads(text,parse_constant=invalid)
    if not isinstance(value,dict) or canonical(value)!=text: raise ValueError('noncanonical record')
    return value


def amount(value):
    if isinstance(value,bool) or not isinstance(value,(int,str,Decimal)): raise ValueError('invalid amount')
    n=Decimal(value)
    if not n.is_finite() or abs(n)>Decimal('1e30'): raise ValueError('invalid amount')
    return n


def verify(bundle, run_id, as_of):
    diagnostics=[]; accepted=[];run={};metadata={}
    try:
        row=bundle['run'];exp=bundle['experiment']
        if row is None or exp is None: raise ValueError('missing source')
        run=parse(row['payload_json']);metadata=parse(exp['metadata_json']);cfg=run['config']
        identity=dict(run);identity.pop('run_id')
        if (run['run_id']!=run_id or row['id']!=run_id or digest(identity)!=run_id
                or digest(run)!=row['payload_hash'] or run['experiment_id']!=row['experiment_id']
                or exp['id']!=run['experiment_id'] or metadata['id']!=exp['id']
                or exp['config_hash']!=digest(json.loads(exp['config_json']))
                or metadata['config_hash']!=exp['config_hash'] or digest(cfg)!=run['config_hash']):
            raise ValueError('identity corruption')
        if not timestamp(run['created_at']) or run['created_at']>as_of:
            return {},{},[],[diagnostic('UNAVAILABLE','risk_runs',run_id)]
        if run.get('version')!='risk-v1' or cfg.get('version')!='risk-v1':
            return {},{},[],[diagnostic('UNKNOWN_ENUM','risk_runs',run_id)]
        if metadata.get('blind') or metadata.get('evidence_mode')=='BLIND':
            return {},{},[],[diagnostic('UNAVAILABLE','experiments',exp['id'])]
        amount(cfg['starting_capital'])
    except (ValueError,TypeError,KeyError,ArithmeticError,AttributeError,RecursionError):
        return {},{},[],[diagnostic('CORRUPTED','risk_runs',run_id)]
    if (not re.fullmatch(r'[0-9a-f]{40}',str(run.get('code_git','')))
            or not re.fullmatch(r'[0-9a-f]{40}',str(metadata.get('git_commit','')))
            or not metadata.get('data_version')):
        diagnostics.append(diagnostic('MISSING_PROVENANCE','risk_runs',run_id,severity='WARNING'))
    projections={}
    for table,rows in bundle['projections'].items():
        grouped={}
        for row in rows: grouped.setdefault(row['event_id'],[]).append(row)
        projections[table]=grouped
    previous=digest(run);previous_at=run['created_at']
    for sequence,row in enumerate(bundle['events'],1):
        identity=row['id'];at=row['at'];kind=row['kind']
        try:
            inputs=parse(row['inputs_json']);output=parse(row['output_json'])
            if (row['sequence']!=sequence or row['run_id']!=run_id or row['experiment_id']!=run['experiment_id']
                    or not timestamp(at) or not previous_at<=at<=as_of or inputs['at']!=at
                    or output['state_after']['at']!=at or output['state_after']['as_of']!=at
                    or row['previous_hash']!=previous or identity!=digest([run_id,row['request_key']])
                    or row['event_hash']!=digest([previous,identity,sequence,kind,inputs,output])):
                raise ValueError('event integrity')
            if kind not in ('EVALUATE','EXECUTE','CONTROL','EXPIRE'):
                diagnostics.append(diagnostic('UNKNOWN_ENUM','risk_events',identity,at=at));break
            expected={'risk_decisions':[],'capital_reservations':[],'portfolio_snapshots':[output['state_after']]}
            if kind=='EVALUATE': expected['risk_decisions'].append(output['risk_decision'])
            if kind!='EXECUTE' and output.get('reservation'):expected['capital_reservations'].append(output['reservation'])
            expected['capital_reservations']+=output.get('reservation_changes',[])
            for table,values in expected.items():
                actual=projections.get(table,{}).get(identity,[])
                wanted=sorted((digest([identity,table,i]),canonical(v),digest(v)) for i,v in enumerate(values))
                if (any(x['run_id']!=run_id for x in actual)
                        or sorted((x['id'],x['payload_json'],x['payload_hash']) for x in actual)!=wanted):
                    diagnostics.append(diagnostic('CORRUPTED',table,identity,at=at))
                    raise ValueError('projection integrity')
            accepted.append(dict(id=identity,at=at,sequence=sequence,kind=kind,inputs=inputs,output=output))
            previous=row['event_hash'];previous_at=at
        except (ValueError,TypeError,KeyError,OverflowError,RecursionError):
            diagnostics.append(diagnostic('CORRUPTED','risk_events',identity,at=at));break
    if bundle.get('truncated'):diagnostics.append(diagnostic('INCOMPLETE','risk_events',run_id))
    return run,metadata,accepted,diagnostics


def reconcile(report):
    """Arithmetic checks only. Never compute prices, fees or simulated fills."""
    ledger=report['ledger_entries'];accounting=report['accounting'];totals={};cash=Decimal(0);inventory=Decimal(0)
    ids=set();events={e['event_id'] for e in report['order_events']}
    orders={o['order_id'] for o in report['orders']};fills={f['fill_id'] for f in report['fills']}
    for fill in report['fills']:
        if fill['order_id'] not in orders:raise LookupError('missing order')
    for position in report['positions']:
        if position['fill_id'] not in fills or position['order_id'] not in orders:raise LookupError('missing position input')
    for x in ledger:
        if x['ledger_id'] in ids or x['event_id'] not in events:raise LookupError('ledger reference')
        ids.add(x['ledger_id']);n=amount(x['amount'])
        totals[x['asset']]=totals.get(x['asset'],Decimal(0))+n
        if x['account']=='CASH' and x['asset']=='COLLATERAL':cash+=n
        if x['account']=='INVENTORY':inventory+=n
    if (any(totals.values()) or inventory!=amount(accounting['remaining_shares'])
            or cash!=amount(accounting['realized_cash_flow'])
            or amount(accounting['initial_net_shares'])!=amount(accounting['exited_inventory_shares'])+
               amount(accounting['settled_inventory_shares'])+amount(accounting['remaining_shares'])
            or (accounting['completed'] and cash!=amount(accounting['net_simulated_pnl']))):
        return 'MISMATCH',cash,None
    basis=Decimal(0)
    if report['positions']:
        from btc5_v3.edge.numeric import rounded
        opening=report['positions'][0];initial=amount(opening['filled_shares_net'])
        cost=amount(opening['collateral_spent']);basis=cost if initial else Decimal(0);remaining=initial
        groups={}
        for x in ledger: groups.setdefault((x['at'],x['event_id']),[]).append(x)
        for _,legs in sorted(groups.items()):
            if not any(x['reason'].startswith(('EXIT_','SETTLEMENT_','SETTLED_')) for x in legs):continue
            removed=-sum((amount(x['amount']) for x in legs if x['account']=='INVENTORY'),Decimal(0))
            if not 0<=removed<=remaining: return 'MISMATCH',cash,None
            released=basis if removed==remaining else min(basis,rounded(cost*removed/initial))
            basis-=released;remaining-=removed
    return 'RECONCILED',cash,basis
