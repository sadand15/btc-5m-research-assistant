# Data and reproducibility

Market archives, SQLite databases, full observations, logs, model binaries and generated research outputs remain under ignored `runtime/`. This repository contains small Markdown research reports, not the raw study database.

Data source: Binance public BTCUSDT spot archives, downloaded by `btc5/archives.py` with published checksum verification. The seconds study uses real 1-second candles sampled every 5 seconds; it is not synthetic interpolation of minute bars. Current deployments additionally record read-only Predict.fun market metadata, order books and official settlements.

In a **separate fresh clone**, after installing dependencies, recreate the historical windows:

```powershell
.\.venv\Scripts\python.exe research.py seconds --days 14 --step 5 --end 2026-09-22
.\.venv\Scripts\python.exe research.py regimes --days 90 --end 2026-09-22
.\.venv\Scripts\python.exe v2.py research
.\.venv\Scripts\python.exe v2.py paper
```

The downloader includes warm-up data before each start. Network access and substantial local storage/time are required. Historical reports preserve the observed results; retraining under different library versions can produce different binary model hashes. `requirements.lock.txt` records the original installed environment; `requirements.txt` defines supported installation ranges.

The first-run V1 window used server time at download, rather than a pinned end date. Its original data fingerprint and review are recorded in the study reports; the live SQLite database is intentionally not published.

All six inspected local joblib files are small (about 195–412 KB) but contain absolute local storage paths in their artifact configuration. They remain private and ignored. The original deployed model and frozen backup are unchanged. See `docs/FROZEN_MODEL.json` for identity, not a claim that a retrained artifact is byte-identical.

Predict.fun historical books cannot be reconstructed from Binance candles. Missing real quotes remain missing; replay with generated quotes is explicitly a mock execution experiment. Never run training over the active frozen deployment or replace its database with test data.
