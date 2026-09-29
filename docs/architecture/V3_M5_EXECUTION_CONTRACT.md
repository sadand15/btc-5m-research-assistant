# M5 Execution Simulation Contract

M4.5 = path evidence; M5 = execution realism; M6 = risk permission (not implemented). This is offline simulation using explicit archived books. No account, wallet, signing, network feed or live order interface exists in this module. H1 (extreme intracycle pricing may reprice before settlement) is a preregistered research hypothesis, not a conclusion or recommendation.

## Input and experiment boundary

`simulate` accepts one original `ResearchObservation` (Prediction, Snapshot, EdgeEvaluation, Decision), an explicit sequence of validated `MarketPathPoint` archives, optional `ResolvedOutcome`, immutable `ExecutionConfig` and `ExitPolicy`, experiment, code SHA, cutoff and creation time. It does not discover or open production data. Each run is an independent single-candidate counterfactual, not a portfolio or capital-funded execution session.

The original chain is bound by experiment, target/market/rule/expiry, snapshot/edge/prediction/decision identities, p_yes, original decision input hash and availability. Original M3 refusal creates no intent. An accepted side/size must agree with M2; simulation may request fewer shares but never more than M3 authorized. Oversize sensitivity returns `SIZE_NOT_AUTHORIZED_BY_M3`, without an intent. Upstream records are retained verbatim and never rewritten or re-estimated. Missing complete lineage and cross-experiment/market books or outcomes fail explicitly. External archives must be trusted upstream exports: hashes are not signatures or proof that a collector saw them.

Later books preserve source/feed/rule/mapping/expiry and must be legal M1 snapshots. Duplicate IDs or ambiguous receive/sequence order fail. M1's nonempty positive-depth requirement remains; missing/invalid venue books are not fabricated as executable zero-depth snapshots. No causal executable book, exhausted physical lots, and extremely small valid depth provide explicit no/partial-fill outcomes.

## Causal execution time

Entry ready time is `decision_at + decision_to_order_latency_ms`. Exit ready time is `trigger_at + exit_latency_ms`. Both default to 250 ms; separate network/matching components are deliberately not modeled. Maximum wait is 5000 ms after ready, capped at expiry. No fill at/after expiry.

Choose the first later recorded book in `(available_at, received_at, sequence, snapshot_id)` order satisfying all of:

- source, receive and availability timestamps are at or after ready;
- availability is within deadline and analysis cutoff;
- book is strictly later than the reference book and not the original signal snapshot;
- source and receipt age at execution availability are both in [0,3000] ms;
- market status is explicitly OPEN, already available, and its source age is at most 5000 ms.

Availability is primary because a received-but-not-yet-validated snapshot cannot execute. Receive time/sequence deterministically resolves simultaneous availability/source observations. Rejected books and reasons are captured. The simulator can wait past an unusable quote but not past the deadline. If cutoff has not reached deadline, status is pending, with no invented timeout business event. At deadline absence gives `NO_FILL / NO_CAUSAL_BOOK`.

Entry never uses the signal snapshot, including latency=0. Zero-latency benchmark still needs a distinct causally available later record. For exits only, the trigger snapshot is eligible at latency=0 **and** `allow_same_book_zero_exit_latency=True`; default is false. With positive latency, rebound disappearing before the next book changes the actual fill price. The trigger threshold is not rechecked to select a nicer execution book: these are IOC market-like research intents, without a limit price guarantee.

## Depth, liquidity and IOC remainder

Entry consumes the selected side's ASK levels ascending. Exit consumes BID levels descending. `walk_depth` returns exact Decimal legs, notional, shares, VWAP and unfilled shares. It never prices the whole request at best ask/bid or mid. One selected book gives one IOC attempt; unfilled quantity is explicitly cancelled rather than filled at a later favorable quote under the same order.

Consumption uses shared `liquidity_id` budgets, not independent YES/NO quantities. Derived NO refers to the same physical lots as its complementary YES view. A consumed lot cannot be reused inside a run or in another walk sharing that budget. Different counterfactual runs deliberately have independent budgets and must not be summed as a portfolio.

M1 liquidity IDs identify lots in a recorded snapshot, not authenticated persistent exchange order IDs. A newly recorded snapshot supplies its displayed lots; no within-snapshot replenishment is invented. Repeated venue liquidity across separately recorded snapshots cannot be proven independent without venue order identity. This and no queue/hidden-liquidity modeling prevent claims of guaranteed real fills.

