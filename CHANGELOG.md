# Changelog

## v2.0.0

- Audit cycle leakage; add hard-direction naive baseline and independent validation partition.
- Replay real one-second archives on a five-second grid; expand to 90-day regime analysis and walk-forward validation.
- Compare probability calibration, confidence/coverage and short-term micro features.
- Add single-flight inference, stale-data protection and post-inference market re-check.
- Add MarketDataProvider, live read-only Predict.fun quote recording and replay/mock quotes.
- Simulate fees, spread, slippage, depth and latency with an audit trail; no real orders.
- Extend Streamlit research views and serve a lightweight iPhone/iPad dashboard.
- Freeze a seven-day forward observation protocol with model, policy and source hashes.
- Package private GitHub releases, offline CI and a separate release-provenance table. Prediction code and deployed model unchanged by packaging.

Historical accuracy does not establish an advantage over the naive baseline. Synthetic fills do not demonstrate real-money profitability.

## v1.0.0

- BTC five-minute direction prediction using distance_time, Logistic Regression and LightGBM.
- Chronological train/calibration/test splits, basic probability calibration and diagnostics.
- Binance historical/live data, SQLite audit storage and Streamlit dashboard.
- Preliminary paper execution with fixed-payout assumptions and deterministic tests.

V1 was recovered from the original local Git file-tree snapshot; it is not a second copy of V2. See `docs/VERSION_PROVENANCE.md` in V2.
