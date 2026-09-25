# M4.5 Intracycle price path contract

M4 = probability + edge evidence; M4.5 = intracycle market path evidence; M5 = execution realism (not implemented).

This module measures observed price paths, not an executable strategy. It never generates orders, entry/exit recommendations, parameter rankings, simulated fills or execution PnL. No fitting, training or optimization is performed. Synthetic fixtures demonstrate software behavior, not recurring patterns in the real BTC prediction market.

## Inputs and immutable boundary

`MarketPathPoint` stores canonical original `snapshot_json`, optional original `decision_json`, and optional explicit `observation_at`. Construct it with `MarketPathPoint.from_snapshot(validated_snapshot, decision=None, observation_at=None)`. `.data()` exposes the flattened research projection, including experiment/market/snapshot IDs, source/received/available timestamps, sequence, expiry, remaining time, both sides' bid/ask/mid/spread and visible depth, derived-liquidity flags and causal reference fields. `available_at` always remains the original snapshot availability; default observation time equals it. An explicit observation must be at or after availability and before expiry.

Only valid M1 snapshots are accepted. Archive validation checks structural fields, timestamp ordering, snapshot identity, finite probability/depth, depth ordering, complementary NO book and liquidity identity. It does not create a permissive MarketSnapshot constructor. Current NO prices/depth are complementary views of the YES lots, not independent liquidity. Both side reports remain necessary but are not independent replications.

M3 status is a label from the linked original Decision, not a new policy evaluation. At the observation time it is `UNAVAILABLE`, `NOT_YET_AVAILABLE`, `ADMISSIBLE` or `REJECTED`. Missing/rejected records remain research observations. Linkage and decision identity are checked; externally supplied archives are assumed to be trusted upstream exports. Hashes support integrity/replay, not signed authenticity or proof of collector completeness.

One point per snapshot is accepted. Duplicate snapshots, ambiguous `(market_id, received_at, sequence)` keys, cross-experiment inputs and changed expiry/source/feed/rule/mapping within a market fail explicitly. Market identity must denote one five-minute contract. The eligible receive window begins at `expiry-300000`; observations at/after expiry, outside the cycle or after cutoff are counted as exclusions. This is an explicit archive, not automatic whole-database discovery. Empty archive markets cannot be inferred; coverage cannot claim completeness beyond supplied input.

## Causal ordering and missingness

Within each market order is exactly `(received_at, sequence)`. Source time and settlement never reorder it. At an observation, future candidates must follow it in that order, be received no earlier than the observation time, and become available no earlier than that time and no later than cutoff. Same-ms higher sequence is allowed with zero elapsed time. Quotes received before a delayed observation are not treated as future movements. Original Snapshot/Prediction/Edge/Decision bytes are never changed by future quotes or outcomes.

Two separate views are always produced: `ALL_STRUCTURALLY_VALID` and `FRESHNESS_FILTERED`. A fresh point has both source age and receipt age in `[0,max_quote_age_ms]` at observation time, and is available before expiry. Default age limit is 5000 ms. Small tolerated future source clocks remain structural observations but fail this freshness condition. Stale peaks are visible in the first view and excluded from the second.

Missing intervals are gaps longer than `max_missing_interval_ms` (default 5000) between observed receive times, including leading/trailing boundaries. No interpolation, synthetic quote insertion, settlement endpoint insertion or backfill occurs. These are missing-coverage intervals under the declared cadence assumption, not proof a specific number of API messages was lost. Freshness filtering can create additional gaps. Cutoff before expiry is explicitly right-censored.

`complete_observation_window` means a nonempty observed future, cutoff reaching expiry and no future coverage gap exceeding the declared limit. It does not assert continuous observation between samples or execution availability. Sparse maxima are observed extrema only. A missing future yields null, not zero or loss. Quote-age and missing-gap assumptions may be preregistered before a new study; changing either changes config identity and must not be selected from blind results.

## Fixed TTE views

As-of targets are remaining 240/180/120/60/30 seconds. At target time, select only the latest point whose receive, availability and observation times are not later than the target and whose source/receipt ages pass there. No suitable point gives explicit `MISSING`; a target after cutoff is also missing. A view references the actual earlier quote and records its receive/availability times; it is not inserted into the raw path as a new quote. Future extrema for this view use quotes strictly after target time. M3 status retains the linked status known at that point's original observation, never a future status.

## Mid and observable bid metrics

For each side, descriptive mid is `(bid+ask)/2`. Observable bid is only a possible side-price reference if already holding; it is not an execution price or fill guarantee. Each observation reports future maximum/minimum mid and bid, signed max-mid-rebound `max(future_mid)-initial_mid`, max-bid-rebound `max(future_bid)-initial_bid`, signed mid drawdown `initial_mid-min(future_mid)` and analogous bid drawdown. Negative and zero rebound are preserved, not clamped. Since extrema exclude the initial point, a monotone rise can have negative signed drawdown. Timing uses receive time of the earliest ordered tied extremum minus observation time. Per-row future counts, market path count, market stale count, missing future intervals and settlement payout are explicit.

The requested example mid .90 with bid .25 is impossible under valid probability quotes: ask would have to be 1.55. The exact impossible input is a rejection test. A valid wide-spread contrast is `.05/.15 → .25/.95`: mid rebound .50 versus bid rebound .20. No invariant is weakened to manufacture the impossible example.

