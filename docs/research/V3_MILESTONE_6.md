# V3 Milestone 6 — Risk Engine & Portfolio Permission

## Scope and preflight

M5 approved baseline: `d4b91c9b881b1ae30988b3fbd35fed04191d53ee`, branch `v3-dev`, initially clean. Its [Windows/Linux CI](https://github.com/sadand15/btc-5m-research-assistant/actions/runs/36509353696) was rechecked as successful before M6 development.

V2 original main remained `11c7d06b988b9177f84cf0f34920ad38c4021add`; annotated frozen tag object remained `fa9757a2e3fd132121a7c7e85307553b1f008a29`. All 27 protected hashes matched `runtime/m0-safety.json`; local/remote main and frozen references matched. No production observation database, blind-test performance, model, calibration or threshold was used for this work.

M6 is offline synthetic portfolio permission. It adds no real account, wallet, order submission, leverage, Kelly, parameter optimization or M7 dashboard.

## Delivered behavior

Immutable config/decision/reservation/state archives and a serialized risk event log now connect original M3 candidates to unchanged M5 simulation. Permission is APPROVE / REDUCE / REJECT. Approval and capital reservation commit atomically; identical retries are idempotent and conflicting retries fail. Competing connections cannot spend the same reserved cash.

Only approved shares enter portfolio-mode M5. Entry reserves binary worst-case cash plus entry fees; actual M5 ledger cash consumes the reservation and releases unused collateral. Open/pending and YES/NO same-market gross exposure are included in limits. Pending can expire through an explicit timer event; paused or expired permissions cannot revive.

Portfolio cash comes from M5 ledger movements. Equity uses remaining acquisition cost basis, not mid or assumed sale value. Daily loss, drawdown and completed-position loss-streak guards are causally reconstructed. Daily pause resets only on the next UTC day; drawdown/loss-streak latches remain. Manual and transient data/provider controls are separately auditable. Pauses revoke unfilled permissions while preserving exit, partial exit, settlement and reconciliation of existing positions.

The precise amount definitions, precedence, fee support restriction, reservation timeout driver, health evidence and persistence contracts are in [V3_M6_RISK_CONTRACT](../architecture/V3_M6_RISK_CONTRACT.md).

## Synthetic evidence

The deterministic demo records six isolated cases and includes original M3 input, state before, permission, reservation revisions, M5 outcome and state after:

| Case | Required observation |
|---|---|
| Normal | 100 shares approved; delayed M5 full fill; cash and cost basis reconcile |
| Position cap | Requested risk budget 180 reduced to 100 |
| Reservation competition | Cash 100, first reservation 80, second request 50 reduced to 20 |
| Partial fill | Partial IOC consumes actual cash, releases all unused reservation |
| Daily loss / exit | Known loss reaches 50; new candidate refused, pre-existing position can still exit |
| Drawdown | Initial/peak equity 1000, realized equity 850, drawdown 15%; 10% guard refuses new risk |

Separate regression covers exactly reserve 100 / actual spend 60 / release 40, completed three-loss streak, UTC rollover, partial share-fee exits, zero-profit reset, 100% entry share fee, missing/invalid health, two-connection concurrency, atomic insert failure, corrupted rows/projections, restart replay, future-loss causality, source immutability and exact equality with standalone M5 output at the same approved size.

These are fixture outcomes, not empirical market results or recommended stakes. No historical PnL selection was performed.

## Files and reproduction

New implementation: `src/btc5_v3/risk/{models,engine,report,demo}.py`, `storage/risk_repository.py`; tests: `tests/v3/test_v3_risk.py`. Existing storage modules only extend schema compatibility to 7. README, architecture, database, roadmap, package metadata and CI describe/run M6.

From a clean committed V3 checkout after installation:

```powershell
python -m pytest -q
python -m btc5_v3.risk.demo --project-root .
python scripts/security_scan.py index
python scripts/security_scan.py history
```

The demo writes only ignored `runtime/v3/m6-demo.sqlite`, `m6-report.json`, `m6-report.md`, with actual code Git SHA and risk config hashes. Existing demo metadata never impersonates a new source revision. CI runs all seven synthetic demos and history scanning without a real API Key.

## Validation and delivery record

M6 adds **82 synthetic tests**. Full local legacy + M1–M6 regression: **580 passed, 2 skipped**; the two skips are existing local Windows symlink privilege conditions. No tests were disabled for M6. The six-case demo also passes twice with identical results in the synthetic test suite.

Final staged/history credential scanning, frozen-reference/hash recheck, standalone committed demo and Windows/Linux CI are delivery gates. Their final commit-specific status is recorded by the matching Actions run and delivery reply, rather than embedding an unverified future CI result here. M6 is delivered as one independent commit on `v3-dev`; main and frozen tags remain untouched.

## Limitations and stop

Health/completeness is explicit research evidence, not a live feed probe. Callers must process available money events before later permissions; backdated reconciliation is rejected. Exit/settlement fixed collateral-per-share fees that could produce negative proceeds are unsupported in M6 portfolio mode. Expiry needs an explicit replay timer event; there is no background service. No MTM risk, real venue lot-size verification, queue modeling or proof of cross-candidate external liquidity exists. Full replay is not yet a production-scale performance design.

This milestone does not demonstrate real profitability, optimal risk parameters or safety to trade. **M5 = execution realism; M6 = portfolio/risk permission; M7 = monitoring/dashboard. STOP; M7 has not begun.**
