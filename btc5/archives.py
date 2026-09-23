"""Checksum-verified public Binance archives; real 1s bars, never interpolation."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
import logging
from pathlib import Path
import time
import zipfile
import numpy as np
import pandas as pd
import requests
from btc5.data import Candle, MINUTE, CYCLE
from btc5.features import compute, model_features, WARMUP

LOG = logging.getLogger(__name__)
COLS = ['timestamp','open','high','low','close','volume','close_time','quote_volume',
        'trades','buy_volume','buy_quote','ignore']


def read_archive(content: bytes, interval: str) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        files = [n for n in archive.namelist() if n.endswith('.csv')]
        if len(files) != 1:
            raise ValueError('Expected one CSV per archive')
        with archive.open(files[0]) as stream:
            f = pd.read_csv(stream, header=None, names=COLS)
    for k in COLS:
        f[k] = pd.to_numeric(f[k], errors='raise')
    # Official spot archives changed from milliseconds to microseconds in 2025.
    scale = 1000 if f.timestamp.median() > 100_000_000_000_000 else 1
    f['timestamp'] = (f.timestamp // scale).astype('int64')
    f['close_time'] = (f.close_time // scale).astype('int64')
    step = {'1s': 1000, '1m': MINUTE}[interval]
    if f.timestamp.duplicated().any() or not f.timestamp.is_monotonic_increasing:
        raise ValueError('Duplicate or out-of-order archived bars')
    if (f.timestamp % step != 0).any() or (f.close_time != f.timestamp + step - 1).any():
        raise ValueError('Invalid archived bar timestamp units/boundaries')
    vals = f[['open','high','low','close','volume','buy_volume']]
    if not np.isfinite(vals.to_numpy()).all() or (f.low <= 0).any() or (f.volume < 0).any():
        raise ValueError('Non-finite or invalid archived prices/volumes')
    if ((f.high < f[['open','close','low']].max(axis=1)) |
        (f.low > f[['open','close']].min(axis=1)) | (f.buy_volume < 0) |
        (f.buy_volume > f.volume + 1e-8)).any():
        raise ValueError('Invalid archived OHLCV')
    return f


class ArchiveDownloader:
    def __init__(self, cache: Path, symbol='BTCUSDT'):
        self.cache, self.symbol = Path(cache), symbol
        self.cache.mkdir(parents=True, exist_ok=True)
        self.http = requests.Session()

    def day(self, day: date, interval: str) -> pd.DataFrame:
        if interval not in ('1s','1m'):
            raise ValueError('Only base 1s/1m archives supported')
        if day >= datetime.now(timezone.utc).date():
            raise ValueError('Only completed UTC days can be archived')
        name = f'{self.symbol}-{interval}-{day.isoformat()}.zip'
        path = self.cache / name
        checksum_path = path.with_suffix('.zip.CHECKSUM')
        url = f'https://data.binance.vision/data/spot/daily/klines/{self.symbol}/{interval}/{name}'
        if not (path.exists() and checksum_path.exists()):
            for attempt in range(4):
                try:
                    checksum = self.http.get(url + '.CHECKSUM', timeout=30)
                    checksum.raise_for_status()
                    data = self.http.get(url, timeout=120)
                    data.raise_for_status()
                    expected = checksum.text.split()[0].lower()
                    if hashlib.sha256(data.content).hexdigest() != expected:
                        raise ValueError('Downloaded archive checksum mismatch')
                    tmp = path.with_suffix('.partial')
                    tmp.write_bytes(data.content)
                    tmp.replace(path)
                    checksum_path.write_text(checksum.text, encoding='utf-8')
                    break
                except requests.RequestException:
                    if attempt == 3:
                        raise
                    time.sleep(2 ** attempt)
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != checksum_path.read_text().split()[0].lower():
            raise ValueError(f'Cached archive checksum mismatch: {path.name}')
        f = read_archive(content, interval)
        midnight = int(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp()*1000)
        if ((f.timestamp < midnight) | (f.timestamp >= midnight+86_400_000)).any():
            raise ValueError('Archive contains bars outside requested date')
        step = 1000 if interval == '1s' else MINUTE
        manifest = {'source': url, 'sha256': digest, 'rows': len(f),
                    'missing_bars': 86_400_000 // step - len(f), 'interval': interval,
                    'utc_day': str(day)}
        path.with_suffix('.manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        LOG.info('[ARCHIVE] %s %s rows=%s missing=%s', day, interval, len(f), manifest['missing_bars'])
        return f


def minute_bars(frame: pd.DataFrame) -> list[Candle]:
    return [Candle(int(r.timestamp), float(r.open), float(r.high), float(r.low), float(r.close),
                   float(r.volume), float(r.buy_volume), True, int(r.timestamp)+MINUTE)
            for r in frame.itertuples(index=False)]


def seconds_dataset(seconds: pd.DataFrame, step_seconds: int = 10) -> pd.DataFrame:
    """Replay every real second; emit a configurable causal training grid.

    Cumulative intraminute OHLCV is built only from seconds observed so far.
    Incomplete minutes/cycles cannot provide labels or feature history.
    """
    if not 1 <= step_seconds <= 60 or 300 % step_seconds:
        raise ValueError('Sampling step must divide 300 and be in 1..60')
    s = seconds.sort_values('timestamp').copy()
    if s.timestamp.duplicated().any():
        raise ValueError('Duplicate seconds across archives')
    s['minute'] = s.timestamp // MINUTE * MINUTE
    grouped = s.groupby('minute', sort=True)
    m = grouped.agg(timestamp=('timestamp','first'), open=('open','first'), high=('high','max'),
                    low=('low','min'), close=('close','last'), volume=('volume','sum'),
                    buy_volume=('buy_volume','sum'), count=('timestamp','size'), last=('timestamp','last'))
    complete = m[(m['count'] == 60) & (m.timestamp == m.index) & (m['last'] == m.index+59000)]
    minutes = {c.timestamp: c for c in minute_bars(complete.reset_index(drop=True))}
    # Compute cumulative snapshots with grouped vector operations, never minute finals.
    s['partial_high'] = grouped.high.cummax()
    s['partial_low'] = grouped.low.cummin()
    s['partial_volume'] = grouped.volume.cumsum()
    s['partial_buy'] = grouped.buy_volume.cumsum()
    s['partial_open'] = grouped.open.transform('first')
    s['ordinal'] = grouped.cumcount()+1
    s['cycle_id'] = s.timestamp // CYCLE * CYCLE
    elapsed = (s.timestamp + 1000 - s.cycle_id) // 1000
    selected = s[(elapsed % step_seconds == 0) & (elapsed < 300)]
    rows = []
    for r in selected.itertuples(index=False):
        if r.ordinal != (r.timestamp-r.minute)//1000+1:
            continue  # Missing second before this observation; no fabricated partial volume.
        cycle = int(r.cycle_id)
        full = [minutes.get(cycle+i*MINUTE) for i in range(5)]
        if any(c is None for c in full):
            continue
        history = [minutes.get(int(r.minute)-i*MINUTE) for i in range(WARMUP,0,-1)]
        if any(c is None for c in history):
            continue
        c = Candle(int(r.minute), r.partial_open, r.partial_high, r.partial_low, r.close,
                   r.partial_volume, r.partial_buy, False, int(r.timestamp)+999)
        f = compute(history, c, int(r.timestamp)+999, full[0].open)
        outcome = 'UP' if full[-1].close > full[0].open else 'DOWN' if full[-1].close < full[0].open else 'TIE'
        rows.append({'timestamp': int(r.timestamp)+999, 'cycle_id': cycle, 'price': float(r.close),
                     'label': int(outcome == 'UP'), 'outcome': outcome, **model_features(f, r.close)})
        if len(rows) % 10000 == 0:
            LOG.info('[REPLAY] samples=%s step=%ss', len(rows), step_seconds)
    if not rows:
        raise ValueError('No valid second-level samples (90 finalized minute warmup required)')
    f = pd.DataFrame(rows)
    f.attrs.update(source='Binance checksum-verified real 1s archives', sample_seconds=step_seconds)
    return f
