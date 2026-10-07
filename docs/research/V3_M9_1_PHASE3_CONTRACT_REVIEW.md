# M9.1 Phase 3 — Real Fixture Contract Review

Review date: 2026-10-07. Branch: `codex/m9-1-binding-collection`.
Review base: `280e9f85d069ef84b68788f182872f0eee192c82`.

**NOT_READY. Requested BTC 5m prediction compatibility: INSUFFICIENT_EVIDENCE.**
The three captured market/category pairs are two daily markets and one nominal
15-minute market; each is **TARGET_MISMATCH** against the frozen model. These
findings cannot establish the contract of an uncaptured BTC five-minute market.
No prediction bridge or frozen study manifest is permitted on this evidence.

## Scope and evidence integrity

Only the existing sanitized probe run
`runtime/venue-contract-probes/461d047389dc448fb480674fcfcdce15` was reviewed.
Eight fixtures and its report were read; no new API request, credential read,
SSH, study operation, inference, performance analysis or sealed-evidence access
was performed. This is contract evidence, not a prospective research dataset.

[Machine-readable review](V3_M9_1_PHASE3_FIXTURE_REVIEW.json) records every
fixture's metadata, all list entries' classification, exact public token IDs,
condition/oracle/resolver identifiers, rule hashes, and all nine source-file
SHA256 hashes. It is a derived review index, not a replacement raw response.
Original files remain in the ignored runtime directory and were not committed.

All eight responses report HTTP 200 and `CONTRACT_AUDIT_NOT_STUDY` scope.
All eight sanitized payload hashes were recomputed successfully. Source-file
hashes are checked again after review. The retained raw-response hashes cannot
be independently recomputed because raw response bodies were not retained.
These local hashes verify consistency, not a venue signature or finality proof.
The probe uses a field allowlist: absence below means absence from retained
fields, not proof that the API never supplies a field under another name.

## Real Fixture Review

| Fixture | Read-only resource | Review finding |
|---|---|---|
| 01 | `/v1/markets`, OPEN discovery | 50 records; 17 BTC text matches; no cycle endpoints. Market statuses: 49 REGISTERED, 1 PRICE_DISPUTED. The list includes daily and hourly rule families, not a verified current BTC 5m market. |
| 02 | `/v1/markets/2880279` | Explicit Up/Down token identities; BINANCE BTCUSDT; daily close-to-close rule; PRICE_DISPUTED, trading OPEN, resolution null. |
| 03 | Category `bitcoin-up-or-down-on-october-5-2026` | Category 555695; paired by exact slug; 24-hour start/end; category OPEN; resolutionProvider THREE_PO. |
| 04 | `/v1/markets`, RESOLVED discovery | 50 records; 49 BTC text matches; PYTH feed metadata and RESOLVED status. No cycle endpoints; list alone cannot certify duration or lifecycle. |
| 05 | `/v1/markets/510` | PYTH BTC_USD; Up resolution matches outcome index/token; Up WON, Down LOST; market RESOLVED, trading CLOSED. |
| 06 | Category `btc-usd-up-down-2025-12-15-17-00` | Category 607; 24-hour start/end; RESOLVED; resolutionProvider PREDICT_DOT_FUN. |
| 07 | `/v1/markets/2874` | PYTH BTC_USD; Up resolution matches outcome index/token; Up WON, Down LOST; market RESOLVED, trading CLOSED. |
| 08 | Category `btc-usd-up-down-2026-01-14-20-00-15-minutes` | Category 2485; nominal 15-minute title, exact endpoint delta 899,000 ms; RESOLVED; resolutionProvider PREDICT_DOT_FUN. |

The OPEN/RESOLVED discovery labels reflect probe request selection; they do not
replace the actual separate `status` and `tradingStatus` fields. All three
detail objects equal their corresponding list records. Market/category slugs,
descriptions and reference `variantData` match within each pair.

For every paired market, Up is `indexSet=1`, Down is `indexSet=2`, with distinct
`onChainId` tokens recorded verbatim in the JSON index. Names observed are
**Up/Down**, not literal YES/NO. Any internal YES=Up/NO=Down convention must be
bound to these identities, not inferred from array order or reused across markets.

## Venue Contract: observed market families

| Market | UTC start → end | Price/reference contract | Outcomes and tie |
|---|---|---|---|
| 2880279 | 2026-10-04 16:00:00 → 2026-10-05 16:00:00 | Binance Spot BTCUSDT; compare the 1-minute candle CLOSE at noon ET on consecutive days. Not a 5m candle open-to-close target. | Ending close greater: Up; lower: Down; equality: 50/50 payout. |
| 510 | 2025-12-15 17:00:00 → 2025-12-16 17:00:00 | PYTH BTC/USD at the rule's ending time versus stated starting price 86391.37750007. | Greater: Up; lower: Down; equality: 50/50 payout. |
| 2874 | 2026-01-14 20:00:00 → 2026-01-14 20:14:59 | PYTH BTC/USD at 15:14:59 ET versus stated starting price 97263.35. | Greater: Up; lower: Down; equality: 50/50 payout. |

