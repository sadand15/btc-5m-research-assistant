# M8 Research Validation Contract

Version: `m8-research-v1`. Written before implementation. Approved source baseline: `e4b67ed728073864a6cc809d26ad6f23c822c973`. M1–M7 source and semantics remain unchanged; M8 supersedes the old deployment milestone proposal. No M9 work.

## Scope, evidence and roles

M8 adds data quality, fixed-config validation and research robustness using the existing M1 validator, M2 edge, M3 decision, M4 calibration, M5 execution and M6 pure risk reducer. Prediction probabilities are explicit archived inputs; no inference/training is invented. M7 remains read-only and unchanged. Schema 7 stays unchanged; separate M8 input archives and ignored JSON/Markdown outputs do not migrate existing databases.

DatasetManifest records identity, DEVELOPMENT / VALIDATION / BLIND role, UTC start/end (inclusive), source, creation time, payload SHA256, evidence mode, declared quality status and optional expected cadence. Role is metadata, never inferred from path. Read boundaries check role before accessing record payloads. BLIND is denied to all M8 analyses, including quality/performance; presence or changes of blind records do not affect outputs. Unknown roles and evidence fail closed. Current adapter supports SYNTHETIC only because M5 settlement semantics explicitly support synthetic research. Real historical/OOS evidence remains UNSUPPORTED until a separately approved adapter exists. A synthetic VALIDATION manifest tests the machinery, not real unseen market performance.

An explicit development→validation pair must have disjoint market IDs and strictly ordered, nonoverlapping time ranges. No automatic split, reassignment or result-based reselection. Validation accepts only VALIDATION and exactly the frozen baseline. Robustness variants accept only DEVELOPMENT. Manifests and config hashes bind all outputs; authentication of an external author's role/creation claims is not implied by a hash.

## Fixed inputs and configuration

Baseline captures approved Git SHA, prediction model/feature/calibration bindings, EdgeConfig, a DecisionConfig template with explicit market identity binding, ExecutionConfig, ExitPolicy, RiskConfig and AnalyticsConfig. Default M8 synthetic binding uses the existing synthetic-risk model and fixed original defaults, edge target 100 shares. Calibration remains `none`; no fitting. Each full bundle has a canonical hash. Variant objects are separate immutable copies and can never be passed as validation baseline. Production defaults/files are never updated.

Each explicit research record contains stable id, UTC decision time and sequence, sanitized raw market envelope, archived Prediction, contemporaneous HealthEvidence, zero or more future MarketPathPoint books and optional ResolvedOutcome. Raw input is validated using M1 at its recorded availability, not retrospectively at decision time. Domain objects reject impossible values. Late books/outcomes are research-only event inputs; never decision inputs.

## Track A: quality gate

Decision-time quality is evaluated with information available at that decision. Only VALID enters primary statistics. DEGRADED is inspectable in a separately labeled ALL ELIGIBLE diagnostic cohort (VALID + DEGRADED). INVALID / UNKNOWN never reach the replay reducer. All exclusion counts, IDs, sources, timestamps and reasons remain in the report. Future execution/settlement evidence availability is counted separately and cannot rewrite historical quality or decisions.

- INVALID: malformed required fields, impossible prices/probabilities/depth/spread, bad health values, cross-identity mismatch or future/causally impossible decision input. Missing required raw/prediction is INVALID. Never use outcome direction or PnL to classify quality.
- DEGRADED: M3 receipt/source/status ages exceeded; M6 feed/heartbeat age exceeded; optional health missing; excessive contemporaneous cross-source divergence; a known cadence gap before the observation.
- UNKNOWN: unsupported evidence/record contract. No default HEALTHY state.
- VALID: all applicable required checks passed; not a guarantee of data authenticity or strategy validity.

All times use integer UTC epoch ms. Ages preserve signed subtraction: decision minus receipt/source/prediction availability/health source/heartbeat. Prediction age is reported but has no invented production limit. Source skew is absolute source timestamp difference. Future values are invalid, not clipped. Staleness uses original M3/M6 limits; execution quote age uses M5's existing receipt-age definition at replay consumption. Outliers are domain invariant failures; no statistical deletion. Statistical outlier screening is NOT IMPLEMENTED.

Expected cadence is optional and explicit. With cadence c and inclusive [start,end], expected slots are start+k*c; a record covers its exact decision-time slot once. Consecutive missing slots define a gap, duration=missing_slots*c; leading/trailing gaps are retained. Without cadence, coverage/gap statistics are UNAVAILABLE, not inferred from sparse observations. Duplicate identity/time-sequence inputs fail the dataset contract. A gap before a record is known at that record's time; trailing/future missing slots do not change earlier quality.

Venue divergence uses two explicit same-unit BTC prices available by decision time: abs(A-B)/A, with first declared source A fixed as reference, never chosen by results. Research warning threshold fixed at 1%; threshold is quality diagnostics, not a production gate. Invalid prices/timestamps are INVALID. Missing comparison is UNAVAILABLE. Reconstructed books without independently supplied compatible ground truth are NOT VERIFIABLE; M8 does not fabricate reconstruction accuracy. No observed book is interpolated.

