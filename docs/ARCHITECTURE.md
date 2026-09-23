# Architecture

`app.py` coordinates bootstrap, live Binance monitoring, paper execution and dashboard processes. `config.yaml` defines relative storage paths, model settings and safety gates. Runtime paths resolve locally; no credentials belong in configuration.

| Component | Responsibility |
|---|---|
| `btc5/data.py`, `archives.py` | REST/WebSocket ingestion, checksummed archives, real seconds replay |
| `features.py`, `micro.py` | Causal cycle features and short-term features |
| `research.py`, `v2research.py`, `validation.py` | Chronological experiments, calibration, walk-forward/regime diagnostics |
| `inference.py`, `live.py` | Single-flight inference, freshness checks and post-inference market checks |
| `market.py`, `predictfun.py`, `venue.py` | MarketDataProvider, read-only live quotes, market binding and official settlement |
| `execution.py`, `fees.py`, `paper_v2.py` | Mock/replay fills with depth, fees, spread, slippage and latency |
| `database.py` | Local SQLite predictions, books, outcomes and execution audit trail |
| `forward.py` | Immutable seven-day study manifest, paired observations and reporting |
| `dashboard.py`, `mobile.py` | Streamlit research UI and lightweight mobile HTML |
| `scripts/register_release.py` | Additive Git release metadata, separate from inference |

Predict.fun requests use a key read from the process environment and market-data GET endpoints. There is no wallet signing or real-money order submission. Quote/market identifiers and Chainlink feed IDs are public identifiers, not credentials.

The current model targets Binance prices. Official Predict.fun BTC/USDT Top-of-Book settlement is a different target. The basis-risk guard remains enabled; missing data or unsupported conditions produce WAIT. Market midpoint probabilities are comparison baselines, not executable prices.

Frozen `btc5/*.py`, `app.py`, configuration and model files were not changed during release preparation. Release provenance joins existing `forward_observations` by `run_id`; historical rows are not rewritten. A new table and ignored sidecar identify the exact Git commit, tag, model hash and config hash. The script checks committed source bytes against the original freeze manifest before registering them.
