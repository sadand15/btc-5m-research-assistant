# M9.1 Phase 3b — Offline public-rule contract review

Date: 2026-10-08. Base: `08e4096058caf9112a1b20ffcc71d722698cb61b`.
Branch: `codex/m9-1-binding-collection`.

**NOT_READY. Prediction compatibility: TARGET_MISMATCH for the two official
BTC 5m contracts identified below. No prediction bridge or frozen real manifest.**
This supersedes the earlier insufficient-evidence verdict only for these newly
identified contracts; it does not claim every past/future BTC market shares them.

## Evidence and scope

The runtime probe directory still contains only the previously reviewed
`461d047389dc448fb480674fcfcdce15` run. There are no new authenticated Phase 3b
fixtures. Its daily and 15m contracts are not used as five-minute evidence.

Official public homepage links led to two anonymous public market pages:

| Official page | Displayed title window on October 8 | Visible observation |
|---|---|---|
| [btc-updown-5m-1791453300](https://predict.fun/market/btc-updown-5m-1791453300) | 5:55AM–6AM ET | Live label; not API OPEN proof |
| [btc-updown-5m-1791453000](https://predict.fun/market/btc-updown-5m-1791453000) | 5:50AM–5:55AM ET | Resolved label; not finality proof |

Both titles describe five-minute windows. Slugs are public identifiers, **not
numeric API market IDs**. Explicit token IDs, native category timestamps and
API state bindings remain INSUFFICIENT_EVIDENCE. No numeric ID is invented from
the epoch-like slug suffix. The title alone cannot prove exact millisecond or
inclusive/exclusive timestamp conventions.

[Public evidence index](V3_M9_1_PHASE3B_PUBLIC_RULE_EVIDENCE.json) records URLs,
local UTC retrieval times, page/rule hashes, titles and paraphrased rules. These
are public-page review records, not sanitized API fixtures or study evidence.
Full HTML was not persisted; hashes identify what was read but cannot substitute
for an archived original. The web extraction tool could not open the market
links; anonymous HTTPS GET successfully returned both pages with HTTP 200.
No credentials, account session, market API, wallet or order endpoint were used.
Labels may be cached; retrieval time is not a native market-event timestamp.

## Venue contract and remaining field uncertainty

Both public rules designate Chainlink BTC/USDT, specifically the
`btc-usdt-topofbook-datalink` stream. They describe Binance best-bid/best-ask
midpoint converted into quote currency; other spot-price sources are excluded.
The terminal reference uses the preceding five-minute Chainlink candle close.
The initial value is the price at the range's beginning, without an exact tick
selection rule. These are statements in the venue rules, not an independently
reproduced oracle calculation.

UP uses strict greater-than, DOWN strict less-than, and equal prices receive
50/50 settlement. If Chainlink is unusable, the rules allow reliable-source
consensus. They do not establish a deterministic fallback selection algorithm.
Cancellation/invalid-market payout is **INSUFFICIENT_EVIDENCE**; data-source
fallback is not a cancellation rule. No tied/cancelled example was observed.

| Field | Contract finding / confidence |
|---|---|
| Primary price source | RESOLVED in these public rules: Chainlink BTC/USDT midpoint stream |
| Starting reference | Beginning-of-window price stated; exact sample, staleness and rounding: INSUFFICIENT_EVIDENCE |
| Ending reference | Preceding 5m Chainlink candle close stated; publication delay and exact last-sample rule: INSUFFICIENT_EVIDENCE |
| UTC [C,C+300000) alignment | INSUFFICIENT_EVIDENCE for API/native boundaries; five-minute ET titles are not the complete boundary contract |
| Strict UP / strict DOWN / equality | RESOLVED at rule level; greater / lower / half payout |
| YES/NO ↔ UP/DOWN token binding | INSUFFICIENT_EVIDENCE; do not infer from button order |
| Cancellation, invalidity, fallback authority | INSUFFICIENT_EVIDENCE beyond the stated consensus fallback |

## Settlement and lifecycle contract

The resolved label on the second public page establishes only that the UI
reported a resolved state. It is not sufficient evidence for a token-linked
authoritative outcome, payout vector, native settled timestamp or finality.
No result is inferred from BTC prices or chart direction.

The official [market-detail schema](https://dev.predict.fun/get-market-by-id-25552989e0)
offers a `resolution` object and token/outcome identifiers. Those are candidate
binding fields, not filled-in evidence for these two markets. The public
[MarketStatus documentation](https://dev.predict.fun/marketstatus-14037482d0)
distinguishes withdrawn/Removed from ordinary progression; this does not define
its payout or prove a terminal irreversible state. Schema examples are not
production responses.

`native_settled_at` and `first_observed_final_at` remain null. A future
`first_observed_resolved_at` must identify its evidence channel (UI or verified
API) and local run scope; it cannot be renamed native settled time. Finality
requires a versioned authority/decision rule and supporting evidence, including
revision/dispute behavior. No approved such rule exists for these samples.

**Verified lifecycle transition edges: none.** The two labels belong to different
markets. They cannot establish LIVE → RESOLVED, intermediate states, or inability
to reopen. No claims are made about resolution within the 24h follow-up window.

## Frozen model comparison

Frozen [model target](../architecture/V3_M9_1_SOURCE_CONTRACT_VERIFICATION.md):
Binance Spot BTCUSDT traded-price candles, UTC [C,C+300000), final close versus
first open; UP iff close>open, label 0 includes close<=open.

The observed venue instead defines an oracle quote-midpoint target. A common
upstream Binance name is not price-series identity. Trade close does not encode
best bid/ask, their timestamps, oracle aggregation or publication decisions.
Different quote paths can coexist with the same trade OHLC. Consequently no
proven deterministic transformation from the frozen model's inputs/output to
this oracle event is available. The explicit difference suffices for
**TARGET_MISMATCH** even while other fields remain unknown.

Let p=P(close>open) for the frozen traded-price event and q=P(close=open).
Then 1-p=P(close<=open); strict DOWN is 1-p-q. Even if a future predictor used
the correct venue price series, a half-tie contract would have expected UP
payout p+q/2 and DOWN payout 1-p-q/2, not simply p and 1-p. This algebra is a
synthetic semantic example, not an estimate of tie frequency or venue value.
Unknown cancellation outcomes would require additional explicit treatment.

Neither EXACT_EQUIVALENCE nor DETERMINISTIC_TRANSFORM_POSSIBLE is supported.
Do not relabel frozen V2 probabilities. A separately defined oracle-target
research predictor may be investigated offline later; no retraining or live
bridge is performed here.

## Exact blocker ledger

All OPEN items below retain INSUFFICIENT_EVIDENCE for their missing fields.

| ID | State | Blocker / evidence needed to close |
|---|---|---|
| B01 | RESOLVED, public-page scope | Official BTC 5m product and two exact page slugs identified. |
| B02 | RESOLVED, rule scope | Primary source, direction comparisons and half-tie rule established for these pages. |
| B03 | OPEN | Bind numeric market/category IDs, two token IDs and rule version/hash to these same markets. Need sanitized metadata or equivalent independently verifiable public binding. |
| B04 | OPEN | Native start/end timestamps, UTC alignment, inclusivity, initial tick selection, rounding, delayed/missing oracle samples. Need authoritative source/boundary specification. |
| B05 | OPEN | Normal, tied, cancelled and invalid payout vectors and authorized fallback process. Need explicit rules and linked outcomes; unavailable exceptional cases stay unknown. |
| B06 | OPEN | Authoritative resolved outcome mapped to exact tokens; UI label alone insufficient. Need resolved same-family binding evidence. |
| B07 | OPEN | Native timestamp semantics or explicitly accepted observed-time alternative; irreversible finality, dispute/reopen/revision authority. Need versioned finality proof/policy. |
| B08 | OPEN | Fixed 24h follow-up adequacy. No timing guarantee; policy must retain missing/unresolved cases rather than extend the window. |
| B09 | OPEN — known mismatch | Frozen predictor targets another random variable. More metadata alone cannot close this; require a proven transform or a separately approved predictor with matching source, horizon and payout semantics. |
| B10 | OPEN | Prospective inference/reference causal bindings and full sealed-dataset replay readiness remain unestablished. No real manifest may be generated. |

## Synthetic/offline work that can proceed

These are scoped next tasks, not claims that new tests were implemented here:

1. **Target-equivalence truth table:** feed, instrument, price type, sample
   boundaries, tie and cancellation branches. Acceptance: any missing dimension
   yields insufficient evidence; explicit mismatch blocks the bridge.
2. **Quote-versus-trade counterexamples:** synthetic identical trade OHLC with
   distinct midquote outcomes. Acceptance: no automatic Binance-name equivalence
   or forced mapping of frozen probabilities.
3. **Tie-aware probability/payout contract:** synthetic UP/DOWN/TIE and unknown
   cancellation cases. Acceptance: binary complement cannot supply a missing tie
   probability; missing payout rules fail closed.
4. **Oracle boundary replay:** synthetic stale, delayed, duplicate and out-of-order
   reference events around C and E. Acceptance: receipt/availability causality,
   no future inputs, no invented tick or zero-age default.
5. **Settlement state-machine fault cases:** mock resolved/revised/disputed,
   absent finality, missing native time and follow-up timeout. Acceptance:
   append-only conflicts, explicit unknown finality and no window extension.
6. **Evidence binding audit:** synthetic mismatched IDs/tokens/rule hashes and
   complete sealed fixtures. Acceptance: M10 refuses incomplete real eligibility;
   synthetic readiness never implies real readiness.

Use only synthetic or explicitly permitted offline research data. No old
sealed evidence, partial OOS results, threshold optimization, new study or
changes to frozen model/calibration are needed for any task above.

## Verification and operational scope

Documentation/evidence-index changes only; no new executable behavior or tests.
Previous full suite at base commit: **1042 passed, 2 skipped** (not rerun for this
documentation-only review). Source/protected-ref and credential checks are
performed before committing. No runtime enable flag or service was changed;
the real collector gate remains unmodified. VPS process state was not queried.
No arm/start command, account connection or sealed-evidence access occurred.
