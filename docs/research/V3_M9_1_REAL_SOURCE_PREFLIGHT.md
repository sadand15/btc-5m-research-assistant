# M9.1 Real Source Preflight Audit

Audit date: 2026-10-06. Branch: `codex/m9-1-binding-collection`.
Audited implementation: `6bf18fa93e4c768d0fbf494d2bd27cdc71f0ed86`.

**NOT_READY. Real collector remains disabled. No real study manifest is issued.**
This commit freezes the audit findings and candidate source identities, not an
approved live configuration. Public documentation is a schema reference, not
proof of current production payloads, finality, availability or service SLA.

## Scope and evidence

- Read repository source/contracts and official public documentation. No old M9
  payload, SQLite, segment or seal was opened; no performance analysis or tuning.
- Read only the local V2 model artifact and the model identity fields of its V2
  freeze manifest. No inference, training or historical prediction reads.
- One local Binance public GET returned HTTP 200, required `a/p/q/T` fields
  present, elapsed 1311 ms. Payload discarded; no study writes. This is not a
  VPS reachability, clock-accuracy or sustained freshness test.
- Predict.fun authenticated probe NOT_RUN: no `PREDICTFUN_API_KEY` in this
  process environment. No credential file opened, no SSH, no account API.
  An existing VPS credential may still exist; it was not inspected.
- The old protected root is the previously recorded
  `f8f6752c1afd349f39fef5cced0d374fc60444a9fa8b5547c9372fe26b9c9c95`.
  Its contents were neither modified nor re-verified in this task.

## Real Source Matrix

| Source | Candidate | Authentication / read-only scope | Audit result | Critical gap |
|---|---|---|---|---|
| Prediction | Local V2 `btc5.research.Predictor`, frozen artifact below | Local read/inference, no API authentication; do not launch `LiveEngine` | NOT_READY | Binance UP target is not a verified Predict.fun payout target; no M9.1 production prediction bridge |
| BTC Reference | Binance Spot BTCUSDT latest aggregate trade | Public GET, no key | FIELD_MAPPING_AVAILABLE; source overall NOT_READY | Auxiliary trade reference only; cannot replace venue oracle or opening reference; real transport bridge/health not frozen |
| Market State | Predict.fun market detail + category + public status topics | Mainnet API key; GET/public subscriptions, no wallet JWT | NOT_READY | Exact current rules, identity mapping, opening-reference timestamp and state-time semantics unverified |
| Settlement | Predict.fun resolved market response, independently corroborated authoritative resolution record | Market-data key; possible read-only chain RPC with no signing | NOT_READY | Actual authoritative settlement time, split/cancel/finality proof and deadline feasibility unverified |

None of these rows grants permission to arm. The Binance result is not target
compatibility approval. M9.1 currently requires definition feed/source to equal
reference feed/source, so a Binance auxiliary reference cannot be silently
assigned to a Chainlink/Pyth venue target.

## Prediction field mapping and artifact identity

The configured local candidate is `runtime/v2/seconds/model.joblib` in the
original local project, not copied into this worktree. Its byte SHA256 matches
the `runtime/forward/manifest.json` model SHA256. It is not evidence that a
prediction service is currently running or that a VPS has this same artifact.

| Required field | Evidence / mapping | Status |
|---|---|---|
| model_version | artifact `version = v2-9e452c59ebf7` | PRESENT, local identity only |
| model hash | `5b4a46e5394c095848cc3191b9f1f8cb4de7366fc1ed496c88baf0561ce6749f` | PRESENT |
| model implementation | `selected_name=lightgbm`, `CalibratedClassifierCV` | PRESENT |
| calibration_version | artifact `calibration=platt`; no separately versioned venue-target calibration | MISSING production binding; method alone is not version |
| feature_schema_version | artifact `schema=causal-minute-v1` | PRESENT |
| feature hash | ordered column-list hash below; feature implementation/provenance bundle still needs its own explicit binding | PARTIAL |
| config hash | artifact full-config hash below; not yet a canonical M9.1 inference-only config | PARTIAL |
| p_up | `Predictor.predict` returns calibrated probability for Binance candle close greater than open | DERIVABLE, wrong/unconfirmed venue semantics |
| p_down | `1-p_up` denotes non-UP in the binary training label; ties are included in non-UP | AMBIGUOUS for DOWN and half-payout venue ties |
| generated_at | future bridge clock after inference, never caller-supplied historical time | MISSING real bridge |
| market_id/start/end | must bind explicit venue identity before inference; V2 predictor alone returns a scalar | MISSING real bridge |
| input snapshot hash / cutoff | hash only causally available feature inputs, including warm-up provenance | MISSING real bridge |
| horizon/TTE | explicit venue end minus generation time, checked again at append | DERIVABLE once identity/bridge validated |

