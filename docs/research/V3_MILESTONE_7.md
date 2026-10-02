# V3 Milestone 7 — Monitoring, Observability & Research Dashboard

## Scope and preflight

Approved M6 baseline: `1b4594c7a64389aa1f209d98860e315f3c651002`, branch `v3-dev`, initially clean. Its [Windows/Linux CI](https://github.com/sadand15/btc-5m-research-assistant/actions/runs/36536225465) was verified successful before implementation. The M7 monitoring contract was written before code.

Original V2 main remains `11c7d06b988b9177f84cf0f34920ad38c4021add`; frozen tag object remains `fa9757a2e3fd132121a7c7e85307553b1f008a29`. All 27 protected files match the original `runtime/m0-safety.json`. No V2 observation database or blind performance was read. M1–M6 source, model, calibration, thresholds and risk parameters are unchanged.

## Implementation

An independent Streamlit entrypoint provides Overview, System Health, Risk, Permissions, Reservations, Positions, Executions, Ledger, Timeline, Diagnostics and Provenance. Every view is marked RESEARCH MODE / READ ONLY with explicit evidence mode and as-of time. The only actions are read-only refresh, navigation, filters and sanitized export.

The UI calls MonitoringService and immutable canonical MonitoringView objects. ReadOnlyQueries opens an existing schema-7 database using SQLite read-only mode, query-only, an authorizer and a consistent WAL-aware read transaction. Six allowlisted tables supply one explicitly selected synthetic M6 run; no arbitrary SQL, blind table access, migration or repair exists. Refresh invokes neither M5 simulation nor M6 risk replay.

The service verifies event chains, canonical hashes, projection contents/counts, source identities and recorded M5 ledger arithmetic. It displays original permission reasons and reservation revisions. Capital follows M6 exactly: available cash = cash minus reserved cash; equity = cash plus remaining acquisition basis. Reserved cash is not added twice; same-market opposite sides remain gross. Completed/partial/pending positions are distinct.

Historical views select only archives already available at the cutoff. Future loss, fill, settlement, health and latch events cannot change past views. Between recorded M6 events, the UI shows LAST RECORDED STATE and does not invent midnight resets or timer events. Event timelines retain source references, deterministic ordering and stable-ID deduplication. Filters change detail rows, not the explicitly labeled selected-run capital totals.

Malformed JSON, unknown enums, missing references, mismatches, unsupported schemas, budget truncation and unavailable sources yield safe diagnostics or UNKNOWN values. Invalid health never becomes healthy merely because wall-clock time advances. Corrupt state cannot be displayed as inactive risk guards. Sensitive fields and recognizable credential values are recursively redacted in views, exports and diagnostics; exception messages are not exposed.

## Synthetic demo

`python -m btc5_v3.monitoring.demo --project-root .` requires a clean commit. It first creates isolated synthetic fixtures using unchanged M6 APIs, closes the writer, then exercises read-only monitoring. Dashboard startup itself never creates fixtures. Outputs are ignored under `runtime/v3/m7-dashboard/`: `demo.sqlite`, `m7-report.json`, `m7-report.md`. Reports include actual source commit, config hashes, provenance, original evidence and view hashes.

| Case | Evidence shown |
|---|---|
| A | APPROVE and full recorded fill; reconciled ledger/capital |
| B | Requested budget 180 reduced to 100, original reason preserved |
| C | Cash 100, reservation 80, competing request 50 reduced to 20 |
| D | Reserve 100, actual spend 60, release 40, partial IOC fill |
| E | Daily-loss pause rejects new risk; an existing position can partially exit and settle |
| F | Cost-basis equity drawdown activates the original recorded guard |

All six fixtures pass in tests with zero diagnostics and RECONCILED status. Repeated/restarted views are identical; primary database bytes are unchanged by monitoring. The CLI additionally runs in Windows/Linux CI against the exact checked-out commit. These are synthetic assertions, not real-market performance evidence.

## Validation and delivery evidence

Local full regression: **647 passed, 2 skipped**, including **67 M7 tests**. Coverage includes all 11 Streamlit pages, repeated refresh, actual headless HTTP startup, missing database without creation, as-of causality, event ordering, all detail filters, permissions/reasons, reservations, positions, ledger conservation, daily/persistent/transient controls, restart determinism, source immutability, WAL visibility, six-query budget, byte limits, malformed inputs, credential redaction and blind-table isolation. Existing M1–M6 tests continue unchanged.

The credential scan initially matched a source expression constructing a synthetic credential URL. Its assembly was rewritten without changing the test value; rescanning M7 files found no findings. Reachable pre-M7 Git history also had zero findings. The staged index and final reachable history are scanned again at delivery. No real key was added to M7.

The CI matrix remains Python 3.12 on Windows and Linux. Both jobs run the complete tests, all M1–M7 demos and index/history scans without real API credentials. This document is committed before that run: final CI status, exact M7 SHA and final frozen-reference recheck are reported with the delivery, rather than predicted here. Inspect the [v3-dev Actions runs](https://github.com/sadand15/btc-5m-research-assistant/actions?query=branch%3Av3-dev) for the delivered SHA. Existing baseline skip differences depend on the host platform; skips are not silently counted as passes.

## Changed files and review entrypoints

- `src/btc5_v3/monitoring/`: immutable models, queries, audit, diagnostics, provenance, service, dashboard, report and demo. Start with `queries.py`, `audit.py`, `service.py` for the trust boundary.
- `tests/v3/test_v3_monitoring.py`: synthetic-only regression and UI/HTTP checks.
- `docs/architecture/V3_M7_MONITORING_CONTRACT.md` and this report: contracts, evidence and limitations.
- README, V3 architecture/database/roadmap, package version 0.7.0 and CI: usage and delivery integration. Schema stays 7; no M7 database tables.

## Limitations and unverified assumptions

Only explicit `M4_SYNTHETIC_ARCHIVE_V1` M6 archives are currently supported. Unknown experiment contracts are unavailable, never relabeled real. One risk run is one portfolio; independent counterfactual runs are not combined. Recorded source Git SHA and config hashes are shown separately from viewer provenance. Historical source branch or unrecorded versions remain UNKNOWN.

M4/M4.5 results absent from these archives remain NOT RECORDED. No new calibration/path/performance analysis is run by monitoring. Upstream collector completeness remains UNKNOWN. Health represents archived evidence, not live provider probes. Cost-basis equity is not mark-to-market; this is not complete real-time account equity. Hashes detect inconsistent archives, not an administrator who rewrites every hash. Bounded reads explicitly stop at configured budgets; production-scale responsiveness is unverified. SQLite WAL reader coordination is not a domain write.

M7 provides monitoring and observability only.
It does not demonstrate real profitability, real execution quality,
optimal risk parameters, or safety for live trading.

M5 = execution simulation; M6 = portfolio/risk permission; M7 = monitoring/observability. **STOP: M8 is not started.**
