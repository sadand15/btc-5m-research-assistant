"""Entry policy and hypothetical binary paper settlement, independent of model."""
import math
from btc5.database import Database, dumps
from btc5.data import Candle, CYCLE


def decide(probability: float | None, f: dict, book: dict | None, cfg: dict,
           supported: bool, fresh: bool = True, historical: bool = False) -> tuple[str, str]:
    e = cfg['entry']
    if probability is None or not math.isfinite(probability) or not 0 <= probability <= 1:
        return 'WAIT', 'MODEL_NOT_READY'
    if not fresh:
        return 'WAIT', 'STALE_DATA'
    if not supported:
        return 'WAIT', 'OUTSIDE_CALIBRATION_TIME_SUPPORT'
    if not e['min_remaining_seconds'] <= f['remaining_seconds'] <= e['max_remaining_seconds']:
        return 'WAIT', 'TIME_FILTER'
    # OHLCV history has no book: report this explicitly rather than inventing spread.
    if not historical and e['require_book'] and not book:
        return 'WAIT', 'BOOK_UNAVAILABLE'
    if book and book['spread_bps'] > e['max_spread_bps']:
        return 'WAIT', 'SPREAD_FILTER'
    if not e['min_volatility'] <= f['volatility'] <= e['max_volatility']:
        return 'WAIT', 'VOLATILITY_FILTER'
    for side, p, sign, threshold in [('UP', probability, 1, e['up_threshold']),
                                     ('DOWN', 1 - probability, -1, e['down_threshold'])]:
        if (p >= threshold and sign * f['trend_15m'] > e['trend_deadband']
                and sign * f['momentum_5m'] > e['momentum_min']
                and sign * f['momentum_1m'] > e['momentum_min']):
            return side, 'ENTRY_CANDIDATE'
    return 'WAIT', 'PROBABILITY_OR_MOMENTUM_FILTER'


def payoff(side: str, outcome: str, stake: float, payout: float, fee: float) -> tuple[str, float]:
    if outcome == 'TIE':
        return 'VOID', -fee
    win = side == outcome
    return ('WIN' if win else 'LOSS'), stake * (payout if win else -1) - fee


class PaperEngine:
    def __init__(self, db: Database, cfg: dict):
        self.db, self.cfg = db, cfg

    def enter(self, timestamp: int, cycle: int, side: str, price: float, probability: float,
              features: dict, version: str) -> bool:
        p = self.cfg['paper_trading']
        if not p['enabled'] or side not in ('UP', 'DOWN') or not cycle <= timestamp < cycle + CYCLE:
            return False
        if self.db.conn.execute('SELECT 1 FROM outcomes WHERE cycle_id=?', (cycle,)).fetchone():
            return False
        with self.db.conn:
            cur = self.db.conn.execute('''INSERT OR IGNORE INTO trades
              (timestamp,cycle_id,cycle_end,direction,entry_price,probability,remaining_seconds,
               model_version,features,stake,payout,fee) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
              (timestamp, cycle, cycle + CYCLE, side, price, probability,
               features['remaining_seconds'], version, dumps(features),
               p['stake'], p['net_win_payout'], p['fee_per_trade']))
        return cur.rowcount == 1

    def settle(self, candle: Candle) -> list[dict]:
        if candle.timeframe != '5m' or not candle.closed:
            return []
        outcome = 'UP' if candle.close > candle.open else 'DOWN' if candle.close < candle.open else 'TIE'
        settled = []
        with self.db.conn:
            self.db.conn.execute('INSERT OR IGNORE INTO outcomes VALUES (?,?,?,?)',
                                 (candle.timestamp, candle.open, candle.close, outcome))
            for row in self.db.conn.execute("SELECT * FROM trades WHERE cycle_id=? AND result='PENDING'", (candle.timestamp,)).fetchall():
                result, pnl = payoff(row['direction'], outcome, row['stake'], row['payout'], row['fee'])
                self.db.conn.execute('UPDATE trades SET result=?,pnl=? WHERE trade_id=? AND result=\'PENDING\'',
                                     (result, pnl, row['trade_id']))
                settled.append({'trade_id': row['trade_id'], 'result': result, 'pnl': pnl})
        return settled
