# M10 offline adapter and research assistant scaffold

This contract is prepared independently of the running `prospective-001`.
Collector `265d6dd7f5f53baa98a8dbb3e45331e1245891bf` and approved M8
`4dd8c798cac479ddd411cb69a7901fda6e0f8136` remain unchanged. No deployment,
partial evidence read, real study creation, model fitting or threshold tuning.

## Evidence eligibility is not research readiness

The eventual real adapter requires all of SEALED, successfully VERIFIED,
VALIDATION, PROSPECTIVE, ended original window and approved baseline. A caller's
`verified=True` flag is insufficient: the unchanged M9 verifier checks actual
manifest, journals, segments and root. Hash integrity does not prove feed
authenticity. BLIND and unknown roles are refused before journal access.

Implemented API: `inspect_synthetic_sealed(study, now=...)` in
`btc5_v3.research_adapter`. Only explicitly supplied `Study` and
`SYNTHETIC_TEST` origin are supported in this phase. There is no CLI that scans
archives. REALTIME is refused **before payload verification/access**, even if
sealed. This deliberate restriction defers final real-data adaptation.

Result separates `candidate_status=ACCEPTED/REJECTED` from
`readiness=NOT_READY` and `replay_allowed=False`. An accepted sealed fixture is
an integrity-qualified candidate, never a ready M8 replay. Results retain
dataset/root/manifest identity, role, evidence mode, origin and baseline.
They contain fixed reasons and missing binding names, not raw evidence.
Invalid, early, unsealed, wrong-role, wrong-baseline or tampered candidates
are rejected. Empty archives cannot become research-ready.

M9 has no settlement field in its payload allowlist and its safe quote
envelope is not M8's normalized raw contract. Therefore the scaffold always
reports `MISSING_BINDING` for SETTLEMENT_BINDING, MARKET_NORMALIZATION_BINDING
and M8_RECORD_BINDING, plus PREDICTION_BINDING when absent/invalid. Merely
finding an archived Prediction does not certify its target/model/calibration
compatibility. No conversion to M8's SYNTHETIC evidence mode is performed.

## Deferred real binding contract

After explicit authorization for final adaptation, a separate derived artifact
must bind the sealed dataset root, adapter schema/version/code/config hashes,
original source event IDs and independent archived evidence IDs/hashes.
Never write derived values back to the source archive. Required validations:

- Raw quote → M1 valid snapshot, retaining source/receipt/availability times,
  market identity, mapping, rule/feed, depth provenance and missing intervals.
- Actual archived Prediction: experiment/market/expiry/target, model/feature/
  calibration identities, input cutoff and availability. No retrospective
  prediction pretending to have been available during collection.
- Actual resolution evidence: matching experiment/market/rule/source/version,
  payout semantics including split, resolution at/after expiry and recorded
  availability. No inferred settlement from final quote or absent-as-zero.
- Explicit M8 record IDs/sequences/decision times and contemporaneous health;
  missing health is not HEALTHY. M9's exclusive window end must not silently
  become an additional M8 inclusive observation.
- Reject duplicate/conflicting/cross-market bindings and incompatible rules.
  Preserve all omissions. Missing bindings mean NOT_READY/MISSING_BINDING;
  unsupported semantics mean NOT_READY, never implicit defaults.

M8 currently hardcodes synthetic target and settlement semantics. Its frozen
quality/replay functions must not be fed real records under a synthetic label.
A complete-looking sidecar alone cannot bypass this limitation. A future
explicit implementation/review is necessary; none is included here.

## Research assistant boundary

`btc5_v3.research_assistant` is a pure, deterministic offline interface with
explicit probabilities, evidence timing and policy inputs. It neither trains
nor invokes a model and does not read a filesystem, wall clock or network.
`outcome_mapping=YES_UP` is required; unsupported/unknown mappings return WAIT.
Outputs include p_up/p_down, calibration/confidence evidence, freshness,
spread, liquidity, TTE, gate reasons and UP/DOWN/WAIT. Confidence is supplied
evidence, never computed as max(p_up,p_down). Values/policies in synthetic
tests are interface fixtures, not calibrated production parameters.

WAIT is a first-class result for missing/invalid/unknown inputs, insufficient
edge, excessive spread, stale data, insufficient depth, unsuitable TTE,
failed calibration/quality gates, causal violations and ambiguous direction.
Research signal is not an order, permission or fill claim. No wallet, account,
funds, signing, order endpoints, scheduler or execution reducer is exposed.
Only mock/synthetic/offline inputs are in scope. Future evidence cannot be
used to improve an earlier signal.

## Delivery and next gate

Synthetic tests cover seal/tamper/role/time/origin rejection before payload,
missing binding, immutable sources, deterministic output, WAIT conditions and
no network calls. All old tests remain required. No current OOS statistics are
computed. After the existing fixed window naturally ends, its operational
`end -> seal -> verify -> adapter` must finish before discussing final real
data suitability. This code does not perform those operations or inspect
their current status. It does not automatically promote a sealed dataset.

## Phase 2 authorized sealed binding audit

The Phase 1 restrictions above remain true for `inspect_synthetic_sealed`.
A separate `audit_sealed` entry now permits explicitly authorized REALTIME
sealed evidence, pinned by dataset root, collector, dataset and approved
baseline. It verifies unchanged M9 integrity and source bytes and returns only
structural field counts, fixed diagnostics and NOT_READY. It does not convert
records, invoke replay or infer prediction/outcome. See the
[Phase 2 report](../research/M10_FINAL_REPORT.md) and
[binding matrix](../research/M10_BINDING_MATRIX.md). No collection changes.
