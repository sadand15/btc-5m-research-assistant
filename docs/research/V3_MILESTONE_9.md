# V3 Milestone 9 — Prospective Evidence Infrastructure

## Scope and preflight

Approved M8: `4dd8c798cac479ddd411cb69a7901fda6e0f8136`, branch `v3-dev`, clean before M9. M8 CI [37026115218](https://github.com/sadand15/btc-5m-research-assistant/actions/runs/37026115218) succeeded on Windows and Linux. Frozen V2 main `11c7d06b988b9177f84cf0f34920ad38c4021add`, annotated frozen tag object `fa9757a2e3fd132121a7c7e85307553b1f008a29`, and the original 27 protected hashes are unchanged. M9 adds a lock over 95 approved M1–M8 source/contract files; no prediction, model, calibration, threshold, execution or risk semantics are changed.

Legacy `btc5/forward.py` and `FORWARD_VALIDATION.md` were reviewed as source/design only. Future-window and source/config identity ideas were reused; the legacy seven-day policy, database coupling and performance report were not executed or reused. No V2 blind-performance payload was read. No real study was created, armed or collected. No M10 work, training, parameter optimization, live account connection or order submission.

## Delivered

- Immutable, future-aligned UTC study manifest with explicit VALIDATION / PROSPECTIVE role, original fixed window, approved baseline SHA and separate collector SHA, model/config/contract/source hashes and honest synthetic origin.
- Single-writer OS lock; append-only SQLite journals per bounded segment; deterministic event-key idempotence; conflict rejection; fsynced atomic segment publication; chain reconciliation and partial-file quarantine; canonical sealed index/root.
- Read-only latest Binance reference trades or current Predict.fun five-minute books. No source substitution, historical range backfill or secret persistence. Exact venue description/feed/mapping drift interrupts the original study.
- Independent 30-second heartbeat while a source poll runs; separate source failure and unexplained collector silence; preserved restart/tail gaps, new-event slot/cycle coverage, explicit unknown source/clock states and no fabricated downtime observations.
- Read-only operational CLI and independent Streamlit page, with no performance/report imports. A verified sealed adapter preserves actual source evidence and gives unchanged M8 data-quality checks explicit missing-input failures.
- Non-root, read-only-root Docker/Compose with persistent volume, restart policy, signal stop, bounded logs, UTC, operational healthcheck and no `.git`/credentials in the image.

Code is isolated in `src/btc5_v3/prospective/`; existing domain files remain unchanged. Supporting changes: `prospective_app.py`, `deployment/prospective/`, `.dockerignore`, CI, package version, README, database/architecture/roadmap docs and synthetic tests. The exact changed-file inventory and commit SHA are available in the final Git commit/delivery record; they are not self-referentially embedded here.

## Validation evidence

Local Windows full suite: **742 passed, 2 skipped**, including **44 M9 tests**. They cover immutable/future windows, duplicates/conflicts, normal hourly rollover, restart, explicit/unknown downtime, continuing heartbeat during source failure, partial transaction rollback, post-commit and post-rename crashes, temporary-file recovery, missing/tampered/reordered segments, changed baseline, rule drift, pre-window/stale/future timestamps, reverse local clock, path/lock isolation, secret redaction, sealed immutability, M8 candidate quality protocol, forbidden early/blind access, seal retry and deterministic demos.

The **16-case synthetic demo passes**: create/freeze, multiple segments, restart, duplicate retry, collector outage, network outage, partial crash, baseline change, tamper, missing segment, window-end rejection, sealed root, sealed write refusal, sealed adapter acceptance, unsealed rejection and peeking guard. Synthetic cases are infrastructure proofs, not market-behavior or profitability evidence.

CI runs the complete suite, all M1–M8 demos, M9 demo, index/history credential scans on both Windows and Linux. Linux additionally builds the Docker image and runs its demo with `--network none`. Local Docker smoke was unavailable because the installed Docker Desktop engine was stopped; no successful local image run is claimed. Final CI status is verified against the delivered commit in GitHub Actions and reported separately; exact job test counts are stated only when actual logs are accessible, otherwise unavailable.

## M8 adapter boundary

SEALED + original window ended + immutable VALIDATION role + verified manifest/baseline/segment chain are required before payload access. The candidate keeps PROSPECTIVE provenance and all original gaps. It does not relabel real data SYNTHETIC. Price/book-only evidence lacks M8's archived synthetic model/settlement binding; readiness is **NOT_REPLAY_READY_M8_BINDINGS_REQUIRE_EXPLICIT_RESEARCH_ADAPTER**. Existing data-quality checks accept the protocol and correctly flag missing required inputs. No automatic validation/performance analysis is run; building a real compatible prediction/settlement adapter requires a subsequent explicit task.

## Operational qualifications

Polling is not full exchange-event coverage. Repeated unchanged source events are deduplicated; missing new-event slots do not alone prove network downtime. Missing slot intervals can overlap known cause-specific gaps and must not be summed as exclusive downtime. Heartbeat slots are only bounded evidence of process/write activity. Source time offsets remain UNKNOWN without independent clock evidence. SQLite/fsync tests do not certify hardware power-loss guarantees. Exact rule-description pinning may stop a study on benign description changes. No fees, latency, fill-quality or live profitability assumption is validated by M9.

Use the [runbook](../../PROSPECTIVE_COLLECTION.md) for the exact create, arm, collect, status, stop/restart, end, seal, verify, adapter and always-on commands. The first real study remains uncreated pending subsequent user approval. M9 stops after delivery; M10 is not started.

## Required limitations

M9 provides prospective evidence collection infrastructure.

It does not itself provide out-of-sample evidence, live profitability evidence, or real execution-quality proof.

Downtime cannot be retroactively reconstructed as genuine real-time market observations.

Hashes provide integrity evidence, not external authenticity.

A prospective dataset becomes eligible for final validation only after its prespecified window ends and the dataset is sealed.
