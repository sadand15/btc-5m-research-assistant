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
        CREATE TABLE IF NOT EXISTS venue_markets (
          market_id INTEGER PRIMARY KEY, received_at INTEGER, binding TEXT, raw_market TEXT, raw_category TEXT);
        CREATE TABLE IF NOT EXISTS venue_books (
          id INTEGER PRIMARY KEY, market_id INTEGER, received_at INTEGER, source_at INTEGER,
          normalized TEXT, raw TEXT, UNIQUE(market_id, received_at));
        CREATE INDEX IF NOT EXISTS venue_book_time ON venue_books(received_at);
        CREATE TABLE IF NOT EXISTS venue_orders (
          id INTEGER PRIMARY KEY, cycle_id INTEGER UNIQUE, market_id INTEGER, status TEXT,
          signal TEXT, fill TEXT, settlement TEXT);
        CREATE TABLE IF NOT EXISTS venue_outcomes (
          market_id INTEGER PRIMARY KEY, received_at INTEGER, yes_payout REAL, raw TEXT);
        CREATE TABLE IF NOT EXISTS audit_v2 (
          id INTEGER PRIMARY KEY, timestamp INTEGER, cycle_id INTEGER, kind TEXT, payload TEXT);
        CREATE INDEX IF NOT EXISTS audit_v2_cycle ON audit_v2(cycle_id,timestamp);
        CREATE TABLE IF NOT EXISTS paper_positions_v2 (
          id INTEGER PRIMARY KEY, scenario TEXT, cycle_id INTEGER, signal TEXT,
          fill TEXT, settlement TEXT, UNIQUE(scenario,cycle_id));
        CREATE TABLE IF NOT EXISTS venue_resolution_checks (
          id INTEGER PRIMARY KEY, market_id INTEGER, received_at INTEGER, payout REAL, raw TEXT);
        CREATE INDEX IF NOT EXISTS resolution_check_market ON venue_resolution_checks(market_id,received_at);
        CREATE TABLE IF NOT EXISTS forward_observations (
          id INTEGER PRIMARY KEY, run_id TEXT, timestamp INTEGER, cycle_id INTEGER, market_id INTEGER,
          book_id INTEGER, prediction_id INTEGER, eligible INTEGER, payload TEXT,
          UNIQUE(run_id,book_id));
        CREATE INDEX IF NOT EXISTS forward_cycle ON forward_observations(run_id,cycle_id,timestamp);
        ''')
        if 'available_at' not in {r[1] for r in self.conn.execute('PRAGMA table_info(predictions)')}:
            self.conn.execute('ALTER TABLE predictions ADD COLUMN available_at INTEGER')
            self.conn.commit()

    def audit(self,timestamp,cycle,kind,payload):
        with self.conn:
            self.conn.execute('INSERT INTO audit_v2(timestamp,cycle_id,kind,payload) VALUES (?,?,?,?)',
                (timestamp,cycle,kind,dumps(payload)))

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

    def prediction(self, timestamp, cycle, price, probability, features, version, decision, reason, supported,available_at=None):
        with self.conn:
            self.conn.execute('''INSERT OR IGNORE INTO predictions
                (timestamp,cycle_id,price,up_probability,down_probability,remaining_seconds,
                 model_version,features,decision,reason,supported,available_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                (timestamp, cycle, price, probability, 1 - probability, features['remaining_seconds'],
                version, dumps(features), decision, reason, int(supported),timestamp if available_at is None else available_at))
