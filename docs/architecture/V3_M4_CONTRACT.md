# M4 research analytics contract

M1 = trustworthy data; M2 = economic edge; M3 = admissibility; M4 = research evidence; M5 = execution realism (not implemented).

Calibration means measurement only. No fitting, training, threshold optimization, execution, orders, fills, portfolio, risk engine or live trading is implemented here. All demo outcomes and fees are synthetic; real venue settlement semantics remain unverified.

## Inputs, scope and time

`ResearchObservation` is an immutable canonical archive of the original Prediction and optional Snapshot, EdgeEvaluation and Decision. Analytics accepts an explicit archive, never discovers the latest rows or silently combines experiments. Coverage is conditional on this archive (`EXPLICIT_ARCHIVE_NOT_WHOLE_DATABASE`); it cannot establish completeness of the upstream collector. An external manifest would be needed for that claim.

The multi-market demo registers a separate `M4_SYNTHETIC_ARCHIVE_V1` research experiment. M1's collector registration binds validation to one market; M4 does not weaken that contract or backfill earlier tables. Original upstream payloads are retained in `analysis_runs.inputs_json`. These hashes establish reproducibility, not signed authenticity of externally supplied archives.

One observation per prediction is accepted. Cross-experiment inputs and duplicate prediction IDs are rejected. A valid research chain requires compatible market, rule, mapping, expiry, IDs and decision input hash, with inputs available before their consuming edge/decision and the decision before expiry. M3 refusals remain research observations but never become admissible candidates.

`ResolvedOutcome` records experiment, market, resolution time, availability time, YES payout, source, rule hash, settlement version and `SYNTHETIC_RESEARCH` semantics. Payout is exactly 0, 0.5 or 1. Availability cannot precede resolution. Labels are usable only if source/version/rule match, resolution is at or after expiry and strictly after the observation, and both resolution and availability are at or before the analysis cutoff. Future/unknown outcomes remain unresolved, not losses. Outcomes are post-hoc evaluation inputs only; they never enter Prediction, EdgeEvaluation or Decision.

One immutable outcome per experiment/market is supported. Settlement correction/revision is not implemented. Changing a future label in an isolated fixture changes analytics only, never upstream records.

## Probability measurement

- Payout Brier is mean `(p_yes - yes_payout)^2`, including split=0.5. Binary Brier is also reported separately.
- Binary Log Loss excludes splits explicitly. Calculation clips to `[epsilon, 1-epsilon]`, default epsilon=1e-12; archived probabilities remain unchanged. Epsilon and clipped sample count are disclosed.
- Ten fixed reliability bins have edges 0, 0.1, ..., 1. Bins are left-inclusive/right-exclusive except the last includes 1. Thus p=0.1 enters [0.1,0.2).
- Bins report total, binary and split counts. Mean predicted probability, observed YES rate and signed gap (observed minus predicted) use binary samples only. ECE weights absolute gaps by binary bin count divided by total binary count; MCE is the largest occupied binary-bin absolute gap.
- Empty metrics are null. Split count/frequency and excluded Log Loss count are explicit. No separate split probability model exists.

Fixed Decimal context (80 digits, HALF_EVEN) prevents dependence on the caller's arithmetic context. Log Loss is rounded to 18 decimal places; Markdown display rounds to six, while JSON retains computed precision.

## Hypothetical edge evidence

Decision-time hypothetical realized value is `net_shares * side_payout - collateral_spent`; YES payout is Y, NO payout is 1-Y. `hypothetical_realized_return` divides that value by gross shares, in collateral per gross share, matching the edge unit. Optional hypothetical ROI divides by collateral spent. None is actual simulated execution PnL.

Fixed signed edge buckets: negative; zero; (0, .02); [.02, .05); [.05, .10); [.10, .15); [.15, infinity). No absolute-edge transform. YES, NO and combined views report counts, unique markets, means/medians of edge and hypothetical return, sample standard deviation and binary side-win fraction (excluding splits). A side win is not a profitable execution. Combined all-side rows are mutually exclusive scenarios, not a portfolio. Separate original-M3-admissible views are supplied.

