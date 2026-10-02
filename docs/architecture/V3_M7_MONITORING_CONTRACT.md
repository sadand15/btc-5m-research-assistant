# M7 Monitoring Contract

Version: `monitoring-v1`. This contract precedes implementation. M7 is a read-only observation layer over the approved M6 schema-7 archives. M1–M6 domain behavior is frozen.

## Scope and read-only boundary

Reuse Streamlit in an independent V3 entrypoint. No import of the legacy dashboard, production config or live services. Monitoring never instantiates writing repositories, migrates schemas, calls prediction/decision/risk/execution engines, creates timer events, resets latches or repairs records. No trading, optimization, training or M8 work.

Use SQLite `mode=ro`, `query_only=ON`, an authorizer denying writes and reads outside six named tables, and a consistent read transaction. Keep normal WAL read visibility; do not use `immutable=1`, which could hide uncheckpointed research events. SQLite reader coordination is not a domain write. Tests compare primary DB bytes, schema and research rows across startup/refresh. Opening a missing DB does not create it. StorageConfig's V3 path isolation remains in force; no original V2 database is opened.

## Sources and evidence

Allowlist: `experiments`, `risk_runs`, `risk_events`, `risk_decisions`, `capital_reservations`, `portfolio_snapshots`. No generic table browser, whole-DB integrity scan, standalone performance aggregate, blind table query or arbitrary SQL API. M1 prediction/snapshot/edge/M3 decision and M5 execution/ledger are available in explicit M6 archives; monitoring uses these exact recorded inputs/outputs. M4 calibration version metadata may be displayed; M4/M4.5 analytical results absent from this archive are NOT RECORDED, never recalculated.

Only the explicit `M4_SYNTHETIC_ARCHIVE_V1` experiment contract is currently supported. It means SYNTHETIC evidence, including historical inspection of that evidence. Unknown contracts are unavailable, never guessed REAL from a path or user label. Historical navigation is separately marked AS-OF REPLAY. One selected risk run is one portfolio; multiple independent runs are never summed.

## View models and capital

Frozen canonical JSON view envelopes contain Overview, Health, Risk, Permissions, Reservations (including every revision), Positions, Executions, Ledger, Timeline, Diagnostics and Provenance. Returned data are detached copies; UI contains no SQL or domain policy. UNKNOWN/UNAVAILABLE is represented by null with a reason, not zero.

Capital values are copied from the latest intact M6 state at or before the requested time: cash, available cash, reserved cash, open acquisition-cost exposure, pending exposure and cost-basis equity. `AvailableCash=Cash-ReservedCash`; `Equity=Cash+OpenExposure`. Never add reserved cash to equity again. No MTM, mid-price equity, liquidation estimate or unrealized PnL.

## Risk and health

Display recorded M6 daily net loss and daily maximum loss/latch, drawdown/peak, completed loss streak, config limits, controls and trigger evidence. Daily reset, persistent financial latch and transient/manual pause are separately labeled. No reset controls. Between recorded M6 events the panel remains LAST RECORDED STATE with its timestamp; crossing midnight does not invent an M6 reset event. Stale historical state is labeled, never silently recalculated into a fresh approval state.

Health is observation of archived evidence, not a live provider probe. Each status includes source/time/age/reason. HEALTHY requires explicit positive evidence; UNKNOWN is not healthy. STALE uses the archived M6 age limits; PAUSED is a recorded control; DEGRADED describes failed gates or incomplete/corrupt observation evidence. Overall completeness of the upstream collector is UNKNOWN even when the selected archive prefix is intact. Spread/depth health uses recorded M3 gate status, not newly chosen thresholds.

## Permissions, reservations and positions

Show original M3 IDs, side, gate/reason evidence, M6 action, exact requested/approved amounts and stored reason precedence. Do not explain historical refusals using later PnL. Reservation revisions retain original status and amounts; RELEASED with `release_reason=RISK_PAUSE` is displayed as that recorded status/reason, not a fabricated REVOKED enum.

