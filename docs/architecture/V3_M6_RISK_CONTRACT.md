# M6 Risk & Portfolio Permission Contract

Version: `risk-v1`. Synthetic/replay simulation only. M5 = execution realism → M6 = portfolio/risk permission → M7 = monitoring/dashboard (not implemented).

## Authority and scope

M6 consumes an immutable M1–M3 `ResearchObservation`. It validates lineage, retains the original side and refuses M3 `NO_TRADE`. It does not refit models, change calibration, recompute edge, select another side, adjust M5 latency, rewrite fills or modify settlement. No accounts, wallets, network adapter, real orders, leverage, Kelly or parameter search exist in this module.

`RiskRepository.evaluate` returns APPROVE / REDUCE / REJECT and atomically creates a reservation for nonzero permission. `RiskRepository.execute` requires that permission and invokes the unchanged M5 `simulate` with exactly the approved shares. Callers cannot supply another quantity, execution config or exit policy at execution time. Standalone M5 remains available for independent counterfactuals, but its unbound results cannot be imported as portfolio transactions.

Risk evaluation time must equal original M3 `evaluated_at`. This version cannot shift M5's original decision-time latency anchor to accommodate a later permission. Such inputs fail explicitly; no backdated approval.

## Fixed config and amount units

`RiskConfig` is immutable, canonical-hashed and versioned. Defaults are research fixtures, not recommended settings:

| Field | Default |
|---|---:|
| starting_capital | 1000 collateral |
| max_position_notional / fraction | 100 / 0.20 |
| max_total_open_exposure / fraction | 800 / 0.80 |
| max_pending_exposure | 400 |
| max_market_exposure | 200 |
| max_daily_simulated_loss | 50 |
| max_drawdown | 0.10 |
| max_consecutive_losses | 3 |
| minimum_available_cash | 0 |
| minimum_share_unit | 1 share |
| reservation_timeout | 10000 ms |
| max_portfolio_age_ms | 30000 |
| max_feed_age_ms / max_heartbeat_age_ms | 3000 / 5000 |
| validation_failure_burst_limit | 3 |
| require_data_health / require_provider_health | true / true |
| loss_day_timezone | UTC |
| pause_behavior | BLOCK_NEW_ENTRY_ONLY |
| equity_basis | CASH_PLUS_REMAINING_COST_BASIS |

M5 IOC has no limit-price order. Signal ask is therefore not a cash guarantee. M6 uses a **worst-case entry collateral bound**, including entry cash fees, for both `requested_notional` and `approved_notional`:

`bound_per_share = 1 + entry_fee.rate + entry_fee.collateral_per_share` for collateral fees; `1` for share fees. The binary price ceiling of one is conservative even where valid quotes are strictly inside (0,1). These fields are risk-budget amounts, not an assertion about actual fill notional. Actual cash consumption comes only from M5 ledger entries.

Requested shares are the original M3 `executable_shares`; M6 cannot increase them. All absolute exposure caps conservatively apply to the entire collateral bound, including entry fees. A fixed default share unit of 1 is a research assumption, not a verified venue lot size. Permission floors to a multiple of that unit; below one unit is REJECT. No float accounting or ambient decimal context is used.

To preserve no-borrowing without altering M5, portfolio mode rejects nonzero **exit/settlement fixed collateral-per-share fees** before reservation: they can make proceeds negative at a low bid or zero payout. Proportional collateral fees and share-denominated fees are supported. Standalone M5's fee behavior is unchanged. This restricted support is explicit, not a statement about actual venue fees.

## Accounting and exposure

Cash includes cash earmarked by reservations. Therefore:

```text
AvailableCash = Cash - ReservedCash
OpenExposure = remaining acquisition cost basis, including entry cash fees
PendingExposure = sum(active reservation remaining collateral)
TotalExposure = OpenExposure + PendingExposure
Equity = Cash + OpenExposure = StartingCapital + RealizedPnL
```

Do not add ReservedCash to equity again. Equity is realized-only / cost-basis equity, not mark-to-mid, mark-to-bid or liquidation value. Unrealized gains and losses are not used.