Observed metadata hashes use SHA256 of UTF-8 `json.dumps(value, sort_keys=True,
separators=(',', ':'), ensure_ascii=False, allow_nan=False)`:

- Ordered artifact columns: `546dab9e64a145feafe1b9e52be98a77e2493bbc516a44b9b666ad8644e7f4f0`.
- Full artifact config: `e9c79603873fb8e9db6415d405995991a96efac0053819c308e10744968a4646`.
- Artifact `fit_end=1789793100000`, symbol `BTCUSDT`. This timestamp is model
  fit provenance, not a prediction generation time.

Code evidence: `btc5/research.py` Predictor/dataset, `btc5/v2research.py`
artifact construction, `btc5/features.py`, `btc5/forward.py` rule_profile.
The legacy rule checker expects Chainlink and equal-price half payout. This
is a historical code expectation, not verification of today's venue rule.
No new model/calibration is selected here and no old evidence is used to fit one.

Production acceptance must enforce inputs available before inference, completion
and durable append before market end, no earlier authoritative resolution,
post-inference market recheck, and committed-ID deduplication. A process crash
before commit leaves a missing prediction; do not reconstruct its timestamp.
V2 `LiveEngine.repair` downloads historical candles and invokes paper settlement;
launching that engine is not an acceptable M9.1 bridge. Warm-up and restart must
use predeclared causal inputs, with unavailable history causing rejection.

## BTC Reference field mapping

