# M9.1 Source Contract Verification

2026-10-06. Base `84b2c28e9344733b140f4d703c6d0eb6a95643c4`.
Branch `codex/m9-1-binding-collection`. **NOT_READY; bridge prohibited;
real collector disabled; no frozen study manifest generated.**

## Evidence scope

Repository source, local frozen model metadata and official documentation only.
No old sealed evidence, database, blind observations or performance results were
read. No training, prediction inference, wallet, orders, SSH or study execution.
Model SHA256 rechecked:
`5b4a46e5394c095848cc3191b9f1f8cb4de7366fc1ed496c88baf0561ce6749f`.
Artifact version `v2-9e452c59ebf7`, symbol BTCUSDT, sample_seconds 5,
elapsed support 5 through 295 seconds, classes [0,1], calibration Platt.

The model identity is verified locally. Training semantics below are established
by the unchanged source path and matching artifact metadata; training archives
were not reloaded and a complete historical training run was not reproduced.

## Prediction Target Contract

Source: Binance **Spot BTCUSDT kline OHLC**, specifically real one-second daily
archives used to build causal partial minutes and five-minute labels. It is not
a futures mark price, index price, oracle midpoint, or current aggregate-trade
poll. Spot candles describe traded prices; a candle close must not be replaced
by an arbitrarily sampled latest-trade response.

Code: `btc5/archives.py:read_archive/seconds_dataset`,
`btc5/features.py:compute`, `btc5/v2research.py:fit_suite`,
`btc5/research.py:Predictor`, `btc5/live.py:handle_kline`.

Let C be the UTC-aligned cycle start in epoch milliseconds and E=C+300000.
The label interval is [C,E). O is the open of the first second at C; F is the
close of the last second starting E-1000 (close_time E-1). Complete minute/cycle
coverage is required. O/F are bar values, not proof of trades exactly at C/E-1.

- UP iff F > O; DOWN iff F < O; TIE iff F == O, using the implementation's
  numeric comparisons without a tolerance. No cancellation training class.
- Binary label y=1 for UP, y=0 for both DOWN and TIE.
- `predict_proba(...)[1]` estimates P(F>O | causal inputs).
- Its complement estimates P(F<=O), not strict P(F<O) and not a NO payout.
- For each in-cycle observation, prediction targets this SAME cycle's terminal
  F relative to its original O. It does not target price at observation+5min,
  or terminal F relative to the current price.
- At the five-second grid, training as-of is C+5000*k-1, k=1..59.
  Rounded feature elapsed_seconds is 5*k; remaining_seconds is 300-5*k.
  Exact E-asof milliseconds is one millisecond larger than rounded remaining.
  Neither rounded feature time nor archive as-of is a live generated_at.
- Archived microseconds are floored to milliseconds and bar boundaries checked.
  The final second is used as a supervised label, never as an earlier feature.
- Live V2 reads Binance Spot kline `k.o/k.c/k.t`; as-of is
  min(event E, minute_start+59999). It remains a Binance feature/target engine,
  not a venue-bound model service. Its timestamp cannot be reused as the actual
  M9.1 inference completion or durable append time.

### Comparison with Predict.fun

| Dimension | Frozen predictor | Venue requirement / current evidence | Compatibility |
|---|---|---|---|
| Cycle | [C,C+300000), UTC aligned | Actual category startsAt/endsAt, must verify 5m | Unverified live |
| Source | Binance Spot BTCUSDT traded-price candles | Exact provider/feed ID/rules per real market | Not proven equivalent |
| Initial price | First second's candle open | Venue rule's opening reference observation | Not proven equivalent |
| Final price | Last second's candle close | Venue oracle/rule endpoint semantics | Not proven equivalent |
| UP | Strict F>O | Explicit rule plus UP token mapping | Unverified live |
| Complement | DOWN OR TIE | NO/DOWN payout, including tie/cancel cases | Not interchangeable |
| Half-payout | Not modelled separately | Legacy checker expects half-payout ties; current rules unverified | No proven transform |
| Cancel | No label | Must obtain authoritative cancellation/payout evidence | Missing |