Positions link permission/reservation/execution. Pending permission is not a filled position. Initial net inventory, actual exits and settlements come from recorded M5 accounting/ledger. Remaining acquisition basis may be reconciled from recorded movements using the M6 proportional-basis and final-residual rule; this is display arithmetic, not rerunning execution or risk. Same-market YES/NO remain gross. Unknown/corrupt references produce diagnostics and unavailable derived values.

## Execution, ledger and reconciliation

Show approved versus attempted/filled/unfilled size, ASK/BID legs, entry/exit prices, fees in original collateral/share units, recorded latency, original exit policy and settlement. Use latest visible M5 prefix per permission; deduplicate stable ledger IDs across repeated cutoff archives. Historical execution archives remain inspectable through timeline/source event IDs. Never rerun M5.

Audit existing arithmetic: per-asset double-entry balance, inventory conservation, CASH flows and M6 cash/reservation/equity reconciliation. RECONCILED means the displayed recorded prefix reconciles, not real fill evidence. Missing prerequisites = INCOMPLETE; arithmetic conflict = MISMATCH; malformed/hash/projection/reference corruption = CORRUPTED. No mutation or automatic repair. Running balances are derived from recorded CASH legs in deterministic event order, not replacements for the ledger.

## Timeline, as-of and filters

SQL selects only risk events with `at <= view_as_of`; visible nested events must also have their own timestamp <= that cutoff and their containing archive must already be available. Future input book/outcome archives are never exported to UI. Metadata about an expiry/deadline is a known future schedule, not a future event. Past views cannot use later projection revisions or final position state.

Timeline order is `(timestamp, risk event sequence, category, source ID)` with explicit source references; stable duplicates from M5 prefixes are emitted once. Prediction and candidate times remain original, while their archive availability is recorded separately. Filters affect displayed rows only; portfolio capital remains clearly labeled SELECTED RUN TOTALS. Filters include range/as-of, market/candidate, permission/reason, reservation/execution, position status, health and guard. Pagination defaults to 50 rows, capped at 200; timeline and source-event budgets are bounded. Source limits are 1000 events by default (maximum 5000), 4 MiB per payload and 64 MiB combined payloads; six SELECT queries fetch a view without per-row queries. A source prefix beyond the budget yields explicit INCOMPLETE, not a silently truncated portfolio total.

## Integrity, corruption and security

Check canonical input/output hashes, event chain/sequence, run/experiment identity, stored projection hashes/content/counts and business references without domain replay. One malformed row does not crash the UI; diagnostics identify fixed error type, table/source, safe record ID, timestamp and severity. Dependent aggregates become unavailable when trust is broken; intact prefix evidence is retained and marked. Hashes are not signatures against a full administrator rewrite.

Never return raw exception text or arbitrary raw database payloads. Recursively redact credential-key fields and recognizable credential/header patterns in every view/export/diagnostic. Unknown payload fields are not promoted to UI facts. No API key is required or loaded. Regression includes corrupt payloads with secret-like fields and values.

## Provenance and restart

Report recorded source Git SHA, schema version, risk/execution config hashes, experiment/data version and observed M1/M2/M3/M5/M6 versions. Missing historical branch, M4/M4.5 analysis version or other provenance is UNKNOWN. Viewer Git/branch is separately identified and must not impersonate source provenance. `generated_at` is the explicit logical as-of time for deterministic output, not a claim about wall-clock processing time.

No process-only portfolio state or dashboard cache is authoritative. Reload reconstructs identical views from the same read transaction/prefix and explicit filters. No expensive M5/M6 simulation replay on refresh. The offline demo may create **new synthetic fixtures only in its own ignored `runtime/v3/m7-dashboard/` directory**, using unchanged M6 APIs before opening the monitoring reader. Dashboard startup itself never creates these fixtures.

## Limitations and non-goals

Schema 7 and explicit synthetic M6 archives only; missing standalone M4/path results remain unavailable. Bounded local research data, no production-scale claim. No live health probe or complete realtime equity. No real accounts, trading controls, strategy/parameter mutation, blind performance reading or M8.

M7 provides monitoring and observability only.
It does not demonstrate real profitability, real execution quality,
optimal risk parameters, or safety for live trading.

M5 = execution simulation; M6 = portfolio/risk permission; M7 = monitoring/observability. Synthetic/replay evidence is not real market execution evidence.