Both PYTH rules permit an administrator-selected exchange fallback if PYTH is
unavailable (including Binance/Coinbase or another exchange). This does not
establish a deterministic transform to Binance Spot BTCUSDT. The same PYTH feed
ID is retained for both; source identity differs from `resolutionProvider` and
`resolverAddress`, which identify other roles and do not prove finality.

Reference amounts are present, but no underlying reference tick timestamps,
publication delay or exact endpoint sample-selection algorithm are established
by the retained `startPrice`/`endPrice` fields. Category creation/publication
times are not reference-price observation times. Market 2874's endpoint is
explicitly :14:59; it must not be rounded to a 900,000 ms exclusive interval.
UTC serialisation/alignment alone does not imply the frozen UTC 5m candle target.

Fixture 01 also contains 15 BTC hourly rules: for example market **2951477**,
`Bitcoin Up or Down - October 7, 12AM ET`, uses the finalized Binance BTCUSDT
**one-hour candle, Up iff close >= open**, Down otherwise. The other two BTC
entries have daily half-tie rules. No paired category was captured for that
hourly example, so its precise cycle endpoints are not verified here. Rule
families must remain distinct: neither BINANCE nor a BTC title is sufficient
evidence of target equivalence. No verified BTC 5m cancel/invalid rule or actual
tied/cancelled case is captured.

## Settlement Contract and timestamp semantics

For 510 and 2874, venue API `resolution` specifies Up, indexSet 1 and the exact
Up token; corresponding outcomes report WON/LOST. These are explicit
**venue-reported resolved outcomes**, not results derived from BTC prices.
For 2880279, `resolution` and outcome statuses are null, despite an `endPrice`:
it remains unresolved for this review. Price comparison is never an outcome source.

No native settlement timestamp or independently verified irrevocable finality
flag is available in the retained fixtures. `RESOLVED` alone does not establish
non-revisability; condition IDs/resolver addresses do not prove on-chain finality.
Cancellation, invalidation and dispute-to-final payout semantics remain open.

| Field | Auditable interpretation |
|---|---|
| Category `startsAt` / `endsAt` | Venue-declared cycle boundaries; not price-tick timestamps or settlement times. |
| Category `createdAt` / `publishedAt` | Metadata lifecycle timestamps; not proof of outcome publication. |
| Probe `request_at` (epoch ms) | Local request start, not venue event time. |
| Probe `received_at` (epoch ms) | Local response receipt; all fixtures satisfy request ≤ receipt ≤ availability. |
| Probe `available_at` (epoch ms) | Local probe availability marker, not native settlement time. |
| `first_observed_resolved_at` | Earliest retained local observation in this probe run with resolved evidence; cannot recover historical resolution time. |
| `first_observed_final_at` | Unknown/null: finality criterion has not been established. |
| `native_settled_at` | Unknown/null in retained evidence; never filled from receipt, cycle end or price. |

For the detail fixtures, locally observed resolved evidence was available at
**2026-10-07T04:44:50.852Z** (510) and **2026-10-07T04:44:53.415Z** (2874).
Both outcomes were already present in fixture 04: its receipt time
**2026-10-07T04:44:49.561Z** is their earliest retained resolved observation in
this run; availability was **2026-10-07T04:44:49.568Z**. These are derived local
markers, not native fields. Market 2880279 was observed disputed at
2026-10-07T04:44:46.793Z. None of these is a native settlement time.

## Lifecycle state machine: observed nodes, transitions unverified

| Observed market state | Trading state | Category state where paired | Evidence |
|---|---|---|---|
| REGISTERED | OPEN | Not paired | Fixture 01 list entries |
| PRICE_DISPUTED | OPEN | OPEN | 2880279, fixtures 02/03 |
| RESOLVED | CLOSED | RESOLVED | 510 and 2874, fixtures 05–08 |

The verified transition edge set is **empty**. Different markets at different
states do not establish OPEN → CLOSED → RESOLVED, a mandatory dispute phase,
or irreversible FINAL. There is no captured transition series, FINAL state,
cancelled/tied example or reopen/revision history. Market 2880279's trading OPEN
status after its cycle end specifically prevents treating OPEN as “currently
within the prediction window.” CLOSED trading alone must not authorize settlement.

## Prediction compatibility

Frozen target: see [Prediction Target Contract](../architecture/V3_M9_1_SOURCE_CONTRACT_VERIFICATION.md).
Model `v2-9e452c59ebf7` predicts Binance Spot BTCUSDT in the current UTC-aligned
300,000 ms interval [C,E): first-second open O versus last-second close F
(bar close time E−1 ms). UP is F>O; label 0 includes F<=O. Its complement is
P(non-UP), not necessarily strict P(DOWN) or a half-tie contract's expected payout.

