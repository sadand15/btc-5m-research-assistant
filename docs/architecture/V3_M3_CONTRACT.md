# M3 implemented contract — deterministic admissibility

M2 answers economic edge; M3 answers admissibility now; M5 will answer execution reality; M6 will answer portfolio/risk permission. M3 only returns research/simulation candidates. It creates no orders, fills, positions, ledger, settlements, broker, trading loop or risk engine. No live adapters, optimization, training or blind-period data is used.

## Input and trust boundary

`decide(snapshot, prediction, edge, config, *, experiment_id, attempt_key, evaluation_at)` is a pure function. It does not import/call the M2 engine, read a database or use wall-clock time. It does not re-estimate probability, reprice edge, select the other side, or deduct another cost. It copies the requested side's exact M2 net edge and EV, including when a quality gate rejects it.

Inputs are immutable normal API objects from M1/M2. The policy verifies experiment, market, prediction/snapshot references, deterministic edge identity, expected edge config/version, probability/mid/time lineage, target mapping/rule/feed, selected side, and lot references. It does not authenticate a maliciously forged EdgeEvaluation or prove its EV without recomputation. `DecisionRepository` obtains upstream records through M1/M2 integrity-verifying repositories; M2's own read-back recalculation remains the M2 integrity boundary, outside DecisionPolicy. Python frozen dataclasses/hashes are not a hostile-reflection or administrator security sandbox.

Explicit `None` inputs produce DATA_INCOMPLETE / NO_TRADE, with null unavailable diagnostics; non-contract object types or malformed decision envelope/config raise errors. A nonempty unknown ID passed to persistence raises lookup failure; it is not silently replaced by a different/latest input. Wrong same-experiment input linkage produces an auditable refusal. Cross-experiment inputs may be diagnosed in memory, but cannot be persisted with cross-experiment FK references.

## Metadata and backwards compatibility

M1 input dialect now optionally accepts `market_status`, `market_status_at`, `market_status_available_at`. All three are required together. Status is OPEN/CLOSED/SUSPENDED/UNKNOWN, times are explicit UTC epoch ms with observed <= available <= snapshot validation time. Observed status time cannot exceed receipt plus M1 clock tolerance. Extended events use redaction version `allowlist-m3-status-v1` and validator version `m3-market-metadata-1`. Unknown/invalid metadata never becomes an assumed OPEN state.

Old raw payloads without these fields still use `allowlist-v1` / `m1-validator-1`; their snapshot IDs and canonical bytes remain unchanged. Snapshot's optional status fields are omitted from serialization when absent. Existing rows are not rewritten or enriched retroactively. M3 refuses a snapshot without status evidence.

Prediction TargetDefinition adds optional target_source, target_feed, reference_price and reference_price_at. Old canonical JSON omits absent extensions, preserving M2 read-back. Reference prices are positive finite Decimal, paired with a timestamp, and known by prediction.input_cutoff. This metadata does not change probability or M2 mathematics.

## Fixed gate/reason precedence: m3-gates-v1

The tuple `GATES` defines both gate order and reason priority within each gate; neither dictionary iteration nor SQL row order determines primary_reason. All detected reasons are emitted in that order, and the first becomes primary_reason. No gate silently repairs mismatches. GateResult records ordered reasons and PASS/REJECT/NOT_APPLICABLE; FINAL is BLOCKED when any rejection exists.

| Order | Gate | Ordered reasons |
|---|---|---|
| 1 | IDENTITY | EXPERIMENT_MISMATCH, MARKET_MISMATCH, PREDICTION_MISMATCH, SNAPSHOT_MISMATCH, EDGE_LINEAGE_MISMATCH, TARGET_MISMATCH, RULE_MISMATCH, FEED_MISMATCH |
| 2 | AVAILABILITY | DATA_INCOMPLETE, SNAPSHOT_NOT_AVAILABLE, PREDICTION_NOT_AVAILABLE, EDGE_NOT_AVAILABLE, REFERENCE_NOT_AVAILABLE, STATUS_NOT_AVAILABLE |
| 3 | MARKET_STATUS | MARKET_STATUS_UNKNOWN, MARKET_NOT_OPEN, MARKET_STATUS_STALE, MARKET_EXPIRED |
| 4 | FRESHNESS | NEGATIVE_RECEIPT_AGE, NEGATIVE_SOURCE_AGE, STALE_RECEIPT, STALE_SOURCE |
| 5 | SOURCE_RULE | PRICE_SOURCE_MISMATCH, TARGET_SOURCE_MISMATCH, REFERENCE_PRICE_MISSING, REFERENCE_STALE, BASIS_TOO_WIDE |
| 6 | EDGE | UPSTREAM_NO_EDGE, EDGE_INELIGIBLE |
| 7 | SPREAD | SPREAD_TOO_WIDE |
| 8 | LIQUIDITY | INVALID_REQUESTED_SHARES, INVALID_EXECUTABLE_SHARES, INSUFFICIENT_DEPTH |
| 9 | NEAR_EXPIRY | MARKET_NEAR_SETTLEMENT |
| 10 | FINAL | Final candidate or NO_TRADE, no new reason |