Candidate: `GET https://data-api.binance.vision/api/v3/aggTrades`, explicit
`symbol=BTCUSDT&limit=1`, no historical range. The official Spot endpoint has
weight 4 per request; `T` is the trade timestamp, `p` price, `a` aggregate ID.
At five-second polling this reference alone costs 48 request-weight/minute;
total IP limits must be read from exchange information and response headers.
[Binance market endpoint](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market)
[Public market data and default millisecond units](https://developers.binance.com/en/docs/products/spot/rest-api).

| Required field | Mapping | Status |
|---|---|---|
| price | decimal `response[0].p`, finite and positive | DOCUMENTED; shape probed |
| source / symbol / feed semantics | BINANCE_SPOT / BTCUSDT / latest aggregate trade in USDT per BTC | DECLARABLE, auxiliary only |
| source timestamp | `response[0].T`, UTC epoch ms; no microsecond override | DOCUMENTED |
| received_at | local UTC after response receipt, persisted once | DERIVABLE |
| source_health/freshness | HTTP/schema/monotonicity/clock checks plus received-source age | DERIVABLE; limits not approved for production |
| cycle alignment | select explicit venue cycle; require source/receipt/cutoff causal order | REQUIRES bridge |
| opening reference / oracle semantics | aggregate trade is neither exact boundary oracle observation nor venue startPrice proof | MISSING |

Do not round a sampled trade into a fabricated opening tick, interpolate gaps,
or replace receipt time by trade time. After reconnect retain dedup IDs, fetch
only newly received data, and preserve gaps. Duplicate old trade timestamps do
not become fresh because a request succeeded. V2 model's candle/depth input
requirements exceed this single price feed.

If the venue actually requires Chainlink, its authenticated Data Streams feed
is a separate candidate, with feed ID, schema, units and report time semantics
requiring verification. Its credentials are independent of Predict.fun. No
Chainlink access, subscription entitlement or rate allowance was verified.
[Chainlink Streams](https://docs.chain.link/data-streams)
[Authenticated report access](https://docs.chain.link/data-streams/tutorials/ts-sdk-fetch).

## Market State field mapping

Official candidates: `GET /v1/markets/{id}`, `GET /v1/categories/{slug}`.
Mainnet uses `x-api-key`; no wallet authentication is needed for these data
reads. Default documented REST allowance is 240 requests/minute per key;
actual key/endpoint limits remain untested. Never put keys in URLs or evidence.
[Predict FAQ](https://dev.predict.fun/)
[Market GET](https://dev.predict.fun/get-market-by-id-25552989e0).

| Required field | Candidate mapping | Status |
|---|---|---|
| market_id | market `id`; category link via `categorySlug` | DOCUMENTED, live unverified |
| market_start/end | category `startsAt/endsAt`; timezone required, aligned 300000 ms duration | DOCUMENTED, live unverified |
| condition / token identity | market `conditionId`, outcomes `onChainId/indexSet/name` | DOCUMENTED; freeze actual tuple, never infer from list order |
| YES/UP NO/DOWN | explicit names + index sets + token IDs + rule text | AMBIGUOUS until current market verified; reversed mapping currently rejected |
| raw lifecycle state | market `status` | DOCUMENTED |
| trading eligibility | separate market `tradingStatus` | DOCUMENTED; CLOSED trading is not proof of RESOLVED outcome |
| rule text/hash | exact description plus full relevant category definition; explicit precedence/conflict policy | DERIVABLE, actual text not audited |
| source_at | public status topic `tsMs` is an event timestamp | DOCUMENTED event time, not proven REST state transition/finality time |
| observed_at/available_at | local receipt/validation clocks | DERIVABLE; not a substitute for source_at |
| opening_reference_price | crypto details `startPrice` | DOCUMENTED value, actual availability unverified |
| opening_reference_at/available_at | source provenance plus first local receipt | MISSING authoritative opening observation timestamp |

Category schema contains the cycle endpoints and crypto feed fields. The crypto
variant contains provider, feed ID, symbol, startPrice and endPrice, without an
opening-observation timestamp in the reviewed example. Do not invent one from
`startsAt`. Preserve raw fields before normalization and reject conflicts between
legacy `variantData` and newer `variantDetails`.
[Category](https://dev.predict.fun/get-category-by-slug-25326911e0)
[Crypto schema](https://dev.predict.fun/cryptoupdownvariantdata-14037469d0).

The current synthetic state schema collapses raw lifecycle and trading states
into one status and requires a fresh source timestamp. Production needs a
versioned dual-status record and a reviewed freshness policy: an unchanged OPEN
state need not emit a new transition every two seconds. Refetch receipt cannot
be mislabeled as a new state transition. Existing synthetic defaults must not be
quietly widened. The opening identity/rule mapping must survive restarts.

## Settlement field mapping and independent authority

| Required field | Candidate mapping | Status |
|---|---|---|
| authoritative outcome | market `status=RESOLVED` with `resolution.indexSet` or uniquely `outcomes[].status=WON`, bound to frozen token mapping | DOCUMENTED candidate, live/finality unverified |
| settled_at | authoritative resolution event time / validated finalized block timestamp with event proof | MISSING verified endpoint/event mapping |
| first_observed_at | clock at first successful receipt of authoritative outcome, persist once | DERIVABLE |
| available_at | local validation completion; never earlier than first_observed_at | DERIVABLE |
| source identity | venue endpoint plus conditionId/oracleQuestionId/resolver and independently verified chain identity | PARTIAL; chain/contract/ABI/finality binding not frozen |
| raw status hash | hash retained allowlisted status payload and independent proof; no auth headers | DERIVABLE after transport implementation |
| split / cancellation | explicit authoritative payout vector and rule, not price-based inference | MISSING verified representation |

Market schema exposes resolver/condition identifiers and a resolution outcome;
the reviewed representation does not establish a dedicated `settled_at`.
That is a documentation gap, not a claim that no such field can ever exist.
[Market schema](https://dev.predict.fun/market-14037477d0)
[Outcome schema](https://dev.predict.fun/outcome-14037514d0).

Public WebSocket status updates carry `tsMs` and may include outcome prices.
Neither prices of 0/1, `endPrice`, a RESOLVED receipt timestamp, nor
`lastOrderSettled` proves the authoritative resolution time. The latter concerns
order matching settlement. The documentation schema named `Resolution` is a
timeseries interval, not a resolution event. Do not bind by that name alone.
[Public topics](https://dev.predict.fun/subscription-topics-1915507m0)
[Timeseries Resolution](https://dev.predict.fun/resolution-14037530d0).

Independent verification requires a reviewed authoritative venue resolution
record or chain event: bind market condition, resolver, outcome/token indexes,
payout vector, transaction/block identity and finality rule. Read-only RPC would
not require signing or wallet connection. Deployed-contract documentation is a
discovery aid, not a proof that any chosen address/event resolves this market.
No contract ABI, RPC endpoint or confirmation rule is approved by this audit.
[Deployed contracts](https://dev.predict.fun/-deployed-contracts-1860295m0).

## Rate limits, restart and the fixed follow-up window

Predict public WebSocket uses an API key, UTC epoch-ms events, heartbeat every
15 seconds with echo, reconnect/backoff and re-subscription. Cached snapshots
are best-effort, not a missed-event replay guarantee. Preserve first receipts,
record outages and reconcile current authoritative status after restart; never
reconstruct missed prediction/quote records.
[Connection and timing](https://dev.predict.fun/general-information-1915499m0).

No reviewed official source promises all outcomes within 24 hours. Therefore
**24-hour outcome completeness is NOT_VERIFIED**, even if a future one-off
resolved example works. Define quote_end and followup_end=quote_end+24h before
arming; stop calls at the deadline, retain unresolved markets as missing, never
extend the window. Early market resolutions may be captured during collection.

A naive follow-up loop over 288 pending markets every 5 seconds would require
3456 requests/minute, exceeding the documented default 240. A production
per-key scheduler must share its budget across discovery/state/book/settlement,
handle 429 and restart without a burst. Example engineering budget for review:
60 settlement requests/minute revisits 288 pending markets in 4.8 minutes;
other request types need their own allocation. This is not a frozen config or
proof of acceptable settlement latency. RPC/Chainlink limits are separate and
unverified. Terminal-market dedup must retain first-observed timestamps.

## Blockers and required changes

1. PREDICTION_TARGET_UNVERIFIED: identify an approved frozen predictor and
   calibration target. V2 proxy identity is known but venue compatibility is
   not. Define tie semantics and a causal feature/warm-up bridge without
   retraining, threshold changes or reused OOS evidence.
2. REFERENCE_TARGET_MISMATCH: separate auxiliary Binance feature source from
   authoritative venue target/opening reference in a versioned contract; never
   disable the current equality check just to accept mixed feeds.
3. STATE_TIME_AND_IDENTITY_UNVERIFIED: audit current authenticated payloads,
   explicit assets/rules, opening timestamp, dual raw status and receipt ages.
4. SETTLEMENT_TIME_AND_FINALITY_UNVERIFIED: verify authoritative outcomes,
   settled_at, split/cancel representation and independent identity/finality.
5. REAL_TRANSPORT_NOT_IMPLEMENTED: add bounded GET/public-topic source bridge,
   authentication/timeout/redaction tests, rate-budget scheduler, restart and
   deadline behavior. Actual host/key access and sustained freshness untested.
6. M10_REAL_BINDING_UNSUPPORTED: current adapter and frozen M8 Baseline are
   synthetic-specific. Add an explicitly reviewed real target profile/adapter
   in a later change; never relabel REALTIME evidence SYNTHETIC or modify M8's
   frozen baseline to force acceptance.

**Code modifications are required before real collection, but this audit makes
no runtime source changes.** Existing `LIVE_COLLECTION_NOT_IMPLEMENTED` guards
in `binding_collection/schema.py` and synthetic-only M10 loader remain intact.
No start/end dates, placeholder model IDs or fake rule hashes are inserted into
a runnable manifest. Re-audit these blockers before generating a real draft.

## Delivery verification

- Full local regression re-run: **965 passed, 2 skipped in 54.44 seconds**.
- All **95 protected baseline file hashes match**. No runtime source, model,
  config, deployment, old runbook or frozen baseline was changed.
- `main`, `v3-dev`, `codex/m10-scaffolding` and `v2.0.0-frozen` references
  unchanged from the implementation delivery.
- Staged-file and Git-history credential scans: **0 findings** in both.

No remote CI, push, deployment, wallet, funds, orders or study arm/start.
