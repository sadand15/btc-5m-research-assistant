# M2 implemented contract — dual-side edge math

M2 is research/simulation arithmetic, not a prediction engine, order, fill, liquidity reservation or complete Decision/Risk gate. No network, venue adapter, wallet, training, historical optimization or V2 observation input is used.

## Inputs and identity

`Prediction` is frozen. It contains experiment_id, prediction_key, deterministic prediction_id, market_id, p_yes, model_version/hash, feature_version/hash, input_cutoff, available_at, target_definition, calibration_version and support_status. SHA fields require lowercase SHA256. Safe identifiers are bounded. p_yes must be finite and within [0,1]; malformed probabilities fail construction, rather than inventing a valid prediction with an INVALID_PROBABILITY result. Unsupported but well-formed predictions produce NO_TRADE.

`TargetDefinition` binds probability_semantics=MARKET_YES, outcome_mapping, rule_hash and expiry. The engine compares these with the validated MarketSnapshot. YES does not implicitly mean UP. An upstream adapter must convert native UP probability explicitly; a BTC_UP target without conversion fails TARGET_MISMATCH. Nonmatching experiment or market also fails closed. Different experiment refusals can be returned in memory but cannot be persisted as cross-experiment links.

prediction_id = SHA256(canonical {experiment_id,prediction_key}). The caller supplies a stable logical prediction_key; changed content with the same key conflicts. edge_id hashes {experiment_id,prediction_id,snapshot_id,evaluated_at,config_hash}. A different evaluation time/config is a new evaluation, not a retry.

## Time contract

All times are explicit integer UTC epoch milliseconds. input_cutoff <= prediction.available_at is required. Before side math, require snapshot.available_at <= evaluation_at, prediction.available_at <= evaluation_at, source_at <= evaluation_at, received_at <= evaluation_at, and evaluation_at < expiry. M1's configured clock skew does not authorize using future source information in M2. A known reference_price_at must also be no later than evaluation_at. Negative ages are retained, never clamped.

- receipt_age_ms = evaluation_at − snapshot.received_at.
- source_age_ms = evaluation_at − snapshot.source_at.

source=1000, received=4000, evaluation=5000 produces source_age=4000 and receipt_age=1000. There is no wall-clock lookup. A later explicit evaluation time before expiry is legal; M2 records age without imposing a stale/spread/source quality threshold. These final gates belong to M3. On causal or compatibility rejection, both side evaluations are null and candidate_action=NO_TRADE. Identity/probability/mid diagnostics remain attached to the rejected input record; null EV is never replaced by zero.

## Depth, costs and units

Prices are collateral/gross share, quantities are shares, EV totals are collateral. Settlement payout assumption is one collateral per winning net share. The denominator of every per-share EV is **gross executed shares**, not requested or net shares.

For each mutually exclusive BUY_YES / BUY_NO scenario, walk the corresponding sorted asks until requested quantity or visible depth is exhausted. Record every lot's liquidity_id, origin, derived flag, price and hypothetical shares. Return requested/executable/unfilled shares, insufficient_depth, VWAP, and total EV for the executable subset only. Valid M1 snapshots always have positive nonempty ask depth, so a positive request has positive hypothetical executable quantity. Zero/negative requested quantity is invalid config. There is no infinite depth assumption or book mutation.

Derived NO asks preserve original YES bid lot IDs. The two scenario results must not be combined as independent executable capacity. M2 performs no consumption, reservation or delayed fill; M5 must enforce shared-lot accounting.

For side probability s (p_yes or 1−p_yes):

```
raw_edge = s - (bid + ask)/2
notional = sum(level_price * taken_shares)
vwap = notional / gross_executed_shares
executable_edge_before_costs = s - vwap
spread_half_cost = best_ask - mid              # explanatory only
depth_cost_per_share = vwap - best_ask         # explanatory only
```

FeeModel is explicitly simulation-only. COLLATERAL: cash_fee = notional × rate + gross_shares × collateral_per_share; net_shares=gross_shares. SHARES: deducted_shares=gross_shares × rate, net_shares=gross_shares−deducted_shares, cash_fee=0; additional collateral_per_share is disallowed. Rates are in [0,1]. Share deductions are reported in shares, never silently charged as collateral or a fixed probability decrement.

```
collateral_spent = notional + cash_fee
                 + gross_shares * (assumed_latency + assumed_extra)
EV_total = net_shares * s - collateral_spent
net_edge_per_share = EV_total / gross_shares
total_cost_basis = collateral_spent / gross_shares
```

`fee_per_share` always means collateral fee / gross executed share; it is zero for SHARES fees, whose effect is in net_shares and expected payout. CostBreakdown separately includes fee_collateral_total, fee_shares_total, net/gross shares, observed best_ask/mid/VWAP, explanatory spread/depth decomposition, assumptions/version and SIMULATION_ASSUMPTIONS label. Latency/extra cost are assumptions, not observed execution costs. **VWAP already includes spread crossing and visible depth impact; neither is added again.** No minimum venue fees or actual fee schedule are claimed.