For example, stale source + wide spread + insufficient depth always yields `(STALE_SOURCE, SPREAD_TOO_WIDE, INSUFFICIENT_DEPTH)` with primary STALE_SOURCE. Absent inputs are diagnosed, but gates whose values cannot be computed do not invent data. Spread/liquidity are NOT_APPLICABLE when no upstream side was requested. PASS means no rejection found by that gate for the supplied inputs, not proof that missing data exists; DATA_INCOMPLETE still blocks the final result.

## Time, status and freshness

All times are UTC epoch milliseconds. At decision time t, snapshot.available_at, prediction.available_at/input_cutoff and edge.evaluated_at must be <= t. Future reference/status timestamps also reject. A BUY edge cannot predate the availability of its own inputs. No negative age is clamped.

- receipt_age_ms = t − snapshot.received_at.
- source_age_ms = t − snapshot.source_at.
- quote_age definition is receipt_age, with source_age separately checked and reported.
- time_to_expiry_ms = snapshot.expiry − t.

Both ages must be >=0 and <= their configured maxima. Equality passes. TTE <=0 means MARKET_EXPIRED; 0<TTE<minimum means MARKET_NEAR_SETTLEMENT; equality with minimum passes. Only explicit OPEN status passes the market-state gate. Missing status metadata causes DATA_INCOMPLETE, unknown status MARKET_STATUS_UNKNOWN, closed/suspended MARKET_NOT_OPEN. Status observed-age > max_market_status_age_ms is MARKET_STATUS_STALE.

Mandatory regression: source=1000, received=4000, decision=5000, max_receipt=2000, max_source=3000 → receipt_age=1000 but source_age=4000 → NO_TRADE / STALE_SOURCE. Mandatory near-settlement regression: TTE=5000 with minimum=10000 refuses even a high edge.

## Source contract and optional reference gate

DecisionConfig binds one exact allowed market_id, source, feed, rule_hash and outcome_mapping, plus prediction_target_source, expected_model_hash, expected_edge_config_hash and edge version. Prediction target must explicitly declare its source/feed. Semantic confirmation defaults false. Setting true requires a semantic_contract_hash recording an externally authored/pre-registered compatibility assertion. All these values enter config hash; merely close prices cannot grant semantic compatibility.

The synthetic demo's assertion only describes its artificial oracle/model. M3 does not verify a real Binance/Chainlink/Predict.fun mapping and never infers it from price divergence. Target source/feed/rule/mapping, market/experiment/expiry, model hash or confirmation mismatch means TARGET_SOURCE_MISMATCH (with more specific identity/feed/rule reasons where applicable). Snapshot source mismatch adds PRICE_SOURCE_MISMATCH.

Reference prices are optional by default; they are not fabricated. `require_reference_price` requires the snapshot reference; `require_basis` requires both snapshot and prediction-target references and an explicit max_basis_bps. Missing required data fails REFERENCE_PRICE_MISSING; reference ages over max_reference_age_ms fail REFERENCE_STALE. Future timestamps always fail availability. Basis is calculated only when the semantic contract matches and required reference values are known, available and fresh:

```
observed_basis = model_target_reference - venue_reference
basis_bps = (model_target_reference / venue_reference - 1) * 10000
```

Gate on abs(basis_bps) <= max_basis_bps; equality passes. A low basis never overrides semantic mismatch. The M1 dialect contract associates reference_underlying_price with its declared feed; no real reference-source validation adapter is implemented.

## Side, spread, liquidity and units