Spearman uses tie-averaged ranks. Both sample and unique-market counts must reach the configured minimum (default 20), otherwise `INSUFFICIENT_SAMPLE`; constant series produce `CONSTANT_SERIES`. Correlation is descriptive, not evidence of causality or stable alpha. Repeated observations in a market are not independent. Cluster-aware inference is unimplemented: SE/CI are null. Profit Factor and Sharpe are unavailable; there is no execution evidence or equally spaced return series.

## Coverage and grouping

Coverage numerator is original M3 admissible candidates; denominator is eligible research observations with a compatible, time-valid full chain. Resolution is not required in this denominator. Total supplied rows, as-of predictions, analyzed predictions, valid snapshots, resolved observations, edge candidates, M3 candidates and exclusion reasons are separately reported. Exclusion counts can overlap. Probability metrics may include supported resolved predictions without a full snapshot/decision chain; their denominator differs from candidate coverage.

Fixed TTE bins in seconds: [0,30), [30,60), [60,120), [120,180), [180,infinity). Each includes probability metrics/gap, raw/net edge, candidate coverage and hypothetical return with counts. Chronological groups are sorted UTC days; model groups and settled YES/NO/SPLIT direction groups are also reported. Settled direction grouping is explicitly post-hoc. No shuffle or out-of-sample claim; small groups are marked insufficient and no significance test is claimed.

## Sensitivity is not optimization

Return every threshold in original order: .02, .03, .05, .07, .10, .15. Return every cost multiplier in original order: 1, 1.5, 2, 3. No best, optimal or recommended threshold output or ranking by historical results.

Both analyses conservatively retain the original M3-admissible cohort and original selected side. No refusal is resurrected, even when a lower threshold could otherwise admit it. Threshold comparison is strict `net_edge > threshold`. Cost scenarios use the fixed strict research condition `net_edge > .01`, disclosed in each result and config hash; it is not a new trading policy.

Cost stress scales collateral fees, latency/extra costs and share-denominated fees, not observed book notional. Spread/depth costs already present in acquisition price are not added again. Share fees exceeding gross shares produce `INVALID_SHARE_FEE_STRESS`, not clamped shares or a candidate. Original M2 records are never overwritten.

`EdgeSensitivityResult` is counterfactual research. Coverage retains the eligible-research denominator. Mean stressed edge uses the original admissible cohort, including negative stressed edges; mean hypothetical realized return uses the scenario-passing resolved subset. These conditional populations differ and are not returns of an executable strategy.

## Persistence and reproducibility

Schema 4 adds only `resolved_outcomes`, `analysis_runs`, `analysis_results` (ten tables total). Run records contain explicit archives, outcome IDs, code/git identity, cutoff, creation metadata, immutable config/hash, input hash and analysis version. Full inclusion rules, counts, exclusions and limitations are in the persisted report. Outcome/run/result writes are transactional; UPDATE, DELETE and REPLACE are rejected. Conflicting labels fail rather than rewrite history.

Analysis identity hashes experiment, code, cutoff, config and full supplied archive. The archive hash includes provided labels even when cutoff excludes them: adding such an input changes provenance identity, not as-of metrics. Input order does not affect identity. Creation time is explicit, at or after cutoff, and excluded from logical identity; retry retains the first persisted creation metadata. Fixed input/config/code/cutoff/creation metadata yields identical artifacts.

Readback validates hashes and replays captured inputs, comparing the complete result; it does not absorb later database additions. Hashes are not signatures or protection against an administrator rewriting everything. Schema migration leaves M1-M3 rows intact. Demo artifacts reside only under ignored `runtime/v3/`. The JSON artifact is an AnalysisResult envelope containing the canonical `report_json` string; parse that string for full analytical tables.
