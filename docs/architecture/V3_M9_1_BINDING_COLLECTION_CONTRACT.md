# M9.1 prospective binding collection contract

Version `binding-collection-v1`, manifest/event/segment schema 2. Storage seal
index retains M9's version-1 hash-chain envelope. Based on M10 Phase 2 commit
`440c16fd35f2e803a1104b7e098417b0f9a4ec56`. New branch/worktree only.

## Isolation and scope

New archives are exclusively `runtime/v3/binding/<study>/`, through the existing
path alias/hardlink protections. `prospective-001` is explicitly refused as a
new binding study ID. No old M9 file is migrated, repaired, reopened for writes
or backfilled. Its known root remains
`f8f6752c1afd349f39fef5cced0d374fc60444a9fa8b5547c9372fe26b9c9c95`.
This development does not connect to the VPS or re-read that archive.

Only SYNTHETIC_TEST creation is currently enabled. Sources/predictors are
injected mock interfaces; no live transport, actual predictor, wallet,
funding, order, deployment service or real study command is included.
REALTIME creation fails closed. This is a tested binding pipeline, not a
claim that real-world M8 target/settlement support has been implemented.

## Frozen manifest and two windows

Manifest binds study/dataset IDs, approved M8 and collector proof, exact model,
feature schema/hash, calibration version, model-config hash, binding config
hash, rule document/hash, explicit source/feed/symbol/units and freshness limits.
Prediction policy is ONE_PER_MARKET_NO_REGENERATION. Configuration values in
the demo are synthetic interface fixtures, not parameters selected from the
old dataset. The actual predictor must match the frozen binding before and
after inference.

Create and arm before `collection_start`. Windows are immutable and exclusive:

- `[collection_start, quote_end)`: state, reference, book and prediction inputs;
  authoritative outcomes for already expired markets may also arrive.
- `[quote_end, settlement_followup_end)`: only authoritative settlement polling,
  plus operational diagnostics/heartbeat/gap bookkeeping. No input polling,
  quote capture, prediction, state refresh or historical reconstruction.
- At `settlement_followup_end == collection_end`: no further source requests or
  event admission. End/seal may happen later, but cannot extend either window.

The inherited storage field `collection_end` means the final acquisition
deadline here; the new `quote_end` explicitly ends quote/prediction collection.
M9's existing manifest is not reinterpreted or changed. Polls are checked both
before requesting and after receiving; responses crossing a deadline cannot
be admitted as on-time evidence. Unresolved markets remain pending in the seal.

## Immutable evidence events

Each accepted event carries stable ID, schema_version, local availability and
journal append-at time. Received/observed timestamps come from the collector's
explicit clock; source time is supplied independently. Availability can
precede the journal append attempt and is never substituted for source time.
Raw exceptions/headers/credentials are not recorded. Accepted inputs have
strict allowlists; rejected books retain sanitized raw content and its hash.

| Event | Required binding |
|---|---|
| MARKET_STATE | market ID/start/end, original OPEN/CLOSED/RESOLVED/SUSPENDED/UNKNOWN status, source health/time, observed_at/available_at; explicit YES→UP and NO→DOWN; complete safe rule text, rule and definition hashes; feed/target source/symbol, condition and outcome asset IDs, units, opening reference price/source time/availability, resolution and split policy |
| BTC_REFERENCE | positive finite price, source, source_at, received_at, available_at, source_health, symbol/feed and reference semantics; not a settlement label |
| BOOK | raw YES levels/source time/receipt/availability, state binding, successful M1 snapshot, validator version/config hash; strictly finite interior probabilities, positive bounded quantities, nonempty/noncrossed depth |
| PREDICTION | market ID/start/end, generated_at/available_at, p_up/p_down summing to one, model version/hash, feature schema/hash, calibration version, model/config hashes, full input snapshot hash, causal input_cutoff, target horizon/TTE, immutable state/reference/book links and actual heartbeat evidence |
| SETTLEMENT | explicit authoritative mock outcome UP/DOWN/SPLIT, source and settlement version, resolved status, settled_at, first_observed_at/available_at, original safe status/hash, market/rule/definition binding |
| REJECTED | operation, safe market identity, fixed reason, sanitized evidence/hash, original rejection time; never silently removed or treated as a legal BOOK/PREDICTION |

