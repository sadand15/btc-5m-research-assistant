# M9 Prospective Evidence Contract

Version `prospective-v1`; approved M8 `4dd8c798cac479ddd411cb69a7901fda6e0f8136`. Contract written before implementation. M9 collects evidence, not orders or performance; M10 is not started.

## Legacy review and frozen boundary

`btc5/forward.py` supplies useful historical ideas: explicit future cycle boundary, fixed end, policy/model/source hashes, overwrite refusal and no backfill. It is not imported as a collector: it binds legacy ROOT/database, a seven-day window and a performance-report path, lacks restart-safe segmented sealing and does not satisfy M8 roles. Its `report` is never run. The existing pure Predict.fun binding/GET-only client may be reused as a transport, with fresh rule verification and an environment-only key; legacy databases/config/model loading are not used.

M1–M8 domain source and specific contracts remain byte-equivalent after LF normalization, checked against an approved Git-derived lock. No model artifact exists for M8's explicit archived synthetic prediction input; record model contract hash/version and `artifact=NOT_APPLICABLE`, never copy V2's model or invent live predictions. Freeze complete M8 configuration hashes including prediction binding, decision template, edge, calibration, execution and risk.

`baseline_git_sha` is always the explicitly approved M8 SHA, never latest HEAD. Collector SHA is separate: a clean descendant with unchanged locked M1–M8 files is eligible as evidence-only code. This distinction and rationale are frozen in the manifest. Each startup and each 30-second heartbeat rechecks domain/config/contract hashes and collector source identity. A change appends INTERRUPTED/BASELINE_CHANGED and stops; no automatic re-arm or baseline replacement.

## Definition, lifecycle and window

Create DRAFT with unique safe study/dataset ID and explicit source specification. Arm freezes a separate canonical manifest, including created_at, armed_at, UTC, role VALIDATION, evidence mode PROSPECTIVE, collection origin (REALTIME or SYNTHETIC_TEST), start/end, baseline/collector/config/contract identities, rule/feed profile and policies. Test clocks/sources are visibly SYNTHETIC_TEST and never real future evidence. Start is strictly after arm and creation, normally next complete 300000-ms boundary; end is prespecified, exclusive. No observations before start or at/after end. No window edit/extend APIs.

DRAFT → ARMED → COLLECTING → WINDOW_ENDED → SEALED. DEGRADED is a recoverable source-health state during collection; INTERRUPTED is a terminal collection stop for baseline/rule change or explicit stop (restart after an explicit stop is allowed only with unchanged identities and within the original window). INVALID represents integrity failure and cannot collect/seal. State changes are append-only control events, separate from the immutable manifest. No write is accepted after seal, including heartbeat/state/dedup retry. Status/verify remain read-only. Window-ended state can be recorded after an interruption without erasing that interruption.

## Observations, source and time

Record raw **safe allowlisted** evidence, not only candidates: source key/type, source_at, received_at, processed_at, market/cycle IDs, price/depth/rule/feed, optional actual archived prediction, quality diagnostics and source health. UTC epoch ms throughout. Received time is local response receipt, processed time is local persistence attempt; neither is substituted for source time. Missing source time is UNKNOWN. Negative latency, future source time, old source state and backwards local time are explicit diagnostics; never silently adjust timestamps. Clock offset evidence may be recorded separately when provided; otherwise UNKNOWN.

Only actual new live responses are admitted; no historical range request or backfill. A source event preceding start is retained as a diagnostic receipt, not counted as a prospective market observation. Polling coverage is not complete exchange tick coverage. Binance reference aggregate-trade polling is public market data, not venue quotes; Predict.fun uses the existing read-only GET transport and pins description/feed/outcome mapping. Rule drift interrupts before accepting the mismatched book. No source substitution on error. Unknown fields, headers and credential-shaped values are discarded/redacted before disk; exceptions become fixed reason codes.

## Heartbeat and gaps

Heartbeat cadence 30000 ms; records process alive, source connection status, last market/venue receipt, dataset, baseline check and committed storage write evidence. Heartbeat is not market evidence. A resumed collector opens a new segment and records unaccounted heartbeat slots from the last heartbeat (or start) to resume. Unexpected silence is UNKNOWN, not guessed power loss; explicit stop can be COLLECTOR_DOWN. Source/network failure intervals are recorded independently with last known evidence, detection/resume and fixed reason; they are not confused with a dead collector.

Gap ledger records ID, source, expected_start, observed_resume, duration, type, reason, detected_at and last heartbeat. Gaps never disappear. Tail gaps at window end are included. Coverage reports unique observed 5-minute cycles against elapsed scheduled cycles, per source; missing polls are separate from missing cycles. Heartbeat-observed uptime sums bounded, nonoverlapping heartbeat slots, not proof of uninterrupted host uptime. Missing event slots with continuing heartbeat are NO_EXPECTED_EVENT (or SOURCE_STALE/known network failure), not fabricated observations.