| Dimension | Frozen model | Captured contracts | Finding |
|---|---|---|---|
| Feed | Binance Spot BTCUSDT | BINANCE daily/hourly; PYTH BTC_USD plus discretionary fallback | Not one common target |
| Horizon | UTC 5m current cycle | Two daily pairs, one nominal 15m pair; hourly list examples | Mismatch |
| Start/end values | Candle open / final close | Daily minute-close comparison or PYTH point reference; hourly candle | Mismatch |
| UP/tie | Strict >; tie in label 0 | Paired markets half payout on tie; hourly rules >= | Mismatch |
| Cancel/invalid | No cancellation label | Exact cancellation/finality behavior unproven | Open |
| Deterministic transform | Requires proof | No horizon/feed mapping proof or separate tie probability | Not established |

- **All three paired markets: TARGET_MISMATCH.** No bridge permitted.
- **Requested true BTC 5m contract: INSUFFICIENT_EVIDENCE.** No matching pair captured.
- Neither EXACT_EQUIVALENCE nor DETERMINISTIC_TRANSFORM_POSSIBLE is supported.

If the intended five-minute market ultimately has different feed/boundaries/tie
semantics, a newly defined predictor and appropriate training/calibration may
be necessary. This review neither authorizes nor performs that work. A half-tie
payout needs P(UP)+0.5·P(TIE); frozen P(UP) alone cannot supply it. Similarly,
changing strict > to >= cannot be done exactly without additional tie evidence.

## Blockers and next evidence

| Gate | Status | Evidence / remaining requirement |
|---|---|---|
| Manual authenticated metadata access | RESOLVED for captured requests | Eight successful read-only responses; no credential needed for this review. Does not certify credential's server-side permission scope. |
| Local sanitized evidence integrity | RESOLVED | Eight payload hashes and nine file hashes; source bytes unchanged. |
| Selected market/category and token identity | RESOLVED for three pairs | Exact list/detail equality, slug/rule/reference consistency, explicit tokens. |
| Explicit resolved outcome field | RESOLVED for 510/2874 only | Resolution index/name/token matches outcome statuses; not finality proof. |
| Genuine BTC 5m open and resolved coverage | OPEN | Need actual 300,000 ms contract pairs, current in-window OPEN example and completed examples. |
| BTC 5m reference and boundary semantics | OPEN | Need exact oracle/feed/instrument, start/end sample rules, timestamp inclusion and fallback rules. |
| BTC 5m tie/cancel/invalid payout | OPEN | Authoritative rules plus cases if available; no inference from normal outcomes. |
| Native settlement time or approved observed-time alternative | OPEN | Inspect safely retained native field names; if absent, explicitly accept local first-observed resolved/final times without relabelling. |
| Finality/revision/reopen | OPEN | Authoritative finality rule plus evidence linking terminal state and payout; repeated same-market observations alone cannot prove impossibility of revision. |
| Fixed 24h follow-up sufficiency | OPEN | No resolution-delay/finality timing proof; old resolved snapshots cannot establish a 24h guarantee. |
| Prediction target equivalence / deterministic transform | OPEN | Captured pairs mismatch; missing intended five-minute contract. |
| Live prediction/BTC reference causal binding | OPEN | Venue metadata does not establish prospective model generation/append timing or fresh reference inputs. |
| Frozen M9.1 real manifest | OPEN / prohibited | All required source and semantic gates must pass first. |

The bounded probe selected the first BTC-text candidates rather than requiring
a five-minute duration and active cycle before consuming selection quota. Two
50-record lists and three paired candidates therefore exhausted coverage without
the requested market family. No absence-of-BTC-5m-on-the-venue conclusion follows.

A future explicitly authorized capture should identify verified five-minute
category/market pairs before counting sample quota, retain exact mapping/rules
and safe timestamp/finality fields, and include an in-window open market plus
completed same-family examples. Capture tie/cancel/dispute examples if available;
otherwise those gates remain explicit unknowns. Additional pages or specific
market IDs may be needed. This review does not change or rerun the probe.
Captured rate-limit headers (limit 250, remaining/reset values) do not establish
reset units, a rate-limit SLA, or settlement availability within 24h.

## Delivery verification

- Full local test suite: **1003 passed, 2 skipped**, 65.91 seconds. No tests skipped
  for this review; this is the suite's existing skip count.
- Fixture/report credential scan: **0 findings** across all nine input JSON files.
- Repository credential scan: **index 0 findings** (241 files),
  **pre-commit history 0 findings** (349 blobs).
- Protected baseline: **95/95 hashes match**. `main`, `v3-dev`,
  `v2.0.0-frozen` and `codex/m10-scaffolding` refs are unchanged.
- All **9/9 input-file hashes remain unchanged** after review.
- Remote CI is not queried or asserted in this offline review.
- Changes are documentation and a derived evidence index only. Frozen model,
  collector source, runtime fixtures and old `prospective-001` sealed evidence
  are not modified; old evidence is not reopened for hashing in this review.
- **STOP: no study arm/start, bridge, training, wallet or order operation.**