`yes_asset_id` / `no_asset_id` mean public outcome asset identifiers, not
credentials. The present mock resolution policy is explicit binary/split;
other real resolution semantics require an approved version, never guessing.
Opening reference and current BTC reference are different inputs. Neither may
be used to manufacture the authoritative outcome.

## Prediction causality and freshness

`Collector.predict(market)` accepts no timestamp or archived prediction from
the caller. The predictor receives a copied bundle of already recorded state,
reference and book; no outcome or future quote is passed. It may return only
p_up/p_down. The collector stamps generated_at **after inference** and checks
the clock, market state, frozen predictor binding and all freshness limits
again. New state during inference, stale/unknown input, an already observed
outcome, expired market or crossing quote_end rejects the prediction.

The journal append attempt must also precede expiry. The prediction hash binds
the exact input bundle. Actual heartbeat evidence is appended before inference;
provider/source validity derives from explicit healthy inputs and validation,
not silent HealthEvidence defaults. Validation failure counts are retained.
The operational append timestamp is not a hardware-certified fsync time;
storage/clock authenticity remains outside synthetic validation.

One prediction ID per market + experiment + config is checked in committed
journals **before** calling the predictor. Restart therefore returns an
existing prediction, never recomputes it with newer data. A crash after atomic
commit but before acknowledgement is deduplicated. A crash before commitment
leaves missing evidence; it does not justify a historical prediction.

## Structural rejection and settlement

Reuse unchanged M1 validation; do not tune rules against the 254 rejected old
books. An invalid latest input prevents fallback to an older valid book. A new
valid observation can restore eligibility, with prior rejection retained.
Ordering uses append order even for identical millisecond timestamps.

Settlement must refer to an observed market, match rule/source/version and
resolve at/after market end, after prediction availability/append. The first
observation timestamp is preserved on retry. Contradictory outcomes do not
replace the first outcome and block readiness pending review. Transient source
failures are diagnostics and may recover within the original deadline.
Follow-up tracks every observed market, including markets without predictions.

## Persistence and restart

`BindingStudy`/`BindingWriter` reuse M9 SQLite append-only triggers, FULL
synchronous transactions, row hashes, single-writer OS lock, hourly chained
segments, atomic publication, orphan reconciliation, partial-file quarantine
and immutable seal verification. No M9 source file is modified. Unknown
restart/tail intervals remain GAP events; no observations are reconstructed.
Schema-specific state counts show pending prediction/settlement and rejections.
After seal, even opening a new writer is refused before touching its lock file.
Hashes detect inconsistent changes, not an adversary rewriting all evidence.

## M10 adapter and meaning of READY

`load_binding_synthetic(study, now=..., expected_root=...)` requires the full
follow-up to end, a verified seal and explicit expected root. It rechecks the
input-reference graph, event ordering, market/rule/model/config identities,
snapshot hashes, probabilities, TTE, health and authoritative outcome binding.
All declared market cycles must be represented, with exactly one prediction
and outcome each and subsequent valid execution-book evidence. Missing cycles,
bindings, unsettled markets, conflicts, unsupported semantics, or the unchanged
M8 2000-record budget fail closed. No subset is silently selected.

Complete SYNTHETIC_TEST archives yield a derived M8 SYNTHETIC validation Dataset
with root/event/input provenance. This labeling is justified by actual mock
origin; real archives cannot use this path. No source record is rewritten.
The adapter checks M8 quality, not performance. A separate synthetic test runs
the unchanged M8 validator/replay twice and requires PASS. REPLAY_READY means
synthetic causal evaluability, not model quality, profitability or real support.

## Before any real second round

Implement and independently verify real read-only source adapters, exact
market/reference/outcome semantics and authoritative finality evidence. Approve
and freeze an actual model/features/calibration and artifact/config hashes;
the mock fixed-probability model is not deployable research evidence. Add the
separately approved real M10 target/settlement adapter. Bind new code identity,
test host clock/storage/recovery and explicitly authorize a new study/window.
Never unlock REALTIME by changing only a label or copying synthetic bindings.
