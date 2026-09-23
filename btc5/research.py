"""Chronological training, held-out calibration and reproducible research reports."""
import hashlib
import importlib.metadata
import json
import logging
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, brier_score_loss, log_loss
from btc5.data import CandleBook, CYCLE, MINUTE
from btc5.features import compute, model_features, FEATURE_SCHEMA, WARMUP
from btc5.strategy import decide, payoff

LOG = logging.getLogger(__name__)
META = {'timestamp', 'cycle_id', 'price', 'label', 'outcome'}


def dataset(candles: list) -> pd.DataFrame:
    candles = sorted(candles, key=lambda c: c.timestamp)
    book = CandleBook()
    for c in candles:
        if c.closed:
            book.update(c)
    rows = []
    for i, c in enumerate(candles):
        cycle = c.timestamp // CYCLE * CYCLE
        full = book.aggregate(cycle, 5)
        # The last minute's close already reveals settlement: never use it as a sample.
        if i < WARMUP or c.timestamp - cycle == 4 * MINUTE or not full or not full.closed:
            continue
        asof = c.timestamp + MINUTE - 1
        try:
            f = compute(candles[max(0, i - WARMUP):i], c, asof, full.open)
        except ValueError:
            continue
        outcome = 'UP' if full.close > full.open else 'DOWN' if full.close < full.open else 'TIE'
        row = dict(timestamp=asof, cycle_id=cycle, price=c.close, label=int(outcome == 'UP'), outcome=outcome)
        row.update(model_features(f, c.close))
        rows.append(row)
        if len(rows) % 2000 == 0:
            LOG.info('[FEATURE] historical samples %s', len(rows))
    if not rows:
        raise ValueError('No complete samples: need contiguous minutes and complete cycles')
    return pd.DataFrame(rows).sort_values('timestamp').reset_index(drop=True)


def calibration_bins(y, p) -> list[dict]:
    y, p = np.asarray(y), np.asarray(p)
    result = []
    for lo in np.arange(0, 1, 0.1):
        hi = lo + 0.1
        mask = (p >= lo) & (p < hi if hi < 0.999 else p <= 1)
        n = int(mask.sum())
        result.append({'bin': f'{lo:.0%}-{hi:.0%}', 'count': n,
                       'predicted': float(p[mask].mean()) if n else None,
                       'actual_up_rate': float(y[mask].mean()) if n else None})
    return result


def classification(y, p) -> dict:
    y, p = np.asarray(y), np.asarray(p)
    pred = p >= 0.5
    return {'samples': len(y), 'accuracy': float(accuracy_score(y, pred)),
            'precision': float(precision_score(y, pred, zero_division=0)),
            'recall': float(recall_score(y, pred, zero_division=0)),
            'f1': float(f1_score(y, pred, zero_division=0)),
            'brier_score': float(brier_score_loss(y, p)),
            'log_loss': float(log_loss(y, p, labels=[0, 1])),
            'calibration': calibration_bins(y, p)}


def grouped(frame: pd.DataFrame, probabilities: np.ndarray, key: str, edges: list) -> list[dict]:
    result = []
    values = probabilities if key == 'up_probability' else frame[key].to_numpy()
    for i, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
        mask = (values >= lo) & (values <= hi if i == len(edges) - 2 else values < hi)
        n = int(mask.sum())
        result.append({'range': f'{lo}-{hi}', 'samples': n,
                       'actual_up_rate': float(frame.loc[mask, 'label'].mean()) if n else None,
                       'brier_score': float(brier_score_loss(frame.loc[mask, 'label'], probabilities[mask])) if n else None,
                       'accuracy': float(accuracy_score(frame.loc[mask, 'label'], probabilities[mask] >= .5)) if n else None})
    return result


