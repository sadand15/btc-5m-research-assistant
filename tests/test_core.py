from dataclasses import replace
import json
import numpy as np
import pytest
from btc5.config import load_config
from btc5.data import Candle, CandleBook, OrderBook, Historical, MINUTE, CYCLE
from btc5.database import Database
from btc5.features import compute, model_features
from btc5.research import dataset, train, Predictor, backtest, classification
from btc5.strategy import PaperEngine, decide, payoff


def candles(n=300):
    rng = np.random.default_rng(12)
    values = 60000 * np.exp(np.r_[0., np.cumsum(rng.normal(0, .0006, n))])
    return [Candle(i * MINUTE, float(values[i]), float(max(values[i:i+2]) + 2),
                   float(min(values[i:i+2]) - 2), float(values[i+1]), 10. + i % 9,
                   5., True, (i + 1) * MINUTE) for i in range(n)]


@pytest.fixture
def cfg(tmp_path):
    c = load_config()
    c['storage'] = {'database': str(tmp_path / 'test.db'), 'model': str(tmp_path / 'model.joblib'),
                    'report': str(tmp_path / 'report.json')}
    c['model'].update(min_cycles=100, n_estimators=20, walk_forward_folds=2)
    return c


def test_aggregation_dedup_partial_and_gap():
    rows = candles(15)
    b = CandleBook()
    for c in rows[:4]:
        assert b.update(c)
        assert not b.update(c)
    partial = b.aggregate(0, 5)
    assert not partial.closed and partial.open == rows[0].open
    b.update(rows[4])
    full = b.aggregate(0, 5)
    assert full.closed and full.close == rows[4].close
    assert full.volume == sum(c.volume for c in rows[:5])
    assert not b.update(replace(rows[4], closed=False, event_time=999999))
    del b.minutes[2 * MINUTE]
    assert b.aggregate(0, 5) is None


def test_15m_uses_exact_utc_open():
    b = CandleBook()
    for c in candles(30)[1:]:
        b.update(c)
    assert b.aggregate(0, 15) is None
    assert b.aggregate(15 * MINUTE, 15).closed


def test_features_are_causal_and_require_continuity():
    rows = candles()
    current = replace(rows[123], closed=False)
    asof = current.timestamp + 40000
    first = compute(rows[:123], current, asof, rows[120].open)
    # Appending arbitrary future candles must not alter a feature.
    second = compute(rows, current, asof, rows[120].open)
    assert first == second
    assert first['remaining_seconds'] == 80
    with pytest.raises(ValueError, match='Missing minute'):
        compute(rows[:100] + rows[101:123], current, asof, rows[120].open)
    with pytest.raises(ValueError, match='outside'):
        compute(rows, current, current.timestamp - 1, rows[120].open)


def test_training_features_do_not_depend_on_future_cycle_close():
    rows = candles(160)
    before = dataset(rows)
    changed = rows.copy()
    changed[124] = replace(rows[124], high=100000, close=99999)
    after = dataset(changed)
    # The outcome may change, but all feature inputs before minute 124 stay identical.
    cols = [c for c in before if c not in ('label', 'outcome')]
    np.testing.assert_allclose(before.loc[before.timestamp < 124 * MINUTE, cols],
                               after.loc[after.timestamp < 124 * MINUTE, cols])
    assert set(before.elapsed_seconds) == {60, 120, 180, 240}


def test_nan_and_invalid_ohlc_rejected():
    with pytest.raises(ValueError):
        Candle(0, 1, 2, 1, float('nan'), 1)
    with pytest.raises(ValueError):
        Candle(1, 1, 2, 1, 1, 1)
    with pytest.raises(ValueError):
        Candle(0, 5, 2, 1, 1, 1)


def test_orderbook_snapshots_are_idempotent():
    b = OrderBook()
    data = {'lastUpdateId': 100, 'bids': [[str(100-i), '2'] for i in range(20)],
            'asks': [[str(101+i), '1'] for i in range(20)]}
    assert b.update(data, 1000)
    assert not b.update(data, 2000)
    assert b.received_at == 1000
    assert b.values['obi_10'] == pytest.approx(1 / 3)
    assert b.values['depth_5'] == 15