## Numeric and candidate policy

Decimal calculations use a private context with precision 80 and ROUND_HALF_EVEN, independent of the ambient context. Inputs permit at most 18 fractional digits / 36 total significant digits and magnitude <= 1e18; probabilities/prices/cost parameters have tighter bounds. Float adapters first normalize to 15 significant decimal digits to remove binary representation noise; string/Decimal inputs retain explicit decimal precision. Out-of-range, bool and nonfinite inputs fail.

Ratios (VWAP, per-share fees/costs/edges) are quantized to 18 decimals. Totals, net shares and cash amounts retain the high-precision formula result: this is a research proxy, **not ledger or venue tick-size rounding**. Displayed per-share × quantity may differ from total by ratio rounding; no total is recomputed from rounded VWAP. Threshold selection uses the reported 18-decimal net edge. Policy name is in config hash.

Defaults: target_shares=1, threshold=0.01, minimum_executable_fraction=1, zero fees/latency/extra assumptions. All are **placeholder research parameters; not empirically optimized**. Eligibility requires executed/requested >= minimum fraction and net_edge_per_share **strictly greater than** threshold. Equality fails. Partial depth below full target is always flagged, even when an explicitly lower minimum fraction allows candidacy. This is minimal hypothetical coverage eligibility, not the complete M3 Liquidity Gate.

Neither eligible → NO_TRADE; exactly one eligible → that side; both eligible → larger net edge per gross share; exact equality → NO_TRADE / EXACT_EDGE_TIE. Normal complementary books, nonnegative costs and nonnegative threshold cannot have both sides positive. Tests use an explicit negative research threshold to exercise both-eligible and exact-tie branches, without changing the default or claiming profitability.

Reasons: EDGE_BELOW_THRESHOLD, INSUFFICIENT_DEPTH, SNAPSHOT_NOT_AVAILABLE, PREDICTION_NOT_AVAILABLE, NEGATIVE_RECEIPT_AGE, NEGATIVE_SOURCE_AGE, REFERENCE_PRICE_NOT_AVAILABLE, MARKET_EXPIRED, UNSUPPORTED_PREDICTION, MARKET_MISMATCH, EXPERIMENT_MISMATCH, TARGET_MISMATCH, EXACT_EDGE_TIE. Side reasons and aggregate NO_TRADE reasons are structured tuples. No risk/spread/stale policy reasons are invented in M2.

split_model=unavailable, split_treatment=IGNORE_SPLIT_EXPLICIT_PROXY. The explicit treatment is in immutable config/hash and evaluation. No P(split) is fabricated, and the binary proxy is not full real venue EV. Other split treatments are rejected until implemented.

## Output and storage

EdgeEvaluation is frozen. Common fields include input IDs, explicit evaluated_at, p_yes/p_no, mids, requested shares, source/receipt ages, preferred_side, candidate_action, reasons, config_hash, edge_version and split/scenario metadata. Nested `yes`/`no` each contain raw edge, executable pre-cost edge, VWAP, quantities, costs, net edge/total EV, eligibility and liquidity_used. `eligible_yes`/`eligible_no` are convenience properties. Snapshot and Prediction remain unchanged.

M1 schema remains intact. `EdgeRepository` explicitly migrates a V3 database to schema 2 in one transaction and adds only predictions/edge_evaluations. Six total tables; no future trading tables. Unique same-experiment parent keys and composite FKs reject cross-experiment linkage. New prediction+edge writes are atomic. Concurrent retries serialize under BEGIN IMMEDIATE, return identical records, and reject differing content. UPDATE, DELETE and REPLACE of M2 identities are blocked by triggers.

Read-back verifies canonical serialization, payload hash, identity and context, then re-evaluates from verified persisted snapshot/prediction/config and compares every edge field. M1 snapshot read-back validation remains in use. Corruption fails; hashes are not signatures against malicious database administrators. Migration failure leaves schema 1 unchanged; ordinary database reopen does not rerun DDL.

## Demonstration and boundaries

`python -m btc5_v3.edge.demo --project-root .` requires a clean committed checkout and writes only runtime/v3/m2-demo.sqlite. It persists two synthetic predictions/evaluations against one synthetic snapshot: p=.70 → raw YES .10, executable/net .09, BUY_YES; p=.60 → both net edges −.01, NO_TRADE. Default fees and depth cost are zero. It prints the full NO equivalent and audit metadata. Same commit reruns are idempotent.

Not verified: real venue wire schema, settlement mapping, fee economics, minimum fees/ticks, model probability calibration, real latency, fills, high-throughput or power-loss durability. Strict Python frozen objects are normal API contracts, not protection from hostile reflection. No current V2 blind data is read for implementation or testing.