def backtest(frame: pd.DataFrame, probabilities: np.ndarray, cfg: dict) -> dict:
    trades = []
    used = set()
    for row, prob in zip(frame.to_dict('records'), probabilities):
        cycle = row['cycle_id']
        if cycle in used:
            continue
        side, _ = decide(float(prob), row, None, cfg, supported=True, historical=True)
        if side == 'WAIT' or not cfg['paper_trading']['enabled']:
            continue
        used.add(cycle)
        p = cfg['paper_trading']
        result, pnl = payoff(side, row['outcome'], p['stake'], p['net_win_payout'], p['fee_per_trade'])
        trades.append({'timestamp': row['timestamp'], 'cycle_id': cycle, 'direction': side,
                       'confidence': float(prob if side == 'UP' else 1 - prob),
                       'remaining_seconds': row['remaining_seconds'], 'entry_price': row['price'],
                       'result': result, 'pnl': pnl})
    pnls = np.array([t['pnl'] for t in trades])
    equity = np.r_[cfg['paper_trading']['initial_equity'], cfg['paper_trading']['initial_equity'] + np.cumsum(pnls)]
    peak = np.maximum.accumulate(equity)
    gross_loss = float(-pnls[pnls < 0].sum())
    wins, losses = sum(t['result'] == 'WIN' for t in trades), sum(t['result'] == 'LOSS' for t in trades)
    def trade_groups(key, edges):
        out = []
        for i, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
            ts = [t for t in trades if lo <= t[key] and (t[key] <= hi if i == len(edges)-2 else t[key] < hi)]
            resolved = [t for t in ts if t['result'] != 'VOID']
            out.append({'range': f'{lo}-{hi}', 'trades': len(ts),
                        'win_rate': sum(t['result'] == 'WIN' for t in resolved) / len(resolved) if resolved else None,
                        'pnl': sum(t['pnl'] for t in ts)})
        return out
    return {'scope': 'OHLCV-only minute-close replay; orderbook/spread filters NOT evaluated',
            'pnl_unit': 'hypothetical fixed-stake binary units, not BTC/USDT execution profit',
            'total_trades': len(trades), 'wins': wins, 'losses': losses,
            'voids': len(trades) - wins - losses, 'win_rate': wins / (wins + losses) if wins + losses else None,
            'no_trade_cycles': int(frame.cycle_id.nunique()) - len(trades),
            'net_pnl': float(pnls.sum()), 'max_drawdown': float((peak - equity).max()),
            'max_drawdown_fraction': float(((peak - equity) / peak).max()),
            'profit_factor': float(pnls[pnls > 0].sum()) / gross_loss if gross_loss else None,
            'by_confidence': trade_groups('confidence', [.5, .55, .6, .65, .7, .75, .8, .9, 1]),
            'by_remaining': trade_groups('remaining_seconds', [0, 30, 60, 90, 120, 180, 300]),
            'trades': trades}


def estimator(kind: str, cfg: dict):
    if kind in ('logistic', 'distance_time'):
        return make_pipeline(StandardScaler(), LogisticRegression(max_iter=1500, C=0.5, random_state=cfg['model']['seed']))
    if kind != 'lightgbm':
        raise ValueError(f'Unknown model type: {kind}')
    m = cfg['model']
    return LGBMClassifier(n_estimators=m['n_estimators'], num_leaves=m['num_leaves'],
                          learning_rate=m['learning_rate'], min_child_samples=m['min_child_samples'],
                          random_state=m['seed'], n_jobs=2, verbosity=-1, deterministic=True, force_col_wise=True)


def fit_calibrated(kind, train, cal, columns, cfg):
    if train.label.nunique() < 2 or cal.label.nunique() < 2:
        raise ValueError('Training AND calibration partitions each require UP and non-UP outcomes')
    base = estimator(kind, cfg).fit(train[columns], train.label)
    calibrated = CalibratedClassifierCV(FrozenEstimator(base), method='sigmoid')
    calibrated.fit(cal[columns], cal.label)
    return base, calibrated