## Fees and rounding

Fee models reuse M2 `FeeModel` units and explicit stage/version, independently configured for entry, exit and settlement. Defaults are zero-fee synthetic assumptions. The demo preregisters entry/exit notional rate .005 and settlement rate .001; these are **not verified venue rates**.

For COLLATERAL, fee is `notional*rate + traded_or_settled_shares*collateral_per_share`. Entry pays it, exit/settlement subtract it from proceeds. For SHARES:

- Entry receives gross filled shares minus `gross*rate` withheld shares. No cash fee is also charged.
- Exit charges additional inventory fee per share actually sold: inventory removed = traded shares + withheld shares. Sellable quantity is at most `remaining/(1+rate)`, so the fee cannot cause overselling. Gross proceeds are based only on shares sold into displayed bid depth.
- Settlement withholds `remaining*rate` shares and pays the side payout on the rest. All remaining inventory is removed, split between redeemed and fee shares.

Share quantities use quantum 1e-18: fee shares round upward, sellable quantity rounds downward. Residual dust remains a position until a later exit or settlement, never silently discarded. Cash multiplication is Decimal80 with no additional currency quantization; this is an explicit synthetic accounting assumption, not a claim of venue tick/fee rounding. Price ratios retain Decimal80. Same fee is never deducted in both denominations.

M2 latency/extra estimates are not replayed as execution cash costs. Later-book prices already include observed movement/spread/depth. No additional artificial latency spread or cost is deducted.

## Position and early-exit policies

`SimulatedPosition` is the immutable opening state: experiment/market/side, gross/net shares, entry VWAP, spent collateral, fee amounts, time and source order/fill IDs. Each exit event and ledger movement describes subsequent changes; the opening position is not overwritten. Partial entry creates only filled inventory.

Policy grid is fixed: HOLD; BID_REBOUND at .05/.10/.20/.30/.40/.60; FIXED_TTE at remaining 120/60/30 seconds. Policies are immutable and hashed. Unsupported thresholds and future-maximum policies are rejected. BID_REBOUND uses `observable_bid - entry_gross_fill_vwap >= threshold` on the first currently available fresh OPEN book, never mid or a future maximum. Entry VWAP reference excludes cash fees; fees affect actual accounting separately. Stale threshold-crossing observations are counted as rejected trigger observations and do not create actionable intents.

After each rebound exit attempt finishes, remaining shares can trigger again only on a later available book; no overlapping orders. Default maximum is three attempts (config bound 1–10). A timeout can be followed by a later new trigger, but its time must be strictly after that deadline. FIXED_TTE uses an explicit clock trigger, not a future quote: trigger at expiry minus target, only if entry already happened. It makes one attempt; a target before entry is not retroactively triggered. Remaining shares then wait for settlement. No risk-based stop, automatic fitting or parameter search exists.

## Settlement and PnL

Only verified-in-code **synthetic settlement semantics** are currently supported through the M4 ResolvedOutcome contract: matching experiment/market/rule, source `synthetic-settlement`, version `synthetic-settlement-v1`, resolution at/after expiry and availability by cutoff. Payouts 0/.5/1 remain explicit; NO payout=1-YES payout. No outcome means pending settlement, not a loss. Early complete exits have known cash PnL even without a label, while their hold comparison remains null until the outcome becomes available.

Report components include gross entry cost, entry cash/share fee, gross exit proceeds, exit cash/share fee, settlement proceeds, gross PnL, total stage fees, net simulated PnL, realized cash flow and remaining inventory. `gross_pnl` is explicitly **actual quantity flows after share fees but before collateral fees**. Therefore `net_simulated_pnl = gross_pnl - total_fees.collateral` for completed paths. Share deductions are already reflected in quantities and are reported in their own units; subtracting them again as cash would be incorrect. Marking fee shares at fill VWAP or payout is a separate diagnostic valuation, not another charge or a fee-free replay.

Net simulated PnL is null for an unresolved open position; partial realized cash flow is still visible. A terminal no-entry/no-fill run has known zero PnL and zero hold comparison, so no-fill candidates are not discarded from result distributions. Rejected/unauthorized candidates remain explicit but do not claim an executable outcome. Cash balances can be negative since this is movement accounting, not M6 capital permission.

Hold comparison uses **the same actual simulated entry quantity/cost/entry fee**, retains all net opening shares to the supplied outcome, and applies settlement fees. It is not a second entry on another quote. `exit_advantage = simulated_early_exit_pnl - hypothetical_hold_pnl` only when both are known. Early exit can lose to hold.