## Storage, canonical hashing and crashes

All files stay under an isolated `runtime/v3/prospective/<study>/` path, with existing path/symlink/hardlink protections. One writer holds an OS-backed lock for its lifetime; process death releases it. Each bounded segment has a separate SQLite append-only journal (FULL synchronous transactions). Segments close at the hourly boundary or at restart/end, whichever comes first. The small control journal stores only append-only state and finalized segment references; it is not a single accumulating observation database.

Each observation/heartbeat/gap/diagnostic commits atomically to its current journal before acknowledgement. Stable `(source,event_key)` IDs and safe payload hashes make retries idempotent; changed content under the same identity fails. Duplicate delivery timestamps do not replace the first receipt. SQLite rollback handles partial transactions; an unacknowledged committed event is found on retry. No committed row is deleted or rewritten.

Finalization serializes ordered committed rows with the project's canonical encoding, UTF-8 and deterministic LF-independent bytes. Header includes sequence/segment ID, policy boundary, observed first/last time, count, content SHA256, previous segment hash, baseline and schema. Write temporary file, fsync, atomic rename, then register its hash in the control journal. An orphan finalized file is adopted only if it exactly matches the journal and expected previous hash; a partial temporary file is quarantined and diagnosed, never treated as sealed evidence. Missing/tampered finalized files, reordered chains or journal mismatches fail verification. Restart validates the complete chain, not just the newest filename.

## Seal and integrity

Only at/after the fixed end: enter WINDOW_ENDED, account tail gaps, finalize the last segment, verify every journal/segment/manifest and baseline, then atomically write a canonical immutable dataset index/root. Root is SHA256 over the ordered segment hashes and manifest hash plus fixed window/count/coverage metadata. Sealed-at is explicit UTC. Seal retries return the same verified index; all mutation paths subsequently fail. Pending seal files are not sealed. No automatic performance analysis follows sealing.

Hashes detect inconsistent changes, not an administrator who rewrites every hash or a dishonest external feed. No external timestamp authority/authenticity claim. SQLite/filesystem fsync behavior depends on host/disk; abrupt power-loss tests exercise transaction/finalization boundaries, not hardware guarantees. Retain journals for reconciliation; finalized JSON segments are independently inspectable.

## M8 adapter and no peeking

Adapter accepts only verified SEALED, role VALIDATION, original window ended, approved baseline-matching datasets. It preserves PROSPECTIVE metadata, source timestamps, original safe payloads and gaps. It does **not** relabel real prices as SYNTHETIC or generate predictions/outcomes. It presents an M8-compatible dataset protocol for quality inspection; exact M8 baseline replay readiness is separately reported. Current M8 requires a synthetic model/source/settlement binding, so real reference/venue-only evidence is accepted as a final validation **candidate**, but missing/incompatible Prediction/settlement evidence remains NOT_REPLAY_READY. Changing those domain bindings is outside M9. Compatible archived inputs can use unchanged M8 functions only through a later explicitly requested analysis. Existing synthetic M8 outputs remain identical.

Collection status, CLI and independent read-only prospective page expose only definitions, baseline, timestamps, counts, cycles, coverage, bounded heartbeat uptime, gaps, sources, integrity and seal status. They never call M8 validation/performance functions or reveal probability/edge/PnL aggregates. The M7 eleven-page entrypoint stays unchanged; prospective UI is an independent read-only view. No tune, extend, delete, promote or trading control.

## Operations and security

Ship UTC Docker/Compose with persistent mounted runtime, read-only root filesystem, non-root user, restart policy, bounded logs, graceful signal stop and operational heartbeat healthcheck. Container code identity is built from approved lock and explicit collector SHA; deployment does not purchase or access a server. No real study is created/armed/launched by M9 development; only synthetic tests/demo run. First real study requires the user's later explicit approval.

Predict.fun key is read only from `PREDICTFUN_API_KEY` by its read-only transport. DO NOT USE WITHDRAWAL/TRADING PERMISSIONS. No order endpoints or wallet code. Failures never dump responses/headers/exceptions containing secrets. Public reference source requires no key. CI is synthetic/network-fake only; Docker smoke does not contact a market.

M9 provides prospective evidence collection infrastructure.
It does not itself provide out-of-sample evidence, live profitability evidence,
or real execution-quality proof.
Downtime cannot be retroactively reconstructed as genuine real-time market observations.
Hashes provide integrity evidence, not external authenticity.
A prospective dataset becomes eligible for final validation only after its
prespecified window ends and the dataset is sealed.
