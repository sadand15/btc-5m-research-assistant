"""Post-hoc only. Never writes to, tunes or changes Prediction/Edge/Decision."""
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import json

from btc5_v3.encoding import canonical, digest
from btc5_v3.edge.numeric import CONTEXT, rounded
from btc5_v3.analytics.models import AnalysisResult, EdgeSensitivityResult, validate_run_identity
from btc5_v3.analytics.statistics import (mean,calibration,edge_bucket,tte_bucket,EDGE_BUCKETS,TTE_BUCKETS,
                                        bucket_summary,spearman)

D=Decimal


def decimal(value):
    result=D(str(value))
    if not result.is_finite():raise ValueError('nonfinite analytical input')
    return result


def hypothetical(side,payout,multiplier=D(1)):
    """Stress only fees/assumed latency/extra, never spread or observed book again."""
    with localcontext(CONTEXT):
        return _hypothetical(side,payout,multiplier)


def _hypothetical(side,payout,multiplier):
    c=side['cost_breakdown'];gross=decimal(c['gross_shares'])
    shares_fee=decimal(c['fee_shares_total'])*multiplier
    if gross<=0 or shares_fee>gross:return None
    net=gross-shares_fee
    extras=gross*(decimal(c['assumed_latency_cost_per_share'])+decimal(c['assumed_extra_cost_per_share']))
    spent=decimal(c['collateral_spent'])+(multiplier-1)*(decimal(c['fee_collateral_total'])+extras)
    expected=net*decimal(side['probability'])-spent
    realized=net*payout-spent if payout is not None else None
    return dict(hypothetical_net_edge=rounded(expected/gross),hypothetical_ev_total=expected,
                hypothetical_realized_value_total=realized,
                hypothetical_realized_return=realized/gross if realized is not None else None,
                hypothetical_roi=realized/spent if realized is not None and spent>0 else None,
                net_shares=net,collateral_spent=spent)


def analyze(observations,outcomes,config,*,experiment_id,code_git,cutoff,created_at):
    validate_run_identity(experiment_id,code_git,cutoff,created_at)
    with localcontext(CONTEXT):
        return _analyze(tuple(observations),tuple(outcomes),config,experiment_id,code_git,cutoff,created_at)