Summary includes quality counts, coverage/gaps, age distributions (nearest-rank p50/p95/p99), stale rates, alignment violations, domain outliers, divergence and missing execution/settlement evidence. Raw secrets are never returned in diagnostics; exported artifacts reuse M7 recursive redaction.

## Track B: causal replay

Reconstruct M1 snapshot and archived Prediction, call unchanged M2 evaluate_edge and M3 decide, then unchanged M6 apply_event (which invokes M5). Replay uses one chronological event queue per dataset/cohort, sorted by (at, phase, sequence, record id); decision phase precedes same-time execution. Only books/outcomes available by a task time are supplied. Nonapproved permissions do not execute. Existing M6 controls and conservative reservations remain authoritative; M8 never synthesizes a healthy heartbeat or clears a guard.

Repeat each baseline replay at least twice with fresh in-memory contexts. Compare full candidates/decisions, permissions, reservation revisions, executions, ledger, states and summaries. Any mismatch is FAIL with diagnostics, never averaged away. Read-only here means no source database mutation; derived hypothetical events live only in memory/artifacts. Cutoff excludes future records/tasks. Baseline identity/config is fixed before replay. No random state in replay.

Metrics report explicit denominators for candidates, permissions/rejections/reductions, approved shares, entry fills/partial fills, fee amounts in original units, execution cost, completed simulated PnL, risk transitions, M4 calibration and selected-side net edge. No missing outcome becomes zero. Report all-eligible vs quality-passed changes. Regime statistics are attribution of the same replay, not independent recomputation of portfolio history. Regimes use decision-time spread (<0.03 low), visible ask depth (<100 low), M4 TTE buckets, fixed probability bins, side/market/UTC day. BTC volatility/trend/shock unavailable without a causal reference series; no full-period statistic is backfilled.

PASS means causally evaluable and reproducible, never profitable. An empty quality-passed cohort is INSUFFICIENT_DATA. Real OOS consistency remains NO ROBUST EVIDENCE with synthetic-only inputs.

## Track C: diagnostics only

Sensitivity uses five fixed minimum-net-edge values baseline + {-0.01,-0.005,0,+0.005,+0.01}, one factor at a time, on DEVELOPMENT quality-passed data. Full grid including baseline is retained; no ranking, winner, recommendation or promotion. A plateau is identical candidate/permission counts across adjacent grid points; a cliff is adjacent candidate-count change of at least 25% of eligible sample count; a spike is a strict local extremum in candidate counts. These are research descriptors, not parameter recommendations.

Ablation removes only the M3 absolute-spread research restriction by setting its copy to the maximum domain spread 1; all other gates and baseline remain. Unsupported components (e.g. calibration training, shock model) are not faked. Report count/metric/risk/calibration deltas with uncertainty, not causal feature importance.

Bootstrap uses seeded moving blocks of chronological market clusters (all observations from a market stay together), with fixed block length 2 markets, 200 replicates, seed 42 by default; at least 8 distinct markets are required. Sample blocks uniformly from valid contiguous starts, concatenate and trim to original cluster count. Percentile 2.5%/97.5% intervals use nearest-rank quantiles. Describe conditional empirical uncertainty only; fixed block length does not establish independence. Too few markets yields INSUFFICIENT_SAMPLE with null CI. Bootstrap reported row-level mean edge, fill/reject indicators and squared probability error; no resampled M6 portfolio is claimed. Realized return CI only for completed fills with positive entry cost.

Feature dependence reports counts, sample share, absolute metric-contribution share and Herfindahl concentration by fixed probability/TTE/spread/depth/side/market/day buckets. Zero contribution denominator is null. It is descriptive concentration, not causal importance. Calibration drift reuses M4 calibration on fixed development and later validation windows plus regime/TTE/probability groups; signed validation-minus-development Brier/ECE and bin gaps, with explicit sample counts. Outcome must be available by cutoff. Intervals of group Brier/edge are bootstrap estimates, not guarantees.

## Matrix, provenance, outputs and non-goals

Unified rows identify dataset, role, quality cohort, regime, BASELINE/research variant and metric set. Every report has actual analysis Git SHA/branch, dataset id/hash/role, approved source SHA, quality contract hash, complete baseline/risk/execution config hashes, analysis parameters, seed if used and generated_at=explicit logical cutoff. Missing facts are UNKNOWN. Equal inputs/config/seed/code/cutoff give identical canonical bytes. Input hash tampering fails; output redaction occurs before persistence.

Write only ignored `runtime/v3/m8/` data-quality, validation, robustness and summary JSON/Markdown artifacts. No M7 UI extension is required; reports are the bounded M8 interface. FACT / ESTIMATE / UNCERTAINTY / LIMITATION remain separately labeled. No live feed/account/wallet, orders, new models, tuning, fitting, optimization, promotion, real PnL or blind reading. Unfavorable results are legitimate research evidence.

M8 evaluates data quality, out-of-sample replay behavior,
and research robustness.
It does not demonstrate live profitability, real execution quality,
optimal parameters, or safety for live trading.
Sensitivity and ablation analyses are research diagnostics only.
They do not replace the frozen baseline.
Synthetic/replay evidence is not equivalent to live market evidence.
