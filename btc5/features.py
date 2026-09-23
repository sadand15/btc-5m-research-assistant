"""One causal feature implementation shared by historical replay and live snapshots."""
import math
import numpy as np
import pandas as pd
from btc5.data import Candle, MINUTE, CYCLE

FEATURE_SCHEMA = 'causal-minute-v1'
WARMUP = 90


def ema(values: np.ndarray, span: int) -> np.ndarray:
    return pd.Series(values).ewm(span=span, adjust=False).mean().to_numpy()


def rsi(values: np.ndarray, period: int) -> float:
    delta = np.diff(values)
    up = pd.Series(np.maximum(delta, 0)).ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    down = pd.Series(np.maximum(-delta, 0)).ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    return 50.0 if up + down == 0 else float(100 * up / (up + down))


def compute(history: list[Candle], current: Candle, asof: int, cycle_open: float) -> dict[str, float]:
    """history is finalized and ends BEFORE current. current is an as-of snapshot.

    No full historical bar may be substituted for an intraminute snapshot.
    Indicators use the last 90 finalized minutes. Current distance/time/volume
    and momentum use current.close. This contract is identical in both modes.
    """
    if not current.timestamp <= asof < current.timestamp + MINUTE:
        raise ValueError('Snapshot timestamp outside current minute')
    closed = [c for c in history if c.closed and c.timestamp + MINUTE <= current.timestamp][-WARMUP:]
    if len(closed) < WARMUP:
        raise ValueError('Insufficient finalized history')
    if any(c.timestamp != current.timestamp - (WARMUP - i) * MINUTE for i, c in enumerate(closed)):
        raise ValueError('Missing minute in feature window')
    close = np.array([c.close for c in closed])
    volume = np.array([c.volume for c in closed])
    high = np.array([c.high for c in closed])
    low = np.array([c.low for c in closed])
    p = current.close
    cycle = asof // CYCLE * CYCLE
    elapsed = round((asof - cycle) / 1000, 2)
    left = 300 - elapsed
    returns = np.diff(np.log(close))
    # sigma is PRICE volatility over five minutes; Z is dimensionless.
    sigma_1m = max(float(np.std(returns[-30:], ddof=1)), 1e-8)
    sigma_5m_price = cycle_open * sigma_1m * math.sqrt(5)
    distance = p - cycle_open
    f = {'distance_absolute': distance, 'distance_percentage': distance / cycle_open,
         'distance_standardized': distance / sigma_5m_price, 'elapsed_seconds': elapsed,
         'remaining_seconds': left, 'sigma_5m_price': sigma_5m_price,
         'distance_remaining_z': distance / (cycle_open * sigma_1m * math.sqrt(max(left, 1) / 60)),
         'rv_1m': abs(float(returns[-1])), 'rv_5m': float(np.sqrt(np.sum(returns[-5:] ** 2))),
         'rv_15m': float(np.sqrt(np.sum(returns[-15:] ** 2))), 'volatility': sigma_1m}
    for n in (1, 3, 5, 15):
        f[f'return_{n}m'] = p / close[-n] - 1
        if n != 15:
            f[f'momentum_{n}m'] = (p - close[-n]) / (n * sigma_5m_price)
    emas = {}
    for n in (5, 9, 10, 20, 21, 50):
        e = ema(close, n)
        emas[n] = e
        f[f'ema{n}'] = float(e[-1])
        f[f'ema{n}_slope'] = float(e[-1] / e[-2] - 1)
        f[f'price_ema{n}_distance'] = float(p / e[-1] - 1)
    f['ema_spread'] = float((emas[9][-1] - emas[21][-1]) / p)
    f['ema_cross'] = float(np.sign(emas[9][-1] - emas[21][-1]) - np.sign(emas[9][-2] - emas[21][-2]))
    for n in (7, 14):
        f[f'rsi{n}'] = rsi(close, n)
    macd = ema(close, 12) - ema(close, 26)
    signal = ema(macd, 9)
    hist = macd - signal
    f.update(macd_line=float(macd[-1]), macd_signal=float(signal[-1]),
             macd_histogram=float(hist[-1]), macd_histogram_slope=float(hist[-1] - hist[-2]))
    typical = (high + low + close) / 3
    def vwap(a, b):
        v = volume[a:b]
        return float(np.dot(typical[a:b], v) / v.sum()) if v.sum() else float(close[b - 1])
    vw, prev_vw = vwap(-20, len(volume)), vwap(-21, len(volume) - 1)
    tr = np.maximum(high[1:] - low[1:], np.maximum(abs(high[1:] - close[:-1]), abs(low[1:] - close[:-1])))
    f.update(vwap=vw, price_vwap_distance=p - vw, price_vwap_ratio=p / vw,
             vwap_slope=(vw - prev_vw) / prev_vw, atr=float(np.mean(tr[-14:])),
             current_volume=current.volume, rolling_volume=float(volume[-20:].sum()),
             volume_ratio=current.volume / max(float(volume[-20:].mean()), 1e-8),
             volume_zscore=(current.volume - float(volume[-20:].mean())) / max(float(volume[-20:].std()), 1e-8),
             aggressive_buy_volume=current.buy_volume,
             aggressive_sell_volume=current.volume - current.buy_volume,
             aggressive_ratio=current.buy_volume / current.volume if current.volume else 0.5,
             minute_elapsed_seconds=(asof - current.timestamp) / 1000)
    # 15m trend uses only completed, UTC-aligned 15m bars.
    groups = []
    for start in sorted({c.timestamp // 900_000 * 900_000 for c in closed}):
        group = [c for c in closed if start <= c.timestamp < start + 900_000]
        if len(group) == 15 and group[0].timestamp == start:
            groups.append(group[-1].close)
    f['trend_15m'] = float(groups[-1] / groups[-2] - 1) if len(groups) >= 2 else 0.0
    f['trend_5m'] = f['return_5m']
    f['trend_1m'] = f['return_1m']
    if not all(math.isfinite(v) for v in f.values()):
        raise ValueError('Non-finite feature')
    return f


# Absolute price-level indicators are recorded, but normalized for modeling.
EXCLUDE = {'distance_absolute', 'sigma_5m_price', 'vwap', 'price_vwap_distance',
           'macd_line', 'macd_signal', 'macd_histogram', 'macd_histogram_slope',
           'atr', 'current_volume', 'rolling_volume', 'aggressive_buy_volume',
           'aggressive_sell_volume', 'minute_elapsed_seconds'} | {f'ema{n}' for n in (5, 9, 10, 20, 21, 50)}


def model_features(features: dict[str, float], price: float) -> dict[str, float]:
    selected = {k: v for k, v in features.items() if k not in EXCLUDE}
    for k in ('atr', 'macd_line', 'macd_signal', 'macd_histogram', 'macd_histogram_slope'):
        selected[k + '_normalized'] = features[k] / price
    return selected
