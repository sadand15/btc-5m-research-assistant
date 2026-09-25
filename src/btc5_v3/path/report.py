"""Deterministic Markdown companion; JSON retains every grid and individual path."""
import json


def markdown(result):
    r=json.loads(result.report_json);c=r['coverage'];cfg=r['config']
    lines=['# Intracycle path research — synthetic demo','',
           f'Analysis `{result.analysis_id}`; code `{result.code_git}`; cutoff `{result.cutoff}`.',
           f'Config `{result.config_hash}`; inputs `{result.input_hash}`.','',
           '## Coverage','',f"Markets: {c['markets']}; path points: {c['path_points']}; freshness-filtered points: {c['freshness_filtered_points']}; stale: {c['stale_quote_count']}.",
           'Archive-conditional observations; not whole-database coverage. Missing intervals remain missing.','',
           '## Repricing distribution by TTE and side','',
           'Mid is descriptive. Bid is an observable side-price proxy and does not guarantee a fill.',
           'Fractions below use rows with an observed future; sparse paths provide observed extrema only. Repeated points are not independent.',
           'Empty cells remain in JSON. All fixed rebound thresholds are shown; no threshold ranking.','',
           '| Freshness view | Side | Price view | Initial price | TTE ms | N / future N / markets | +.05 | +.10 | +.20 | +.30 | +.40 | +.60 | Median rebound |',
           '|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    def show(x): return 'null' if x is None else str(round(float(x),6))
    for x in r['study_tables']:
        if not x['count']: continue
        p=x['price_bucket'];t=x['tte_bucket']
        rates=' | '.join(show(g['observed_hit_fraction']) for g in x['grid'])
        lines.append(f"| {x['view']} | {x['side']} | {x['price_view']} | {cfg['price_buckets'][p]}–{cfg['price_buckets'][p+1]} | {cfg['tte_buckets_ms'][t]}–{cfg['tte_buckets_ms'][t+1]} | {x['count']} / {x['observed_future_count']} / {x['unique_markets']} | {rates} | {show(x['median_max_rebound'])} |")
    lines+=['','## Settlement and market paths','',
            'Settlement is separate from quote extrema. Temporary rebound may end in a losing payout; unresolved and split labels remain explicit.',
            '| Market | Side | View | Range | Direction changes | Large reversals | Settlement | Missing intervals |',
            '|---|---|---|---:|---:|---:|---:|---:|']
    for x in r['market_metrics']:
        lines.append(f"| {x['market_id']} | {x['side']} | {x['view']} | {show(x['total_range'])} | {x['number_of_direction_changes']} | {x['number_of_large_reversals']} | {show(x['settlement_payout'])} | {x['missing_interval_count']} |")
    lines+=['','Full per-observation extrema, signed drawdowns, bid/mid contrasts, settlement counts at every rebound threshold, fixed-TTE missing views and spread/depth/age/M3 conditioning are in the JSON artifact.',
            'BTC shock conditioning is unavailable: no explicitly supplied causal BTC series.','',
            '## Limitations','']+['- '+x for x in r['limitations']]
    return '\n'.join(lines)+'\n'