def test_no_trade_filters(cfg):
    f = dict(remaining_seconds=120, volatility=.001, trend_15m=.01, momentum_5m=1, momentum_1m=1)
    assert decide(.8, f, {'spread_bps': 1}, cfg, True)[0] == 'UP'
    assert decide(.8, f, {'spread_bps': 1}, cfg, False)[0] == 'WAIT'
    assert decide(.8, f, None, cfg, True)[1] == 'BOOK_UNAVAILABLE'
    assert decide(.8, f, {'spread_bps': 1}, cfg, True, fresh=False)[1] == 'STALE_DATA'
    assert decide(.8, f, {'spread_bps': 10}, cfg, True)[1] == 'SPREAD_FILTER'
    assert decide(.52, f, {'spread_bps': 1}, cfg, True)[0] == 'WAIT'


def test_paper_restart_once_per_cycle_and_settlement(cfg):
    db = Database(cfg['storage']['database'])
    e = PaperEngine(db, cfg)
    f = {'remaining_seconds': 120}
    assert e.enter(180000, 0, 'UP', 103, .8, f, 'v1')
    assert not e.enter(190000, 0, 'DOWN', 102, .8, f, 'v1')
    db.close()
    db = Database(cfg['storage']['database'])
    e = PaperEngine(db, cfg)
    # Close below ENTRY but above cycle OPEN: UP is a WIN.
    c = Candle(0, 100, 105, 99, 101, 10, 5, True, CYCLE, '5m')
    assert e.settle(c)[0]['result'] == 'WIN'
    assert e.settle(c) == []
    assert db.conn.execute('SELECT pnl FROM trades').fetchone()[0] == 1
    assert not e.enter(200000, 0, 'UP', 103, .8, f, 'v1')
    db.close()


def test_ties_are_void_and_payoff_configured():
    assert payoff('DOWN', 'TIE', 2, .8, .1) == ('VOID', -.1)
    result, pnl = payoff('UP', 'UP', 2, .8, .1)
    assert result == 'WIN' and pnl == pytest.approx(1.5)


def test_database_final_cannot_be_overwritten_by_partial(cfg):
    db = Database(cfg['storage']['database'])
    c = candles(1)[0]
    db.candles([c])
    db.candles([replace(c, closed=False, volume=50, event_time=999999)])
    assert db.read_minutes()[0].volume == c.volume
    db.close()


def test_historical_pagination_and_unclosed_exclusion(cfg):
    h = Historical(cfg)
    def raw(t):
        return [t, '100', '102', '99', '101', '10', t+59999, '1000', 10, '5', '500', '0']
    calls = []
    def get(endpoint, **params):
        calls.append(params)
        return [raw(t) for t in range(params['startTime'], min(240000, params['startTime']+120000), MINUTE)]
    h.get = get
    rows = h.download(0, 210000)
    assert [c.timestamp for c in rows] == [0, 60000, 120000]
    assert len(calls) == 2


def test_training_chronology_calibration_and_reload(cfg):
    frame = dataset(candles(900))
    report = train(frame, cfg)
    s = report['split']
    assert s['train']['last_cycle'] < s['calibration']['first_cycle']
    assert s['calibration']['last_cycle'] < s['test']['first_cycle']
    for fold in report['walk_forward']:
        assert fold['train_last_cycle'] < fold['calibration_first_cycle']
        assert fold['calibration_last_cycle'] < fold['test_first_cycle']
    predictor = Predictor(cfg['storage']['model'])
    rows = candles(920)
    f = compute(rows[:910], rows[910], rows[910].timestamp+59999, rows[910].open)
    p = predictor.predict(f, rows[910].close, rows[910].timestamp+59999)
    assert 0 <= p <= 1
    assert predictor.supported(59, 4)
    assert not predictor.supported(61, 4)
    with pytest.raises(ValueError, match='cutoff'):
        predictor.predict(f, rows[910].close, 0)
    broken = f.copy()
    broken['rsi7'] = float('nan')
    with pytest.raises(ValueError, match='NaN'):
        predictor.predict(broken, rows[910].close, rows[910].timestamp+59999)
    assert all(0 <= m['brier_score'] <= 1 for m in report['models'].values())
    assert json.loads(open(cfg['storage']['report'], encoding='utf-8').read())['model_version'] == predictor.version


def test_backtest_drawdown_includes_initial_equity(cfg):
    import pandas as pd
    frame = pd.DataFrame([dict(timestamp=180000, cycle_id=0, price=100, label=0, outcome='DOWN',
                             remaining_seconds=120, volatility=.001, trend_15m=.01, momentum_5m=1, momentum_1m=1)])
    result = backtest(frame, np.array([.9]), cfg)
    assert result['max_drawdown'] == 1
    assert result['losses'] == 1
    cfg['entry']['up_threshold'] = .99
    empty = backtest(frame, np.array([.9]), cfg)
    assert empty['total_trades'] == 0 and empty['win_rate'] is None
