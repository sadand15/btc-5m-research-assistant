import json
import sqlite3
from dataclasses import asdict
from btc5.data import Candle, CandleBook


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


class Database:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS candles (
          timestamp INTEGER, timeframe TEXT, open REAL, high REAL, low REAL,
          close REAL, volume REAL, buy_volume REAL, closed INTEGER, event_time INTEGER,
          PRIMARY KEY(timestamp, timeframe));
        CREATE TABLE IF NOT EXISTS predictions (
          id INTEGER PRIMARY KEY, timestamp INTEGER, cycle_id INTEGER, price REAL,
          up_probability REAL, down_probability REAL, remaining_seconds REAL,
          model_version TEXT, features TEXT, decision TEXT, reason TEXT,
          supported INTEGER, UNIQUE(timestamp, model_version));
        CREATE TABLE IF NOT EXISTS trades (
          trade_id INTEGER PRIMARY KEY, timestamp INTEGER, cycle_id INTEGER UNIQUE,
          cycle_end INTEGER, direction TEXT, entry_price REAL, probability REAL,
          remaining_seconds REAL, model_version TEXT, features TEXT,
          result TEXT DEFAULT 'PENDING', pnl REAL, stake REAL, payout REAL, fee REAL);
        CREATE TABLE IF NOT EXISTS outcomes (
          cycle_id INTEGER PRIMARY KEY, open_price REAL, close_price REAL, direction TEXT);
        CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
        CREATE INDEX IF NOT EXISTS prediction_cycle ON predictions(cycle_id);
        ''')

    def close(self):
        self.conn.close()

    def candles(self, rows: list[Candle]):
        with self.conn:
            self.conn.executemany('''INSERT INTO candles VALUES
              (:timestamp,:timeframe,:open,:high,:low,:close,:volume,:buy_volume,:closed,:event_time)
              ON CONFLICT(timestamp,timeframe) DO UPDATE SET
              open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,
              volume=excluded.volume,buy_volume=excluded.buy_volume,
              closed=excluded.closed,event_time=excluded.event_time
              WHERE excluded.event_time >= candles.event_time AND excluded.closed >= candles.closed''',
              [asdict(c) for c in rows])

    def import_minutes(self, rows: list[Candle]):
        self.candles(rows)
        book = CandleBook()
        for row in rows:
            book.update(row)
        derived = []
        for n in (5, 15):
            for t in sorted({c.timestamp // (n * 60000) * n * 60000 for c in rows}):
                c = book.aggregate(t, n)
                if c:
                    derived.append(c)
        self.candles(derived)

    def read_minutes(self, start: int = 0) -> list[Candle]:
        return [Candle(**{**dict(r), 'closed': bool(r['closed'])}) for r in self.conn.execute(
            "SELECT * FROM candles WHERE timeframe='1m' AND closed=1 AND timestamp>=? ORDER BY timestamp", (start,))]

    def state(self, **kwargs):
        with self.conn:
            self.conn.executemany('INSERT OR REPLACE INTO state VALUES (?,?)', [(k, dumps(v)) for k, v in kwargs.items()])

    def prediction(self, timestamp, cycle, price, probability, features, version, decision, reason, supported):
        with self.conn:
            self.conn.execute('''INSERT OR IGNORE INTO predictions
                (timestamp,cycle_id,price,up_probability,down_probability,remaining_seconds,
                 model_version,features,decision,reason,supported) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (timestamp, cycle, price, probability, 1 - probability, features['remaining_seconds'],
                 version, dumps(features), decision, reason, int(supported)))