M5 `COLLATERAL/CASH` ledger legs alone change cash. M5 inventory legs determine actual inventory removed by exits and settlements, including share fees. Remaining basis uses proportional acquisition cost, rounded at 1e-18; the final disposal releases the exact residual basis. Realized profit is ledger disposal cash minus released basis. `settled_pnl` is the realized subset from settlement, not an extra cash credit. M5 `collateral_spent` already includes entry collateral fees; those fees are not added twice. Every completed position reconciles exactly to M5 net simulated PnL. A 100% entry-share fee produces zero inventory and an immediate completed loss.

Same-market YES and NO costs plus pending collateral are summed gross; no netting benefit. Side-specific exposure remains visible. No borrowed cash or negative available cash is permitted.

## Causality and order

Event timestamps are explicit UTC epoch milliseconds. Each run accepts nondecreasing `at`, with SQLite sequence defining same-ms order. A race winner is the first committed transaction; replay of that serialized sequence is deterministic, not a claim of scheduler-independent priority.

As-of state replays only risk events with `at <= cutoff`. M5 emits fills and settlement cash only when their availability is within its cutoff. An input archive can contain future quotes/outcomes; they cannot affect an earlier state or decision. Changing an already committed M5 business-event prefix is rejected. Reconciliation cannot introduce a new money movement older than the last portfolio event: process available fills before later candidates instead of rewriting previous permissions.

Caller archives must be complete for their declared as-of point. `RECONCILE` is an explicit synthetic/replay watermark assertion, not a live-provider completeness proof. Stale portfolio state blocks approval; a caller must reconcile/refresh explicitly. Health evidence is caller-supplied, contains only typed timestamps, booleans, counts and safe reference IDs, and is not a real feed probe. An unavailable/future/impossible timestamp fails closed.

## Reservation lifecycle

Approval and ACTIVE reservation are one `BEGIN IMMEDIATE` transaction. Independent connections must acquire the write lock before reading available funds. The same candidate ID in the same run retries identically; different input/config/time for that identity is a conflict.

IOC actual spend consumes collateral. A partial fill records PARTIALLY_CONSUMED followed by CONSUMED with the remaining amount released in the same transaction. For reserve 100 / actual cash use 60, consumed=60, released=40, remaining=0. Even a full share fill can release collateral because actual price is below the bound. NO_FILL releases all. Pending retains its reservation while active.

Reservation timeout must cover M5 latency plus maximum entry-book wait. The replay driver calls `expire` at or after the explicit deadline; it records EXPIRED and releases collateral, even if an old M5 prefix was pending. Read-only state queries do not write timer events. Expired/cancelled entry permission cannot later be resurrected by supplying historical quotes. No background clock or service is started by M6.

A risk pause revokes ACTIVE, still-unfilled permissions and records RELEASED / RISK_PAUSE. Previously created M5 pending audit records are retained; permission cancellation is recorded at M6, not fabricated as a new M5 fill or rewritten order event. Existing positions, partial exits and settlements continue under the original M5 policy. New entry is also checked against causally known health/control state at its actual M5 fill time. Existing-position processing does not require a new risk approval.

## Financial controls and resume

- UTC day is `[00:00, next 00:00)`. `daily_pnl` is causally realized net PnL; losses from partial disposal are included, unresolved inventory is not a realized loss.
- Daily pause latches when the current day's cumulative net realized PnL reaches `-max_daily_simulated_loss`. Later same-day recovery does not resume permission. Next UTC day resets only the daily latch.
- Peak equity includes initial capital and subsequent realized-equity highs. Drawdown is `(peak-equity)/peak`; its pause latches once the limit is reached for the run. Neither midnight nor manual RESUME resets it.
- Only completed positions with net PnL < 0 increment the loss streak. Zero or positive PnL resets the current streak. Equal-ms completion ties use immutable risk-decision ID. A reached loss-streak guard latches for the run even after subsequent recovery. Unresolved and partially disposed positions never count as completed losses.
- Data checks cover missing/stale source, missing/stale heartbeat, validation burst, source mismatch and impossible timestamps. Provider state is independently checked. Valid fresh evidence clears transient pauses deterministically.
- MANUALLY_PAUSED is controlled by explicit PAUSE/RESUME. RESUME clears only that manual state. There is no financial-reset API; a separate research run is a separate preregistered experiment, not a hidden reset of this history.

