"""Produce compact factual evidence from local artifacts (no network requests)."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
report = json.loads((root / 'runtime/report.json').read_text(encoding='utf-8'))
with sqlite3.connect(root / 'runtime/research.sqlite') as conn:
    counts = {table: conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
              for table in ['candles', 'predictions', 'trades', 'outcomes']}
    coverage = conn.execute("SELECT MIN(timestamp),MAX(timestamp),COUNT(*) FROM candles WHERE timeframe='1m' AND closed=1").fetchone()
    sample_span = conn.execute('SELECT MIN(timestamp),MAX(timestamp),COUNT(DISTINCT cycle_id) FROM predictions').fetchone()
    decisions = dict(conn.execute('SELECT reason,COUNT(*) FROM predictions GROUP BY reason'))
    state = {k: json.loads(v) for k,v in conn.execute('SELECT key,value FROM state')}
    book_samples = conn.execute("SELECT COUNT(*) FROM predictions WHERE json_extract(features,'$.orderbook.bid') IS NOT NULL").fetchone()[0]
summary = {'counts': counts, 'finalized_minute_coverage': coverage,
           'live_prediction_span': sample_span, 'live_entry_reasons': decisions,
           'live_snapshots_with_book': book_samples, 'connection': state.get('connection'),
           'models': {name: {k: v[k] for k in ['accuracy','precision','recall','f1','brier_score','uncalibrated_brier']}
                      for name, v in report['models'].items()}, 'split': report['split'],
           'walk_forward': [{k:v[k] for k in ['samples','accuracy','brier_score']} for v in report['walk_forward']]}
(root / 'runtime/verification.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
print(json.dumps(summary, indent=2))
freeze = subprocess.run([sys.executable, '-m', 'pip', 'freeze'], capture_output=True, text=True, check=True)
(root / 'requirements.lock.txt').write_text(freeze.stdout, encoding='utf-8')
