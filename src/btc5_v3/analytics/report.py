"""Deterministic Markdown rendering; full precision remains in the JSON artifact."""
import json
from decimal import Decimal


def display(value):
    if value is None:return 'unavailable'
    if isinstance(value,(int,bool)):return str(value)
    try:return format(Decimal(value),'.6f')
    except Exception:return str(value)


def markdown(result):
    r=json.loads(result.report_json);q=r['prediction_quality'];c=r['coverage']
    lines=['# M4 synthetic research evidence','',f'Analysis: `{result.analysis_id}`',
           f'Experiment: `{result.experiment_id}`',f'Code: `{result.code_git}`',f'Cutoff UTC ms: {result.cutoff}',
           '', '**SYNTHETIC / HYPOTHETICAL ONLY — sensitivity analysis ≠ optimization.**',
           '', '## Data coverage','', '| Measure | Value |','|---|---|']
    for key in ('input_rows','total_predictions','valid_snapshot_rows','resolved_rows','eligible_research_observations',
                'edge_candidates','m3_admissible_candidates','candidate_coverage','split_count','unique_markets'):
        lines.append(f'| {key} | {display(c[key])} |')
    lines+=['', 'Excluded reasons (counts can overlap): `'+json.dumps(c['excluded_reasons'],sort_keys=True)+'`',
            'M3 rejection counts: `'+json.dumps(c['m3_rejection_reasons'],sort_keys=True)+'`',
            '', '## Probability quality','', '| Measure | Value |','|---|---|']
    for key in ('brier_payout','brier_binary','log_loss','ece','mce','binary_settled_count','split_count','log_loss_epsilon'):
        lines.append(f'| {key} | {display(q[key])} |' if key!='log_loss_epsilon' else f'| {key} | {q[key]} |')
    lines+=['', 'Binary calibration; split is counted separately. Brier payout includes y=0.5.',
            '', '| Bin | Count | Binary | Split | Mean p (binary) | Observed YES (binary) | Gap |',
            '|---|---|---|---|---|---|---|']
    for b in q['bins']:
        lines.append('| '+ ' | '.join(map(str,[f"[{b['lower']},{b['upper']}{']' if b['upper']=='1' else ')'}",b['count'],b['binary_count'],b['split_count'],
                                               display(b['mean_predicted_probability']),display(b['observed_yes_rate']),display(b['calibration_gap'])]))+' |')
    lines+=['','## Edge analysis','', 'All YES/NO scenarios are mutually exclusive hypotheses, not a portfolio. Returns are collateral per gross share.']
    for view in r['edge_analysis_all_scenarios']:
        lines+=['',f"### {view['side']}",'', '| Signed bucket | Count | Resolved | Mean edge | Mean hypothetical return |', '|---|---|---|---|---|']
        for b in view['buckets']:
            lines.append(f"| {b['bucket']} | {b['count']} | {b['resolved_count']} | {display(b['mean_predicted_edge'])} | {display(b['mean_hypothetical_realized_return'])} |")
        m=view['monotonicity'];lines+=['',f"Spearman: {display(m['correlation'])}; {m['status']}; markets={m['unique_markets']}."]
    lines+=['', '## TTE','', '| Bucket | Rows | Brier payout | Coverage | Mean net edge | Hypothetical return |','|---|---|---|---|---|---|']
    for t in r['tte']:
        lines.append(f"| {t['bucket']} | {t['count']} | {display(t['probability_quality']['brier_payout'])} | {display(t['candidate_coverage'])} | {display(t['mean_net_edge'])} | {display(t['mean_hypothetical_realized_return'])} |")
    lines+=['','## Sensitivity','', 'Fixed M3-admissible cohort. No rejected candidate is resurrected; no side switch. Cost stress uses fixed strict edge > 0.01.',
            '', '| Scenario | Value | Admissible | Coverage | Mean stressed edge (fixed cohort) | Hypothetical return (passing) |',
            '|---|---|---|---|---|---|']
    for s in r['sensitivity']:
        lines.append(f"| {s['scenario']} | {s['value']} | {s['admissible_candidates']} | {display(s['coverage'])} | {display(s['mean_hypothetical_net_edge'])} | {display(s['mean_hypothetical_realized_return'])} |")
    lines+=['','## Limitations','']+['- '+x for x in r['limitations']]
    lines+=['','Profit factor and Sharpe unavailable. No execution evidence, independent-row confidence interval or OOS claim.',
            'JSON includes all observations, model groups, chronological days, both candidate-only and all-scenario views; this Markdown is a compact rendering.','']
    return '\n'.join(lines)