Legacy `btc5/forward.py:rule_profile` expects Chainlink BTCUSDT and half payout
for equality. That historical checker is not a current-market fixture. Official
API schema exposes provider/feed metadata; its example values do not select an
actual provider for this study.
[Market schema](https://dev.predict.fun/market-14037477d0)
[Category schema](https://dev.predict.fun/get-category-by-slug-25326911e0).

No deterministic transform has been proven. Even under an identical price
source, if tie payout is 1/2, expected YES payout would be
P(UP)+0.5*P(TIE), which cannot be reconstructed from P(UP) alone. Distinct
Binance and oracle price paths add a separate unproven relationship. Similar
prices or correlated outcomes do not establish semantic identity.

**Prediction bridge remains disallowed.** Options for a later approved phase:
retain this model explicitly as a Binance-only research proxy with no venue
probability claim; or define a new research predictor for the verified venue
target, then fit/calibrate and independently validate it on authorized data.
If the actual venue target differs, training that target (or another justified
new predictor) is needed; relabeling this frozen artifact is insufficient.
No retraining is performed or authorized by this audit, and old OOS evidence
must not be used for target/model selection.

## Predict.fun Market Contract

Production response verification is **BLOCKED_NO_LOCAL_CREDENTIAL**. Both
`PREDICTFUN_API_KEY` and legacy `PREDICT_API_KEY` process environment values
were absent. No key search, credential file read, public proxy fallback,
testnet substitution or permissions change was attempted.

Required permission: an existing mainnet API key allowed to read public market
metadata/status, via `x-api-key` to `api.predict.fun`. No wallet JWT, signature,
balance permission or trading permission is needed for this scope. The exact
key entitlement and local reachability have not been tested.
[Authentication and default limits](https://dev.predict.fun/).

| Field to verify | Read-only candidate | Current state |
|---|---|---|
| market_id, conditionId, oracleQuestionId, resolverAddress | GET /v1/markets/{id} | Not captured |
| category identity, start/end | categorySlug -> GET /v1/categories/{slug} | Not captured |
| YES/NO, UP/DOWN token identity | outcomes name/indexSet/onChainId plus rules | Not captured; never use array order |
| reference/opening and oracle | crypto provider/feed ID/symbol/startPrice plus exact description | Not captured |
| rule text/hash | original rule-bearing response bytes and explicit text hash convention | Not captured |
| lifecycle vs trading status | status and tradingStatus, retained separately | Not captured |
| tie/cancel behavior | explicit rules and authoritative payout/status examples | Not captured |
| rate-limit headers/429 behavior | bounded GET headers, no intentional load-to-limit test | Not captured |

Documentation describes a withdrawn/Removed status outside the ordinary
lifecycle, but it does not establish a payout or irreversibility guarantee.
Do not map every closed/removed/cancelled state to LOSS or half payout.
[MarketStatus](https://dev.predict.fun/marketstatus-14037482d0).

There is **no real response fixture** in this delivery. The capture-status file
under tests/fixtures records the missing evidence, not an invented response.
Future authorized capture must record raw successful public response bytes,
SHA256, method/endpoint, request and receipt UTC times, HTTP status, safe
rate-limit/Date headers and capture scope=CONTRACT_AUDIT_NOT_STUDY. Keep auth,
cookies and account information out. If unexpected sensitive content appears,
do not commit it; record capture rejection. Redacted content must never be
labelled byte-identical raw evidence. Capture market/category and resolved,
tied/cancelled examples when legitimately available, with explicit missing
cases; do not manufacture examples or deliberately exhaust quotas.

## Settlement Contract

Candidate is the official market detail response: explicit RESOLVED status
and a resolution outcome whose index/token identity agrees with the frozen
mapping, or a uniquely WON outcome after consistency checks. This remains a
candidate until production payload/finality semantics are verified. Conflicting
resolution and outcome fields reject; outcome price=0/1, endPrice and BTC
movement are never substitutes.
[Outcome schema](https://dev.predict.fun/outcome-14037514d0).

The reviewed Market schema does not establish native settled_at. Public status
topic tsMs is an event timestamp; it is not documented proof of resolution
finality. Orderbook lastOrderSettled concerns orders, not market outcome.
[Public status topics](https://dev.predict.fun/subscription-topics-1915507m0).

Whether an apparently resolved market may reopen or have revised outcomes is
**UNKNOWN**. No irrevocability or 24-hour completion guarantee was verified.
One successful resolved response cannot prove either. Require provider-backed
finality semantics or a verified resolution event/contract before accepting an
outcome as final. Contradictory observations are append-only conflicts, never
silent overwrites. Unknown cancellation/tie payouts remain NOT_READY.

### Auditable time alternative (proposal, not implemented)

- `native_settled_at`: nullable, set only from proven source semantics.
- `first_observed_resolved_at`: local first receipt of a claimed resolved state.
- `first_observed_final_at`: local first receipt of evidence that satisfies an
  explicitly versioned finality predicate; null until that predicate is proven.
- `available_at`: completion of validation/finality verification, at or after
  the relevant receipt. Inference may use nothing available after its cutoff.
- `time_basis`: NATIVE_EVENT or LOCAL_FIRST_OBSERVED_FINAL; never interchangeable.
- `source_identity`, `raw_status_hash`, `finality_policy_version`,
  `finality_evidence_hash`, `last_observed_nonfinal_at` (nullable), and append-only
  revision/conflict records make the observation auditable.

Preserve first-observed values across restarts. If first observation follows an
outage, it stays the later receipt; never infer a prior receipt or exact event
time. A local receipt proves when this collector learned the outcome, not when
anyone could first know it. Thus prediction-before-first-receipt alone does not
prove prediction-before-outcome; require pre-expiry generation/append AND
verified rules that forbid earlier determination, or an authoritative time bound.

Current M9.1 requires native `settled_at`, and its synthetic M10 adapter relies
on that chronology. Using the proposed alternative requires an explicit schema
version and causal-check review; this audit does not replace settled_at with
receipt time or weaken any existing gate. Unproven finality stays missing even
if local observation time is known. Stop all follow-up at the predeclared deadline.

## Timestamp semantics table

| Timestamp | Clock / meaning | Must not be used as |
|---|---|---|
| C / E | UTC cycle start / exclusive end from validated venue definition | Actual native settlement or oracle tick time |
| archived second timestamp | Binance bar opening boundary, normalized ms | Local receipt |
| close_time=second+999 | Inclusive bar endpoint at ms resolution | Proof of a trade exactly then |
| training as-of | Last admitted second close endpoint | Live generated_at |
| elapsed/remaining features | Rounded seconds in V2 model input | Exact remaining_ms |
| generated_at | Local real inference completion | Backdated feature time |
| received_at | Local transport receipt | Source occurrence time |
| available_at | Local completed validation/availability | Native settlement |
| status tsMs | Venue event clock (documented) | Proven irreversible resolution time |
| native_settled_at | Verified source event time, otherwise null | Local discovery time |
| first_observed_final_at | First receipt meeting proven finality predicate | Exchange-native settled_at |

## Blocker disposition

| Prior blocker | This stage | Cleared? |
|---|---|---|
| Frozen predictor identity/target unclear | Model identity verified; source, cycle, labels, tie and rounding documented and synthetic-tested | Identity/definition yes; bridge compatibility NO |
| Reference/target mismatch | No equality or deterministic transform proved | NO |
| Real market identity/rules/state | Local credentials absent; no production fixtures | NO |
| Settlement time/finality | Honest local-observation alternative specified; native time and finality still unverified | NO |
| Read-only auth/limits | Permission scope documented; actual auth and headers untested | NO |
| Real transport/M10 binding | Unchanged, intentionally outside this stage | NO |

Cannot generate a frozen real study manifest. Current source gates stay disabled.
Changes are contracts, capture-status evidence and synthetic semantic regression
tests only.

## Delivery verification

- Full local regression: **968 passed, 2 skipped in 74.61 seconds**, including
  three new synthetic UP/DOWN/TIE target-contract tests.
- Staged-file and Git-history credential scans: **0 findings** in both.
- All **95 protected baseline hashes match**; main, v3-dev and frozen V2 tag
  references unchanged. Runtime source, model, config and old evidence unchanged.
- No remote CI run, push, deployment or authenticated production response claim.