## Ledger and invariants

Every notional, fee, inventory acquisition, exit and redemption has a deterministic event reference and two equal/opposite ledger legs per asset. Accounts include CASH/MARKET/FEES/SETTLEMENT for collateral and INVENTORY/MARKET/FEE_SHARES/REDEEMED for shares. Their purpose is reconciliation, not a real broker balance.

Conservation: initial **net** shares = exited inventory shares + settled inventory shares + remaining shares. Exited inventory includes traded exit shares plus exit share fee; settled inventory includes redeemed plus settlement fee shares. Initial gross shares = initial net + entry share fee. At completed settlement remaining=0. Sum of ledger legs for each asset is zero; INVENTORY balance equals remaining; CASH balance equals realized cash flow. Net completed PnL reconciles to cash. No movement can exist without its order execution or settlement event in the captured result.

## Diagnostics and H1 report

Fixed entry slippage is `entry_fill_vwap - decision_best_ask`, not also an unrelated mid-relative number. Decision mid and M2 expected VWAP remain separate references. Spread impact is execution half-spread times traded shares; depth impact is VWAP minus execution best ask for buys, best bid minus VWAP for sells. They are explanatory components of prices already paid, not extra fees.

Paired latency impact is delayed entry VWAP minus zero-latency counterfactual VWAP, only when filled quantities match and both fill. Otherwise null with reason, avoiding depth/size confounding. Zero-latency counterfactual uses the first distinct later recorded quote, not the signal book. Exit rebound survival separately asks whether the delayed bid still meets the original threshold; an IOC exit may fill lower even when the rebound did not survive.

Latency grid: 0/100/250/500/1000/2000 ms, changing entry and exit latency together. Size grid: 1/10/50/100 requested shares, never beyond M3 approval. Exit policy grid contains all ten alternatives above. Demo is **one factor at a time**, not all combinations: baseline 250 ms and M3-approved 100 shares; latency/size studies use BID_REBOUND .20. All grid rows remain in original order, no PnL ranking or best parameter output.

H1 groups use M4.5 initial side-mid price buckets and TTE edges, including [240,300] seconds, and the full rebound grid. Initial conditioning is decision-time mid/TTE; trigger reference is actual entry VWAP, a distinct clearly named quantity. A post-hoc M4.5-style bid diagnostic counts observed rebound after entry; it is computed after simulation and never drives intent generation.

Funnel separates per-position observed-path rebound from per-attempt triggers, attempted exits, fresh books, surviving rebound, sufficient depth, full/partial/failed/pending exits. These are not identical denominators: repeated partial exits are multiple attempts. Stale observations and missed/partial exits remain visible. Resolved comparisons include unsuccessful exits followed by settlement and known-zero entry failures; unresolved open paths remain counted with null PnL. Repeated grids/markets are not independent observations and are not additive portfolio PnL. Synthetic results do not validate real-market H1.

## Persistence and replay

Schema 6 adds execution_runs/results and seven normalized audit projection tables: simulated_orders, simulated_order_events, simulated_fills, simulated_positions, simulated_exit_attempts, simulated_settlements and simulated_ledger_entries (21 tables total). Runs reference registered experiments; all projections have same-experiment run foreign keys. Inputs/config/policy/code/cutoff/creation metadata and hashes are archived. Projection business references are generated from and verified against complete deterministic replay, not accepted as arbitrary caller SQL records.

Writes of run/result/all projections are one transaction. UPDATE/DELETE/REPLACE are rejected. Retrying identical inputs preserves first creation metadata and does not double-fill, charge fees, settle or exit. Readback recalculates the full result and checks every normalized projection, hash and count. Migration failure rolls back. Existing M1–M4.5 records are untouched.

Run identity includes full input archive/config/policy/code/cutoff; business order/event IDs instead depend on immutable candidate/config/policy/code and the relevant event only. Adding future books or labels changes the analysis run, not already determined past events. Different cutoffs/scenarios store independently auditable runs; do not sum their repeated prefix ledger events as one capital account. Hashes are integrity evidence, not defense against complete administrator rewrite.

Demo writes only ignored runtime/v3/m5-demo.sqlite, m5-report.json and m5-report.md. JSON contains all 160 case/grid rows with full traces and group/funnel data. Markdown displays the entire grid and H1 funnel. No credentials, production DB or frozen blind performance are required. Stop after M5; M6 requires separate authorization.