States may coexist: ACTIVE, PAUSED_DAILY_LOSS, PAUSED_DRAWDOWN, PAUSED_LOSS_STREAK, PAUSED_DATA, PAUSED_PROVIDER, MANUALLY_PAUSED. Automatic TRIGGER/CLEAR and explicit PAUSE/RESUME are immutable nested risk events with event ID, time, previous/new state, reason, trigger reference, config hash/version. Read-only historical queries derive state without inventing a stored control event.

## Deterministic reason precedence

Malformed lineage, conflicting retry, corrupt storage or invalid accounting is a hard transaction failure before permission; no reservation is committed to an untrustworthy state. `INVALID_PORTFOLIO_STATE` is reserved in the reason vocabulary, but corrupted storage is not converted into a normal candidate rejection.

For evaluable candidates, all reasons are retained in this order:

```text
UPSTREAM_NO_TRADE
MANUALLY_PAUSED
DATA_KILL_SWITCH
PROVIDER_KILL_SWITCH
INVALID_PORTFOLIO_STATE
STALE_PORTFOLIO_STATE
INSUFFICIENT_CAPITAL
POSITION_LIMIT
MARKET_EXPOSURE_LIMIT
TOTAL_EXPOSURE_LIMIT
PENDING_EXPOSURE_LIMIT
DAILY_LOSS_LIMIT
MAX_DRAWDOWN_REACHED
CONSECUTIVE_LOSS_LIMIT
SIZE_REDUCED
APPROVED
```

Cash/size/exposure restrictions may REDUCE. Upstream refusal, stale state and pause reasons always REJECT. The primary reason is first in this fixed order, even when a later financial guard makes the final action REJECT. Quantity rounding alone yields SIZE_REDUCED.

## Persistence and integrity

Schema 7 adds five tables to schema 6's 21: `risk_runs`, `risk_events`, `risk_decisions`, `capital_reservations`, `portfolio_snapshots`. Existing M1–M5 migrations only gain schema-7 recognition; their inference/execution semantics remain untouched.

`risk_runs` binds experiment FK, code Git SHA, canonical config/hash, creation time and version. Events bind the same experiment/run, immutable sequence, unique request key, complete typed input archive, deterministic output and previous/event hashes. Outputs retain the original M3 chain, exact M5 result including its ledger, reservation revisions, control transitions and before/after state. All rows reject UPDATE/DELETE/REPLACE.

M6 portfolios consume exact M5 outputs archived inside risk events, not separately aggregated standalone M5 counterfactual rows. This avoids charging repeated cutoff prefixes twice. Decisions, reservation revisions and snapshots are audit projections, not mutable balances. Restart/readback replays every permission and M5 archive and verifies every projection/hash/count. Atomic rollback covers all five tables. WAL read transactions give consistent snapshots. Cross-experiment originals/books/outcomes and cross-run permission references fail closed.

Hashes detect accidental corruption; they are not signatures against an administrator rewriting the whole database. Full-prefix replay is deliberately correctness-first and has not been optimized for long-running production volume.

## Evidence and limitations

Six mandatory demo cases: normal approval/full fill, position reduction, competing reservations, partial-fill release, daily pause with existing exit, and drawdown. Reports preserve complete M3 input, state before, decision, reservation, M5 trace, reconciliation and state after, plus exposure/utilization, reason counts, controls and funnel.

All tests/data in this milestone are synthetic. Actual venue fees, lot sizes, queue priority, cross-candidate competition for shared external book depth, feed completeness, latency and real liquidation value remain unverified. M5 snapshots are not matching-engine orders. This milestone proves neither profitability nor safe real-money sizing. No V2 blind performance was read. STOP after M6; M7 is not started.
