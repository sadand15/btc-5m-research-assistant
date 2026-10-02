# V3 Milestone 8 — Data Quality, Validation / Replay, Research Robustness

## Scope and preflight

M8 follows the user's approved research scope, replacing the older deployment proposal. It adds no deployment, live feed, model, strategy, account, wallet or production control. M9 is not started.

Approved M7 baseline: `e4b67ed728073864a6cc809d26ad6f23c822c973`. Preflight verified clean `v3-dev`, exact local/remote HEAD, and successful [M7 Windows/Linux CI](https://github.com/sadand15/btc-5m-research-assistant/actions/runs/36987931150). M1–M7 contracts, schema, domain interfaces and prior tests were inspected before implementation. The M8 research contract preceded code; quality gate tests preceded replay and robustness work.

V2 main remains `11c7d06b988b9177f84cf0f34920ad38c4021add`; frozen tag object remains `fa9757a2e3fd132121a7c7e85307553b1f008a29`. The original 27 hashes in `runtime/m0-safety.json` matched at preflight and after implementation. No V2 database or blind performance was read. M1–M7 source files and expected test results remain unchanged.

## Architecture and frozen boundary

Explicit dataset manifest → role/hash/chronological checks → causal data quality → frozen baseline validation or development-only robustness → deterministic JSON/Markdown evidence. Separate modules are `data_quality`, `validation`, `robustness` and `m8`. There is no copy of the domain pipeline: replay calls original M1 validation, archived Prediction, M2 edge, M3 decision and M6 reducer, which calls original M5 execution. M4 calibration functions are reused without fitting.

The immutable Baseline binds approved source SHA, model/feature hash and version, calibration version, full decision template, EdgeConfig, ExecutionConfig, ExitPolicy, RiskConfig and AnalyticsConfig. Validation rejects any different configuration; variants require DEVELOPMENT role. Prediction values are explicit archives, not new inference. The M7 UI remains unchanged; M8 is delivered through research reports.

Existing schema 7 is unchanged. Only the explicit demo writer creates a separate two-table M8 fixture catalog. Its reader uses read-only mode, query-only, an authorizer and a consistent transaction, checks manifest role before reading payload, then verifies canonical JSON and SHA256. Missing files are not created. BLIND payloads and unrelated tables cannot be read. No production repository is instantiated by replay.

## Track A — Data Quality

VALID / DEGRADED / INVALID / UNKNOWN are deterministic states from domain invariants and the documented M8 contract. Primary research accepts VALID only; a diagnostic ALL_ELIGIBLE cohort also includes DEGRADED. Invalid/unknown records never enter the reducer. Every exclusion retains safe record ID, source, timestamp and reasons. No PnL or outcome direction defines quality.

Coverage uses explicitly declared exact cadence slots, including leading/trailing gaps. Without a declared cadence, coverage is unavailable. Ages retain original M3/M6 definitions; prediction age has no invented threshold. Book age at availability and invalid follow-up evidence are separately audited without rewriting past decision quality. Future timestamps, invalid probabilities/depth/prices, stale state, missing inputs, cross-source skew and venue divergence are inspected. Divergence uses the first declared positive price as reference and a fixed 1% research warning threshold.

Reconstruction without ground truth is NOT VERIFIABLE. Statistical outlier screening is unsupported; inconvenient observations are not statistically filtered away. Missing execution/settlement evidence remains explicit. Quality cannot authenticate an external producer's data or prove source completeness without the declared cadence.

## Track B — Validation / Replay

Manifests explicitly identify DEVELOPMENT / VALIDATION / BLIND, time range, source, creation time, payload hash, evidence mode and quality status. Ordered development/validation ranges cannot overlap and cannot share market identities. Role is never guessed from path. Current adapter supports SYNTHETIC, consistent with existing M5 settlement semantics; real historical/OOS validation is not implemented or claimed.

One chronological queue carries decisions, known books and settlements through one in-memory portfolio per dataset/cohort. Future inputs never enter earlier decisions, executions, risk or regime labels. A failed execution trial cannot partly mutate the retained context. Original permissions, conservative cash reservations, fee units, fills, ledger and risk latches remain authoritative. Replay never creates a synthetic healthy heartbeat to bypass a guard.

Validation repeats both QUALITY_PASSED and ALL_ELIGIBLE baseline replay twice with fresh contexts, comparing full outputs, not only totals. Mismatch is a failure. PASS means evaluable and reproducible, not profitable; empty clean cohorts are INSUFFICIENT_DATA. Reports include counts, permissions/reductions/rejections, approved size, fill/partial-fill denominators, costs/fees, completed simulated PnL, risk transitions, calibration and edge. Regime results attribute the same portfolio replay and do not reset its history.

Contemporaneous spread, visible depth, TTE, probability, side, market and UTC-day groups are fixed. BTC volatility/trend/shock remain unavailable without a suitable causal series. No full-period statistic is backfilled into a decision.

## Track C — Research Robustness

Five fixed local minimum-edge values retain the baseline and both directions of perturbation. Count plateau/cliff/spike diagnostics retain every row. The single supported ablation removes only the copied absolute-spread restriction; other gates remain. Neither operation can replace or promote the baseline or run variants on validation data.

Seeded moving blocks of chronological market clusters preserve all observations within a market. Defaults: seed 42, 200 replicates, two-market blocks, minimum eight contributing markets. Percentile intervals and distribution summaries are conditional empirical estimates; insufficient samples have null intervals. Resampling does not claim to replay a portfolio under each sampled ordering. A periodic alternating fixture was unsuitable for testing random variation with block length two; the test fixture was corrected, not the inference method.

Feature dependence reports sample shares, absolute-edge contribution shares and Herfindahl concentration, not causal feature importance. Calibration drift reuses M4 payout Brier and binary-only ECE, including fixed groups and market-cluster Brier intervals. Development and validation windows stay fixed. The unified matrix includes dataset/hash/role × quality cohort × regime × baseline/variant × metrics and uncertainty.

## Deterministic demo

`python -m btc5_v3.m8.demo --project-root .` runs all twelve scenarios. `btc5_v3.data_quality.demo`, `btc5_v3.validation.demo` and `btc5_v3.robustness.demo` use the same complete fixture suite so track entrypoints cannot silently omit dependencies.

| Scenario | Assertion |
|---|---|
| Clean data | VALID and deterministic baseline replay |
| Missing/gap | Explicit cadence gap and exclusion audit |
| Stale data | DEGRADED, never assumed healthy |
| Timestamp violation | INVALID and excluded from primary replay |
| Venue divergence | Fixed-reference divergence detected |
| Replay determinism | Full fresh-context outputs agree |
| Regime split | At least two contemporaneous spread groups |
| Sensitivity plateau | All adjacent high-edge candidate/permission counts stable |
| Sensitivity cliff | Near-threshold candidate count discontinuity detected |
| Ablation | Copied spread restriction changes candidates, baseline stays intact |
| Bootstrap | Seeded market-cluster estimate is reproducible |
| Calibration drift | Fixed later synthetic window changes calibration as constructed |

The demo contains 23 development records (one declared missing slot) and 24 later validation records with different market IDs. Designed bad inputs are retained in the audit. These are constructed demonstrations, not unseen market evidence. All twelve assertions pass in tests, including rerun/restart byte-stable report hashes and unchanged source database bytes.

## Outputs and provenance

Only ignored `runtime/v3/m8/` receives `data-quality.json/.md`, `validation.json/.md`, `robustness.json/.md`, `summary.json/.md` and the isolated synthetic input catalog. Reports contain readable tables plus complete machine-readable evidence. FACT / ESTIMATE / UNCERTAINTY / LIMITATION are separated; no report picks a parameter or ranks variants by profit.

Provenance records actual analysis SHA/branch, approved baseline source SHA, dataset/manifest hash and role, quality contract hash, complete baseline/risk/execution hashes, analysis type/parameters, explicit seed and logical generated-at cutoff. Missing provenance is UNKNOWN. Redaction applies recursively before artifact writing; credentials are not required or loaded. Input files are never overwritten on a fixture conflict.

## Tests and security

Local full suite: **698 passed, 2 skipped**, including **51 new M8 tests**. Coverage includes quality classes, invalid values, coverage/gaps/staleness, future timestamps, role/hash/timesplit checks, deterministic candidates/permissions/executions/ledger, same-ms sequence, future loss/settlement isolation, quality cohort changes, regime counts, full grid, ablation isolation, bootstrap seeds/small samples/clusters, stable and changed calibration, concentration shares, read-only catalogs, forbidden blind table access, corrupt evidence, immutable old source, actual twelve-case demo, restart and redacted artifacts.

M8 source and reachable pre-M8 history scans found no credentials. The final staged index and reachable history are scanned again for delivery. The original V2 27 hashes match; regression explicitly compares all pre-existing domain source paths against the approved M7 commit. No old expected result is changed to pass M8.

## Windows CI / Linux CI and delivery record

The Python 3.12 matrix on Windows and Linux runs full pytest, all prior M1–M7 demos, three M8 track demos, the unified M8 demo and index/history scans. No API key is supplied. This report is committed before the corresponding CI run; it does not claim future success. Exact final job counts, run URL, independent M8 SHA, remote references and clean-tree confirmation are recorded in the final delivery after actual checks. The [branch Actions page](https://github.com/sadand15/btc-5m-research-assistant/actions?query=branch%3Av3-dev) associates each run with its exact commit. Final delivery evidence is also saved locally under ignored `runtime/v3/m8/delivery.json` after CI.

## Limitations and STOP

There is **NO ROBUST EVIDENCE OF LIVE EDGE** from this milestone. Synthetic validation is not true OOS validation; manifest declarations cannot prove that an external author did not previously inspect data. No real dataset is silently substituted or relabeled. Hashes provide integrity, not signed authenticity. Fixed bootstrap block length is a research assumption, and small cohorts remain uncertain. Calibration drift and concentration are diagnostic associations. Quality filtering changes the counterfactual portfolio cohort, so its outcome difference is not causal attribution of data quality.

No production feature, new model, retraining, live account/feed, optimal-parameter selection, tuning, deployment or blind performance reading occurred. M7 has no new tuning or promotion controls. **STOP: M9 is not started.**

M8 evaluates data quality, out-of-sample replay behavior,
and research robustness.

It does not demonstrate live profitability,
real execution quality,
optimal parameters,
or safety for live trading.

Sensitivity and ablation analyses are research diagnostics only.
They do not replace the frozen baseline.

Synthetic/replay evidence is not equivalent to live market evidence.
