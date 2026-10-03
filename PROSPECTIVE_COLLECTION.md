# Prospective collection runbook (M9)

Infrastructure only. **No real study was created or armed during M9 development.** First real study requires the user's subsequent approval. Use a separate `v3-dev` clone or the isolated worktree, never the frozen V2 directory. No commands below analyze performance or submit orders.

## Identity and installation

Python 3.12, clean committed M9 source, and the explicitly approved M8 ancestor `4dd8c798cac479ddd411cb69a7901fda6e0f8136` are required. The manifest records that ancestor separately from the actual M9 collector commit, with hashes of 95 approved domain files/contracts and all M8 configuration bindings. Every startup/heartbeat verifies them. The collector uses no V2 model, config, database or blind observations.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
.\.venv\Scripts\python.exe -m btc5_v3.prospective.demo --project-root .
```

The demo is entirely synthetic, marks its origin `SYNTHETIC_TEST`, runs 16 deterministic cases, and removes its temporary studies. It is not prospective OOS evidence.

## Create and arm a real study (after approval)

Choose one explicit source. `binance` polls the newest BTCUSDT aggregate trade only (public, no key). It is an underlying reference, **not a Predict.fun quote**. `predictfun` polls actual current BTC five-minute YES books with an environment-only `PREDICTFUN_API_KEY`. Provision that variable through your host's secret manager; never put its value in a command, JSON, repository, log, Docker image or manifest.

These are exact executable Windows commands from the clone root. The first create defaults to the second upcoming full five-minute boundary, providing 5–10 minutes to arm; the fixed duration is 24 hours. If that deadline is missed, use a new study/dataset ID, never edit the old manifest. Explicit start example syntax is `--start 2027-01-01T00:00:00Z`; choose a genuinely future boundary.

```powershell
.\.venv\Scripts\python.exe -m btc5_v3.prospective --project-root . --study prospective-001 create --dataset prospective-001-validation --source predictfun --duration-hours 24
.\.venv\Scripts\python.exe -m btc5_v3.prospective --project-root . --study prospective-001 arm
.\.venv\Scripts\python.exe -m btc5_v3.prospective --project-root . --study prospective-001 collect
```

For a reference-only study, use a **different** ID and `--source binance`. Never substitute a source inside an armed study. Predict.fun create makes read-only discovery requests to freeze the exact description hash, feed, outcome mapping, cycle and fee metadata. Missing rules or auth fail closed. Rule drift terminates collection; a changing description (even formatting) may intentionally require a new study. The hash is not independent verification of oracle correctness or economic settlement semantics.

Sources: [Binance official public market-data host](https://developers.binance.com/en/docs/products/spot/rest-api), [Predict.fun official orderbook endpoint](https://dev.predict.fun/get-the-orderbook-for-a-market-25326908e0). Polling retains received source timestamps and local receipt/processing times; it does not claim full exchange tick coverage. Binance requests no historical range. Predict.fun does no wallet access, signing, order placement or settlement-performance computation.

## Status and safe stop/restart

In another terminal:

```powershell
.\.venv\Scripts\python.exe -m btc5_v3.prospective --project-root . --study prospective-001 status
.\.venv\Scripts\python.exe -m btc5_v3.prospective --project-root . --study prospective-001 verify
.\.venv\Scripts\python.exe -m streamlit run prospective_app.py --server.address 127.0.0.1 --server.port 8504
```

The independent page takes a study ID and displays operational fields only. It does not change M7 or open V2. No predictions, edge, PnL, ranking or performance aggregates are exposed. Status/verify are read-only. Status includes last heartbeat/observation, clock age, counts, unique cycle/receipt-slot coverage, missing slots, gaps, source state and integrity. Heartbeat uptime is bounded observed slots, not proof of continuous host uptime. A duplicate source event is not an additional observation; unchanged markets can therefore have missing new-event slots even with healthy HTTP requests.

Use Ctrl+C for a graceful stop. Restart with the **same collect command**, original source/config/commit and original window. OS locking blocks a second writer. Restart validates the chain, reconciles the committed journal, closes the prior segment and starts a new one. Explicit stopped intervals are `COLLECTOR_DOWN`; unexplained silence is `UNKNOWN`. Connection failure intervals remain distinct from collector silence. `NO_EXPECTED_EVENT` intervals are finalized at window end and may overlap other cause-specific gaps; do not sum overlapping gap durations as exclusive downtime.

Do not edit, delete, truncate, rename or repair evidence files in place. Stop on INVALID and preserve the directory for diagnosis. Failed baseline/rule checks are terminal within the original window. SQLite transactions handle partial rows; incomplete publication files are quarantined and diagnosed. A crash may lose an unreceived or uncommitted response: it stays missing, never fabricated or backfilled.

## Window end, sealing and M8 candidate

Collection stops admitting observations at the fixed exclusive end. No auto-analysis or auto-window extension follows. After the window ends and the collector has exited:

```powershell
.\.venv\Scripts\python.exe -m btc5_v3.prospective --project-root . --study prospective-001 end
.\.venv\Scripts\python.exe -m btc5_v3.prospective --project-root . --study prospective-001 seal
.\.venv\Scripts\python.exe -m btc5_v3.prospective --project-root . --study prospective-001 verify
.\.venv\Scripts\python.exe -m btc5_v3.prospective --project-root . --study prospective-001 adapter
```

Seal finalizes all segments and tail gaps, verifies the complete chain and immutable manifest, and writes a canonical dataset root. Repeating seal returns the same verified root. All later mutation APIs refuse. Keep the **entire** `runtime/v3/prospective/prospective-001/` directory (manifest, journals, registry, segment JSON, sealed index and quarantines) on persistent storage and back it up after graceful stop/seal. Runtime is excluded from Git and Docker build contexts.

`adapter` accepts only verified, ended, SEALED VALIDATION datasets and preserves PROSPECTIVE metadata. It returns a candidate/readiness status, **not an M8 performance report**. Current real source records lack M8's frozen synthetic prediction/settlement binding: `NOT_REPLAY_READY_M8_BINDINGS_REQUIRE_EXPLICIT_RESEARCH_ADAPTER`. Python `load_sealed` exposes the existing M8 data-quality protocol; missing required inputs are reported INVALID by that checker. It never relabels real data SYNTHETIC or manufactures predictions. A subsequent explicit research task is needed for a compatible domain adapter. BLIND inputs are rejected before payload access.

## Always-on host (Docker Compose)

Use a separately managed always-on Linux host with reliable UTC/NTP, storage and network; no server was purchased or deployed by M9. This avoids dependence on the personal PC. Run from a clean committed clone. Set `COLLECTOR_SHA` to the exact checked-out M9 commit and `STUDY_ID` to a new ID. Image build copies no `.git`, credentials, runtime or `.env`. The build stamp binds collector SHA and source hashes, not external authenticity.

```sh
export COLLECTOR_SHA="$(git rev-parse HEAD)"
export STUDY_ID=prospective-001
docker compose -f deployment/prospective/compose.yml build
docker compose -f deployment/prospective/compose.yml run --rm collector python -m btc5_v3.prospective --project-root /app --study "$STUDY_ID" create --dataset prospective-001-validation --source predictfun --duration-hours 24
docker compose -f deployment/prospective/compose.yml run --rm collector python -m btc5_v3.prospective --project-root /app --study "$STUDY_ID" arm
docker compose -f deployment/prospective/compose.yml up -d
docker compose -f deployment/prospective/compose.yml exec collector python -m btc5_v3.prospective --project-root /app --study "$STUDY_ID" status
docker compose -f deployment/prospective/compose.yml stop
```

Provision the key in the host environment before Predict.fun create/run; public Binance collection needs none. The named `evidence` volume persists across restart/recreate. Do **not** use `down --volumes`. The container runs as UID 10001 with read-only root, `/tmp` tmpfs, dropped capabilities, bounded logs, 30-second healthcheck and restart policy. A Docker healthcheck flags degradation; Docker restart policy only restarts an exited process, not merely an unhealthy one. At window end stop the service to avoid repeated exited-process restarts, then run `end`, `seal`, `verify`, `adapter` through `compose run --rm` as above. A planned code update requires a new study: do not rebuild the active collector under the same identity.

## Limits

M9 provides prospective evidence collection infrastructure.
It does not itself provide out-of-sample evidence, live profitability evidence, or real execution-quality proof.
Downtime cannot be retroactively reconstructed as genuine real-time market observations.
Hashes provide integrity evidence, not external authenticity.
A prospective dataset becomes eligible for final validation only after its prespecified window ends and the dataset is sealed.