## Preregistered bins and grids

Price edges: 0, .05, .10, .20, .30, .50, .70, .80, .90, .95, 1. Left inclusive/right exclusive; final bin includes 1. M1 quotes remain strictly inside (0,1); endpoint bucket behavior is tested independently. Mid tables condition on initial mid; bid tables condition on initial bid, so their populations can differ. Pairwise per-observation results permit direct mid/bid comparison.

TTE edges in seconds: 0, 30, 60, 120, 180, 240, 300, with the same boundary rule. Exactly 240 seconds belongs to [240,300], while an explicit 240-second as-of view is also supplied. Post-expiry quotes are excluded rather than put in the first bucket.

Rebound thresholds: .05, .10, .20, .30, .40, .60; hit comparison is `>=`. Every grid element is returned in this order, including empty cells. There is no best threshold, optimal price/TTE or recommended strategy output. `IntracyclePathConfig` is frozen and canonical-hashed. Fixed bucket/grids/movement definitions are validated, not dynamically learned.

## Statistical units, reversal and continuation

Each side/view/price/TTE cell reports total rows, observed-future denominator, unique markets, no-future count, mean/median maximum rebound, median maximum drawdown, negative/zero counts, all threshold counts/fractions and declared-window-complete subset counts/fractions. Observed hit fraction is conditional on having an observed future and on supplied archive selection. Missing peaks and observation-density selection prevent interpreting it as an unbiased probability for complete market paths.

Market-balanced hit fraction averages each market's within-cell hit fraction with equal market weight. It reduces tick-count weighting, not selection bias or within-market dependence. Status is `INSUFFICIENT_SAMPLE` below minimum distinct observed-future markets (default 20); otherwise `DESCRIPTIVE_ONLY`. Fractions/counts remain inspectable even when insufficient. No confidence interval, significance or repeatable-real-market claim is generated.

For every threshold, downward extension counts accompany upward rebound. Low-priced (<.5) downward extension is recorded as low-price continuation; high-priced (>.5) upward extension is high-price continuation. Opposite moves remain the upward/downward reversal evidence; no default assumption favors reversal. Settlement is not substituted for a final quote.

Market-level high/low/range and observed maximum rebound/drawdown are computed separately for YES/NO and both freshness views. Direction-change count uses a fixed .05 move: establish direction only after moving that far from the segment start, update the running extreme, and count a reversal only after an opposite move of at least .05 from that extreme. Large reversals repeat the same algorithm with .20. At least two large reversals marks observed whipsaw. Restart the movement algorithm at each missing-data gap, so disconnected quotes do not prove turns. Range/extrema can still span gaps and remain labeled observed-only.

## Quality and settlement conditioning

Fixed quality edges: spread 0/.02/.05/.10/1; normalized spread 0/.1/.5/1/2; visible bid/ask depth 0/1/10/100/1e22 shares; source age -60000/0/1000/5000/max timestamp and receipt age 0/1000/5000/max timestamp. Normalized spread is spread/mid; visible depth is summed displayed quantity, not a fill estimate. Each dimension and M3 status has separate YES/NO and mid/bid distributions, with no optimization.

Only explicitly supplied synthetic `ResolvedOutcome` is supported: same experiment/market/rule, source `synthetic-settlement`, version `synthetic-settlement-v1`, resolution at/after expiry and both resolution/availability at/before cutoff. Incompatible, premature and future labels are separately counted. Payout is 0/.5/1, NO payout is 1-YES. Per threshold distinguish rebound then losing settlement (temporary rebound), rebound then winning settlement, split and unresolved. Multiple settlement versions for one market in a run are rejected; cross-run archives can represent explicit separate evidence without rewriting any original settlement row.

Snapshot reference price is exposed only if its timestamp is causally available by receipt/availability. It is not assumed to be a live BTC series. No explicitly permitted causal BTC series was supplied in this phase, so BTC price/5s/15s/30s/60s returns, realized volatility and shock conditioning are unavailable. Enabling BTC shock config is rejected until a versioned causal-series contract exists.

## Persistence and artifacts

Schema 5 adds only `path_analysis_runs` and `path_analysis_results`; twelve tables total. Original snapshots remain untouched. Runs contain original point/outcome archives, immutable config/hash, input hash, code SHA, cutoff, explicit creation metadata and analysis version. Same experiment/code/config/cutoff/full input archive gives the same logical analysis ID. Creation metadata is explicit and first-write-preserved on retry. Full input hash also includes supplied future inputs excluded by cutoff; changing the archive changes provenance ID without introducing them into as-of statistics.

Writes are atomic and append-only; UPDATE/DELETE/REPLACE fail. Readback recomputes from captured archives and checks complete result and hashes; later database additions do not enter older runs. No cryptographic authenticity or protection against complete administrator rewrite is claimed.

The demo writes only ignored `runtime/v3/m4-5-demo.sqlite`, `m4-5-report.json`, `m4-5-report.md`. JSON is a PathAnalysisResult envelope; parse its `report_json` string for all tables, observations, missing intervals and fixed views. Markdown is a deterministic readable companion (six-decimal display); JSON retains computed Decimal precision. Computation uses fixed Decimal context 80/HALF_EVEN. No API credential is needed.
