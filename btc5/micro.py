"""Identical causal second-bar features for archived and streaming data."""
import numpy as np
import pandas as pd

MICRO_COLUMNS = ['return_5s','return_10s','return_15s','return_30s','return_60s',
                 'momentum_acceleration','rv_60s','volume_change_30s','buy_flow_30s',
                 'sell_flow_30s','flow_imbalance_30s']


def micro_frame(seconds):
    s = seconds.sort_values('timestamp').copy()
    if s.timestamp.duplicated().any():
        raise ValueError('Duplicate second bar')
    out = pd.DataFrame(index=s.index)
    out['timestamp'] = s.timestamp + 999
    for n in (5,10,15,30,60):
        out[f'return_{n}s'] = s.close / s.close.shift(n) - 1
    out['momentum_acceleration'] = out.return_5s - (s.close.shift(5)/s.close.shift(10)-1)
    out['rv_60s'] = np.log(s.close).diff().pow(2).rolling(60).sum().pow(.5)
    volume = s.volume.rolling(30).sum()
    out['volume_change_30s'] = volume / volume.shift(30).clip(lower=1e-8) - 1
    out['buy_flow_30s'] = s.buy_volume.rolling(30).sum()
    out['sell_flow_30s'] = volume-out.buy_flow_30s
    out['flow_imbalance_30s'] = (out.buy_flow_30s-out.sell_flow_30s)/volume.clip(lower=1e-8)
    valid = s.timestamp.diff().rolling(60).min().eq(1000) & s.timestamp.diff().rolling(60).max().eq(1000)
    out.loc[~valid, MICRO_COLUMNS] = np.nan
    return out


def live_micro(seconds, asof):
    s = pd.DataFrame([r for r in seconds if r['timestamp']+999 <= asof])
    if len(s)<61:
        raise ValueError('MICRO_WARMUP_OR_MISSING_SECONDS')
    last = micro_frame(s).iloc[-1]
    if asof-last.timestamp > 2000 or not np.isfinite(last[MICRO_COLUMNS].to_numpy(dtype=float)).all():
        raise ValueError('STALE_OR_GAPPED_TRADE_FLOW')
    return {k:float(last[k]) for k in MICRO_COLUMNS}
