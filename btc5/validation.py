"""Out-of-sample regime diagnostics and paired UTC-day block bootstrap."""
import numpy as np
import pandas as pd
from btc5.research import classification


def diagnostics(frame: pd.DataFrame, fit_end: int, test: pd.DataFrame,
                probabilities: dict[str, np.ndarray], seed=42, replicates=500) -> dict:
    # Regimes are descriptive: trailing cycle-price returns, never future outcome labels.
    cycles = frame.groupby('cycle_id', sort=True).price.first()
    timestamps = cycles.index.to_numpy()
    regular = pd.Series(timestamps, index=cycles.index).diff().rolling(288).max().eq(300000)
    ret = cycles.pct_change(288, fill_method=None).where(regular)
    vol = cycles.pct_change(fill_method=None).rolling(288).std().where(regular)
    train_vol = vol[vol.index < fit_end].dropna()
    if train_vol.empty:
        raise ValueError('Need at least 24h history for causal regime definitions')
    q1, q2 = train_vol.quantile([1/3, 2/3]).tolist()
    meta = pd.DataFrame(index=test.index)
    meta['month'] = pd.to_datetime(test.timestamp, unit='ms', utc=True).dt.strftime('%Y-%m')
    trailing = test.cycle_id.map(ret)
    meta['trend_24h'] = np.where(trailing > .01, 'rising', np.where(trailing < -.01, 'falling', 'sideways'))
    meta.loc[trailing.isna(), 'trend_24h'] = 'insufficient_history'
    v = test.cycle_id.map(vol)
    meta['volatility_24h'] = np.where(v < q1, 'low', np.where(v < q2, 'medium', 'high'))
    meta.loc[v.isna(), 'volatility_24h'] = 'insufficient_history'
    meta['remaining_seconds'] = test.remaining_seconds.round().astype(int)
    result = {'definition': 'Trailing 24h cycle prices; trend +/-1%; vol terciles learned BEFORE calibration cutoff.',
              'volatility_thresholds': [q1,q2], 'groups': {}, 'paired_day_bootstrap': {}}
    for category in meta:
        result['groups'][category] = {}
        for group in sorted(meta[category].unique()):
            mask = (meta[category] == group).to_numpy()
            result['groups'][category][str(group)] = {
                'cycles': int(test.loc[mask].cycle_id.nunique()),
                **{name: {k:v for k,v in classification(test.loc[mask].label, p[mask]).items() if k != 'calibration'}
                   for name,p in probabilities.items()}}
    # All snapshots from a day remain together; compare models on the SAME resample.
    day = (test.timestamp // 86_400_000).to_numpy()
    y = test.label.to_numpy()
    day_ids = np.unique(day)
    rng = np.random.default_rng(seed)
    draw = rng.integers(0, len(day_ids), size=(replicates, len(day_ids)))
    for name,p in probabilities.items():
        loss = (p-y)**2
        reference = (probabilities['distance_time']-y)**2
        counts = np.array([(day==d).sum() for d in day_ids])
        totals = np.array([loss[day==d].sum() for d in day_ids])
        diffs = np.array([(loss-reference)[day==d].sum() for d in day_ids])
        scores = totals[draw].sum(axis=1) / counts[draw].sum(axis=1)
        deltas = diffs[draw].sum(axis=1) / counts[draw].sum(axis=1)
        result['paired_day_bootstrap'][name] = {
            'independent_day_blocks': len(day_ids), 'replicates': replicates,
            'brier_95_percentile': np.quantile(scores,[.025,.975]).tolist(),
            'brier_minus_distance_time_95_percentile': np.quantile(deltas,[.025,.975]).tolist(),
            'interpretation': 'Negative difference favors this model; short/block-dependent sample may still understate uncertainty.'}
    return result