def _analyze(observations,outcomes,c,experiment_id,code_git,cutoff,created_at):
    archives=sorted((o.data() for o in observations),key=lambda x:(x['prediction']['available_at'],x['prediction']['prediction_id']))
    ids=[x['prediction']['prediction_id'] for x in archives]
    if len(ids)!=len(set(ids)):raise ValueError('one explicit observation per prediction; duplicate selection forbidden')
    if any(x['prediction']['experiment_id']!=experiment_id for x in archives):raise ValueError('cross-experiment analysis forbidden')
    outcome_map={}
    for o in sorted(outcomes,key=lambda x:x.outcome_id):
        if o.experiment_id!=experiment_id:raise ValueError('cross-experiment outcome forbidden')
        if o.market_id in outcome_map:raise ValueError('ambiguous market outcome/revision')
        outcome_map[o.market_id]=o
    excluded={};samples=[];sides=[]
    def exclude(reason):excluded[reason]=excluded.get(reason,0)+1
    total_predictions=sum(x['prediction']['available_at']<=cutoff for x in archives)
    for data in archives:
        p,s,e,d=(data[k] for k in ('prediction','snapshot','edge','decision'))
        if p['available_at']>cutoff:exclude('PREDICTION_AFTER_CUTOFF');continue
        if p['support_status']!='SUPPORTED' or p['target_definition']['probability_semantics']!='MARKET_YES':
            exclude('UNSUPPORTED_TARGET');continue
        target=p['target_definition'];prob=decimal(p['p_yes'])
        reasons=[]
        valid_snapshot=bool(s and s['market_id']==p['market_id'] and s['experiment_id']==experiment_id
                            and s['rule_hash']==target['rule_hash'] and s['outcome_mapping']==target['outcome_mapping']
                            and s['expiry']==target['expiry'] and s['available_at']<=cutoff)
        if not valid_snapshot:reasons.append('MISSING_OR_INCOMPATIBLE_SNAPSHOT')
        valid_edge=bool(valid_snapshot and e and e['prediction_id']==p['prediction_id'] and e['snapshot_id']==s['snapshot_id']
                        and e['experiment_id']==experiment_id and e['evaluated_at']<=cutoff and decimal(e['p_yes'])==prob
                        and e['edge_id']==digest(dict(experiment_id=experiment_id,prediction_id=p['prediction_id'],
                            snapshot_id=s['snapshot_id'],evaluated_at=e['evaluated_at'],config_hash=e['config_hash'])))
        if not valid_edge:reasons.append('MISSING_OR_INCOMPATIBLE_EDGE')
        valid_decision=bool(valid_edge and d and d['prediction_id']==p['prediction_id'] and d['snapshot_id']==s['snapshot_id']
                            and d['edge_id']==e['edge_id'] and d['experiment_id']==experiment_id and d['evaluated_at']<=cutoff
                            and d['decision_id']==digest([experiment_id,d['attempt_key']])
                            and d['input_hash']==digest([canonical(s),canonical(p),canonical(e)]))
        if not valid_decision:reasons.append('MISSING_OR_INCOMPATIBLE_DECISION')
        at=d['evaluated_at'] if valid_decision else e['evaluated_at'] if valid_edge else p['available_at']
        if at>=target['expiry']:reasons.append('AT_OR_AFTER_EXPIRY')
        if valid_edge and (p['available_at']>e['evaluated_at'] or s['available_at']>e['evaluated_at']):
            reasons.append('FUTURE_EDGE_INPUT')
        if valid_decision and e['evaluated_at']>at:reasons.append('FUTURE_DECISION_INPUT')
        eligible=valid_decision and not reasons
        admissible=bool(eligible and d['final_action'] in ('BUY_YES','BUY_NO') and not d['all_reasons']
                        and d['final_action']==e['candidate_action'])
        o=outcome_map.get(p['market_id']);payout=None;outcome_reason=None
        if o is None:outcome_reason='OUTCOME_MISSING'
        elif o.available_at>cutoff or o.resolution_at>cutoff:outcome_reason='OUTCOME_AFTER_CUTOFF'
        elif o.rule_hash!=target['rule_hash'] or o.source!=c.outcome_source or o.settlement_version!=c.settlement_version:
            outcome_reason='OUTCOME_CONTRACT_MISMATCH'
        elif o.resolution_at<target['expiry'] or o.resolution_at<=at:
            outcome_reason='OUTCOME_NOT_POSTHOC'
        else:payout=o.yes_payout
        for reason in reasons:exclude(reason)
        if outcome_reason:exclude(outcome_reason)
        probability_usable=payout is not None and p['available_at']<target['expiry'] and o.resolution_at>p['available_at']
        day=datetime.fromtimestamp(at/1000,timezone.utc).date().isoformat()
        sample=dict(prediction_id=p['prediction_id'],market_id=p['market_id'],p_yes=prob,yes_payout=payout,
                    probability_usable=probability_usable,valid_snapshot=valid_snapshot,eligible=eligible,
                    edge_candidate=bool(valid_edge and e['candidate_action'] in ('BUY_YES','BUY_NO')),
                    admissible=admissible,at=at,day=day,tte=target['expiry']-at,model_version=p['model_version'],
                    m3_reasons=tuple(d['all_reasons']) if valid_decision else (),exclusion_reasons=tuple(reasons),
                    outcome_exclusion_reason=outcome_reason)
        samples.append(sample)
        # Side diagnostics are mutually exclusive hypotheses, never a combined portfolio.
        if eligible:
            for side_name,key in (('YES','yes'),('NO','no')):
                side=e[key]
                if side is None:continue
                if side['side']!=side_name or side['requested_shares']!=e['requested_shares']:
                    raise ValueError('side lineage mismatch')
                outcome=payout if side_name=='YES' or payout is None else 1-payout
                value=hypothetical(side,outcome)
                if value is None:raise ValueError('invalid base economics')
                if value['hypothetical_net_edge']!=decimal(side['net_edge_per_share']):
                    raise ValueError('M2 economic archive integrity failure')
                sides.append(dict(prediction_id=p['prediction_id'],market_id=p['market_id'],side=side_name,
                                  raw_edge=decimal(side['raw_edge']),net_edge=decimal(side['net_edge_per_share']),
                                  payout=outcome,hypothetical_realized_return=value['hypothetical_realized_return'],
                                  hypothetical_realized_value_total=value['hypothetical_realized_value_total'],
                                  admissible=admissible and d['final_action']=='BUY_'+side_name,
                                  tte=sample['tte'],day=day,side_record=side))
    denominator=sum(x['eligible'] for x in samples)
    def probability_quality(rows):
        return calibration([(x['p_yes'],x['yes_payout']) for x in rows if x['probability_usable']],c)
    def edge_view(rows):
        views=[]
        for side in ('YES','NO','COMBINED'):
            chosen=[x for x in rows if side=='COMBINED' or x['side']==side]
            resolved=[x for x in chosen if x['hypothetical_realized_return'] is not None]
            buckets=[dict(bucket=b,**bucket_summary([x for x in chosen if edge_bucket(x['net_edge'])==b])) for b in EDGE_BUCKETS]
            views.append(dict(side=side,buckets=buckets,monotonicity=spearman(
                [x['net_edge'] for x in resolved],[x['hypothetical_realized_return'] for x in resolved],
                minimum_sample_count=c.minimum_sample_count,unique_markets=len({x['market_id'] for x in resolved})),
                population='MUTUALLY_EXCLUSIVE_SCENARIOS_NOT_PORTFOLIO'))
        return views
    def grouped(rows,side_rows):
        n=sum(x['eligible'] for x in rows);selected=[x for x in side_rows if x['admissible']]
        return dict(count=len(rows),unique_markets=len({x['market_id'] for x in rows}),probability_quality=probability_quality(rows),
                    status='DESCRIPTIVE_ONLY_NO_SIGNIFICANCE_TEST' if len({x['market_id'] for x in rows})>=c.minimum_sample_count else 'INSUFFICIENT_SAMPLE',
                    eligible_research_observations=n,admissible_candidates=sum(x['admissible'] for x in rows),
                    candidate_coverage=D(sum(x['admissible'] for x in rows))/n if n else None,
                    mean_raw_edge=mean([x['raw_edge'] for x in selected]),mean_net_edge=mean([x['net_edge'] for x in selected]),
                    mean_hypothetical_realized_return=mean([x['hypothetical_realized_return'] for x in selected if x['hypothetical_realized_return'] is not None]))
    ttes=[dict(bucket=b,**grouped([x for x in samples if x['tte']>=0 and tte_bucket(x['tte'])==b],
                                [x for x in sides if tte_bucket(x['tte'])==b])) for b in TTE_BUCKETS]
    periods=[dict(utc_day=day,**grouped([x for x in samples if x['day']==day],[x for x in sides if x['day']==day]))
             for day in sorted({x['day'] for x in samples})]
    sensitivity=[]
    # Conservative fixed-M3-candidate cohort: no resurrection or side switching.
    cohort=[x for x in sides if x['admissible']]
    for kind,grid in (('THRESHOLD',c.threshold_grid),('COST_MULTIPLIER',c.cost_multiplier_grid)):
        for factor in grid:
            rows=[]
            for x in cohort:
                value=hypothetical(x['side_record'],x['payout'],factor if kind=='COST_MULTIPLIER' else D(1))
                passes=value is not None and value['hypothetical_net_edge']>(factor if kind=='THRESHOLD' else c.cost_stress_threshold)
                rows.append(dict(prediction_id=x['prediction_id'],side=x['side'],passes_counterfactual=passes,
                                 status='VALID' if value is not None else 'INVALID_SHARE_FEE_STRESS',
                                 **(value or {})))
            selected=[x for x in rows if x['passes_counterfactual']]
            realized=[x['hypothetical_realized_return'] for x in selected if x['hypothetical_realized_return'] is not None]
            result=EdgeSensitivityResult(kind,factor,denominator,len(selected),D(len(selected))/denominator if denominator else None,
                                         len(realized),mean([x['hypothetical_net_edge'] for x in rows if 'hypothetical_net_edge' in x]),
                                         mean(realized),tuple(rows),factor if kind=='THRESHOLD' else c.cost_stress_threshold)
            sensitivity.append(asdict(result))
    fingerprints=digest({'observations':[json.loads(o.payload_json) for o in sorted(observations,key=lambda x:x.input_hash)],
                         'outcomes':[json.loads(o.to_json()) for o in sorted(outcomes,key=lambda x:x.outcome_id)]})
    identity=dict(experiment_id=experiment_id,code_git=code_git,cutoff=cutoff,config_hash=c.hash,input_hash=fingerprints)
    rejections={}
    payout_by_prediction={x['prediction_id']:x['yes_payout'] for x in samples}
    for sample in samples:
        for reason in sample['m3_reasons']:rejections[reason]=rejections.get(reason,0)+1
    report=dict(coverage=dict(input_scope='EXPLICIT_ARCHIVE_NOT_WHOLE_DATABASE',input_rows=len(archives),total_predictions=total_predictions,analyzed_predictions=len(samples),
                             valid_snapshot_rows=sum(x['valid_snapshot'] for x in samples),resolved_rows=sum(x['probability_usable'] for x in samples),
                             edge_candidates=sum(x['edge_candidate'] for x in samples),eligible_research_observations=denominator,
                             m3_admissible_candidates=sum(x['admissible'] for x in samples),
                             candidate_coverage=D(sum(x['admissible'] for x in samples))/denominator if denominator else None,
                             unique_markets=len({x['market_id'] for x in samples}),excluded_reasons=dict(sorted(excluded.items())),
                             m3_rejection_reasons=dict(sorted(rejections.items())),
                             split_count=sum(x['yes_payout']==D('.5') and x['probability_usable'] for x in samples),
                             denominator_definition='ALL STRUCTURALLY MATCHED PRE-EXPIRY PREDICTION/SNAPSHOT/EDGE/DECISION ROWS; NO SETTLEMENT FILTER'),
                prediction_quality=probability_quality(samples),
                by_model=[dict(model_version=v,**probability_quality([x for x in samples if x['model_version']==v]))
                          for v in sorted({x['model_version'] for x in samples})],
                by_settlement_direction=[dict(direction=label,**grouped(
                    [x for x in samples if x['yes_payout']==value],
                    [x for x in sides if payout_by_prediction[x['prediction_id']]==value]))
                    for label,value in (('YES',D(1)),('NO',D(0)),('SPLIT',D('.5')))],
                edge_analysis_all_scenarios=edge_view(sides),edge_analysis_admissible_candidates=edge_view(cohort),
                tte=ttes,chronological_periods=periods,sensitivity=sensitivity,observations=samples,
                hypothetical_profit_factor=None,hypothetical_sharpe=None,
                limitations=['SYNTHETIC_RESEARCH_SETTLEMENT_ONLY','NO_EXECUTION_SIMULATION','NO_REAL_FILLS','NO_LIVE_TRADING_CLAIM',
                             'SENSITIVITY_ANALYSIS_NOT_OPTIMIZATION','FEES_MAY_BE_SYNTHETIC','SPLIT_PROBABILITY_MODEL_UNAVAILABLE',
                             'REPEATED_MARKET_ROWS_NOT_INDEPENDENT','NO_CLUSTER_CONFIDENCE_INTERVALS','NO_OUT_OF_SAMPLE_CLAIM',
                             'FIXED_M3_CANDIDATE_COHORT_NO_SIDE_RESELECTION','ARCHIVE_COMPLETENESS_REQUIRES_EXTERNAL_EVIDENCE'])
    return AnalysisResult(digest(identity),experiment_id,code_git,cutoff,created_at,c.hash,fingerprints,canonical(report))