def train(frame: pd.DataFrame, cfg: dict) -> dict:
    cycles = np.sort(frame.cycle_id.unique())
    if len(cycles) < cfg['model']['min_cycles']:
        raise ValueError(f'Need {cfg["model"]["min_cycles"]} cycles; found {len(cycles)}')
    a = int(len(cycles) * cfg['model']['train_fraction'])
    b = int(len(cycles) * (cfg['model']['train_fraction'] + cfg['model']['calibration_fraction']))
    tr = frame[frame.cycle_id < cycles[a]]
    ca = frame[(frame.cycle_id >= cycles[a]) & (frame.cycle_id < cycles[b])]
    te = frame[frame.cycle_id >= cycles[b]]
    columns = sorted(set(frame.columns) - META)
    if not np.isfinite(frame[columns].to_numpy(dtype=float)).all():
        raise ValueError('NaN/Inf model input')
    report = {'schema': FEATURE_SCHEMA, 'data_source': 'Binance public finalized 1m OHLCV',
              'target': 'P(cycle_close > cycle_open); complement includes ties',
              'ties': int(frame[frame.outcome == 'TIE'].cycle_id.nunique()),
              'split': {name: {'cycles': int(part.cycle_id.nunique()), 'samples': len(part),
                               'first_cycle': int(part.cycle_id.min()), 'last_cycle': int(part.cycle_id.max())}
                        for name, part in [('train', tr), ('calibration', ca), ('test', te)]},
              'models': {}, 'config': cfg,
              'limitations': ['Minute close samples only; no historical intraminute interpolation.',
                              'DOWN probability means non-UP; ties void paper positions.',
                              'Repeated samples within a cycle are correlated; sample count is not independent cycle count.',
                              'Feature importance is exploratory, not a feature selection result.',
                              'PnL assumes configured hypothetical binary payoff; no venue quotes or fill model.']}
    selected = None
    for kind in ('distance_time', 'logistic', 'lightgbm'):
        cols = ['distance_standardized', 'distance_remaining_z', 'remaining_seconds'] if kind == 'distance_time' else columns
        LOG.info('[MODEL] fitting %s train=%s calibration=%s test=%s', kind, len(tr), len(ca), len(te))
        base, calibrated = fit_calibrated(kind, tr, ca, cols, cfg)
        probs = calibrated.predict_proba(te[cols])[:, 1]
        result = classification(te.label, probs)
        result['uncalibrated_brier'] = float(brier_score_loss(te.label, base.predict_proba(te[cols])[:, 1]))
        result['by_up_probability'] = grouped(te, probs, 'up_probability', [0, .5, .55, .6, .65, .7, .75, .8, .9, 1])
        result['by_remaining'] = grouped(te, probs, 'remaining_seconds', [0, 30, 60, 90, 120, 180, 300])
        result['backtest'] = backtest(te, probs, cfg)
        report['models'][kind] = result
        if kind == cfg['model']['type']:
            selected = (calibrated, cols)
            # Permute only on test; do not feed this ranking back into fitting.
            importance = permutation_importance(calibrated, te[cols], te.label,
                n_repeats=3, random_state=cfg['model']['seed'], scoring='neg_brier_score', n_jobs=1)
            report['feature_importance'] = sorted(
                [{'feature': col, 'brier_increase': float(mean), 'std': float(std)}
                 for col, mean, std in zip(cols, importance.importances_mean, importance.importances_std)],
                key=lambda r: r['brier_increase'], reverse=True)
    report['constant_train_prior'] = classification(te.label, np.full(len(te), tr.label.mean()))
    # A direction persistence baseline measures the already-observed part of the cycle.
    report['current_side_baseline'] = classification(te.label, np.where(te.distance_percentage > 0, .75, .25))
    report['walk_forward'] = []
    folds = cfg['model']['walk_forward_folds']
    for frac in np.linspace(.4, .7, folds) if folds else []:
        x, y, z = [int(len(cycles) * v) for v in (frac, frac + .1, frac + .2)]
        wt = frame[frame.cycle_id < cycles[x]]
        wc = frame[(frame.cycle_id >= cycles[x]) & (frame.cycle_id < cycles[y])]
        we = frame[(frame.cycle_id >= cycles[y]) & (frame.cycle_id < cycles[min(z, len(cycles)-1)])]
        cols = selected[1]
        _, model = fit_calibrated(cfg['model']['type'], wt, wc, cols, cfg)
        report['walk_forward'].append({'train_last_cycle': int(wt.cycle_id.max()),
            'calibration_first_cycle': int(wc.cycle_id.min()), 'calibration_last_cycle': int(wc.cycle_id.max()),
            'test_first_cycle': int(we.cycle_id.min()), 'test_last_cycle': int(we.cycle_id.max()),
            **classification(we.label, model.predict_proba(we[cols])[:, 1])})
    fingerprint = hashlib.sha256(pd.util.hash_pandas_object(frame, index=False).values.tobytes()).hexdigest()
    version_hash = hashlib.sha256((fingerprint + json.dumps(cfg['model'], sort_keys=True) + FEATURE_SCHEMA).encode()).hexdigest()
    version = f'{cfg["model"]["type"]}-{version_hash[:12]}'
    artifact = {'model': selected[0], 'columns': selected[1], 'version': version,
                'schema': FEATURE_SCHEMA, 'symbol': cfg['symbol'], 'fit_end': int(ca.cycle_id.max()) + CYCLE,
                'elapsed_support': sorted(frame.elapsed_seconds.round(3).unique().tolist()),
                'fingerprint': fingerprint, 'config': cfg}
    path = Path(cfg['storage']['model'])
    temp = path.with_suffix('.tmp')
    joblib.dump(artifact, temp)
    temp.replace(path)
    report['model_version'] = version
    report['data_sha256'] = fingerprint
    report['package_versions'] = {name: importlib.metadata.version(name)
        for name in ['numpy', 'pandas', 'scikit-learn', 'lightgbm', 'joblib']}
    out = Path(cfg['storage']['report'])
    out.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    te.to_csv(out.with_name('heldout_samples.csv'), index=False)
    pd.DataFrame(report['models'][cfg['model']['type']]['backtest']['trades']).to_csv(out.with_name('backtest_trades.csv'), index=False)
    return report


class Predictor:
    def __init__(self, path: str):
        # Only load artifacts created locally by this project (joblib is executable).
        self.artifact = joblib.load(path)
        if self.artifact['schema'] != FEATURE_SCHEMA:
            raise ValueError('Feature schema mismatch; retrain model')

    @property
    def version(self):
        return self.artifact['version']

    def predict(self, features: dict, price: float, timestamp: int) -> float:
        if timestamp < self.artifact['fit_end']:
            raise ValueError('Refusing prediction before model calibration cutoff')
        row = model_features(features, price)
        values = pd.DataFrame([row], columns=self.artifact['columns'])
        if not np.isfinite(values.to_numpy(dtype=float)).all():
            raise ValueError('NaN/Inf or missing model inputs')
        return float(self.artifact['model'].predict_proba(values)[:, 1][0])

    def supported(self, elapsed: float, tolerance: float) -> bool:
        # Only approach a trained minute close from the left. Just AFTER a boundary
        # has a new partial candle/volume and is a different input distribution.
        return any(0 <= t - elapsed <= tolerance for t in self.artifact['elapsed_support'])