M2 NO_TRADE stays NO_TRADE / UPSTREAM_NO_EDGE. For BUY_YES or BUY_NO, only that selected side is inspected; preferred_side cannot switch. An ineligible/missing selected side fails EDGE_INELIGIBLE. Upstream reasons are preserved separately rather than changing M3 precedence.

Spread = selected ask − selected bid; normalized spread = spread / selected mid. Absolute and optional normalized maxima are inclusive. They gate admissibility only: **M2 edge=.09 remains .09**, whether a .02 spread is accepted or rejected. No .01 spread-half or .02 full-spread deduction is applied again.

ExecutableFraction = M2 executable_shares / requested_shares. Requested must be positive, executed must be within [0,requested], and zero executed always fails depth. Fraction and optional absolute executable-share minima are inclusive. Requested=100, executable=60, minimum=.8 → NO_TRADE / INSUFFICIENT_DEPTH, even when M2's separately configured fraction/edge permits the candidate. No resizing or new VWAP is computed.

Selected liquidity_used is copied unchanged, with physical IDs, origin, derived flags, prices and shares. IDs/quantities/origins must refer to the selected snapshot book without duplicates. `liquidity_independent=false` is audit metadata, not a rejection; derived NO is allowed when otherwise admissible. No lot is consumed or reserved. Shared-depth consumption belongs to M5.

Per-share edge is collateral/gross executed share, total expected value is collateral, shares remain shares. Decimal context is fixed at precision 80; ratio diagnostics use 18-place HALF_EVEN. Threshold comparisons for normalized spread, fraction and basis use exact cross-products, so rounding a displayed ratio to a boundary never relaxes a gate. M2's edge and total EV are copied byte-equivalent Decimal values, not rounded again.

## DecisionConfig and output

DecisionConfig is frozen with deterministic canonical SHA256. Default research assumptions: max_receipt_age=2000 ms, max_source_age=3000 ms, max_market_status_age=5000 ms, minimum TTE=10000 ms, max absolute spread=.05, minimum fraction=.8, no normalized spread/absolute share minimum, optional references/basis disabled, max reference age=3000 ms. No default semantics confirmation. These are **pre-registered research assumptions, not historical optimization results**. Only decision-v1/m3-gates-v1/edge-v1 policies are currently supported.

Frozen Decision contains identity/attempt/input IDs, time, requested/final actions, primary/all reasons, source/receipt ages and quote definition, TTE, spread/normalized spread, requested/executable/fraction, unchanged edge/EV, selected side/liquidity metadata, reference diagnostics, market status, gate audit, upstream reasons, config/version and full-input hash. Its purpose explicitly says RESEARCH_SIMULATION_CANDIDATE_NOT_ORDER. On missing input or upstream NO_TRADE, unavailable side values remain null.

## Storage and deterministic replay

Schema 3 adds only `decisions` to the existing six tables. DecisionRepository explicitly upgrades schema 2 using BEGIN IMMEDIATE and transactional DDL. Same-experiment FKs reference predictions, market_snapshots and edge_evaluations; nullable references support explicitly absent inputs. No future order/fill/risk tables are created. Schema reopen is read-only validation, not repeated migration.

decision_id = SHA256([experiment_id,attempt_key]). Every attempt_key is caller-assigned and stable. Same inputs/time/config + same key are idempotent; changed content under that key fails, even if it would produce the same final action. A new evaluation time/config needs a new attempt_key. Records reject UPDATE/DELETE/REPLACE. One decision insert and all input checks occur within one transaction; upstream records are not modified.

Read-back verifies canonical config and payload hashes/identity, resolves exact stored input IDs through upstream integrity checks, reruns the pure policy and compares the complete output. No latest/as-of lookup can replace an input. Adding a t+10000 event therefore leaves the past t decision unchanged. Tests inject migration/write failures and corrupt rows, exercise FK constraints and concurrent duplicate attempts. No cryptographic signing, power-loss campaign or high-throughput benchmark is claimed.

## Synthetic demo

`python -m btc5_v3.decision.demo --project-root .` requires a clean commit. It stores four scenarios in this worktree's runtime/v3/m3-demo.sqlite and prints full audit records: A BUY_YES, B NO_TRADE/STALE_SOURCE, C NO_TRADE/SPREAD_TOO_WIDE, D NO_TRADE/INSUFFICIENT_DEPTH. Re-running the same Git commit is idempotent. No network or V2 database is involved.
