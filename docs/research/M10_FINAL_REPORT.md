# M10 Phase 2 final report — real sealed binding audit

2026-10-06, Asia/Shanghai. This completes the binding audit, not a real-world
replay adapter or an execution deployment.

## Conclusion

**NOT_READY; replay_allowed=false.** M9 successfully sealed evidence, but a
verified quote archive is not an archived predictive research dataset.
The exact root provided by the user was matched against the original image:
`f8f6752c1afd349f39fef5cced0d374fc60444a9fa8b5547c9372fe26b9c9c95`.

Study prospective-001; dataset prospective-001-validation; collector
`265d6dd7f5f53baa98a8dbb3e45331e1245891bf`; approved M8
`4dd8c798cac479ddd411cb69a7901fda6e0f8136`. Phase 2 starts at M10 scaffold
`0c72115c813072125205f5a8b590d138fd70c82a` on codex/m10-scaffolding.

## Verified evidence and method

Original M9 verifier reports valid=true, sealed=true, 25 segments. Structural
audit reads all 3250 observations plus heartbeat metadata. It checks role,
PROSPECTIVE mode, ended window, expected dataset/collector/baseline and root
before inspection. It verifies the journals/segments before and after and
compares all evidence-file byte hashes. No difference was found. Two runs
returned the same structural counts and pinned identities.

Each audit ran in a disposable non-networked read-only container using the
original M9 image and a **read-only** evidence volume. New code was streamed
over stdin: no source installation, image rebuild, collector restart, manifest
write, outcome backfill or new study. The audit's explicit post-window logical
as-of argument was 1791244800000; no performance cutoff/replay was evaluated.
No API credentials were mounted or used. Output has allowlisted field-presence
counts, integrity and fixed issue codes; no raw quotes, probability values,
outcomes, PnL, win rate, directional result or edge analysis.

See [machine-readable audit](M10_BINDING_AUDIT.json) and the full
[field-by-field binding matrix](M10_BINDING_MATRIX.md).

## Blockers

1. **Archived Prediction absent in 3250/3250 records.** Model/feature/calibration
   identity, target, input cutoff and availability are absent. Quotes cannot
   substitute for predictions; the manifest's synthetic baseline template
   proves no real inference occurred.
2. **Outcome evidence absent.** No authoritative payout, resolution time or
   availability binding. This prevents completed settlement/calibration research;
   it does not imply that every unresolved M8 input must be rejected at parsing.
3. **Market status and causal decision health incomplete.** OPEN and status
   timestamps are absent. Heartbeat states exist but require an explicit as-of
   association; validation-failure evidence is not archived. Defaults cannot
   make them healthy or VALID.
4. **Frozen M8 semantics are synthetic-only.** DatasetManifest, target/feed/rule
   checks and ResolvedOutcome explicitly reject real semantics. Even otherwise
   complete real inputs cannot enter unchanged M8 by changing a label.
5. **Target/contract evidence incomplete.** YES_UP is derivable from the pinned
   profile; condition/token IDs, exact real resolution semantics and opening
   BTC reference evidence are not archived. CHAINLINK is a target feed label,
   not a BTC reference price series. NO book is not independently observed.

Additionally 254 quote rows require structural rejection/review; no rows were
repaired or silently removed. A 3250-row one-to-one quote mapping would exceed
M8 Dataset's 2000-record bound. A future explicit decision/batching contract
must preserve chronology and portfolio state, not selectively subsample.

## Implemented scope and next step

Added root-pinned `research_adapter.audit_sealed` with synthetic regressions.
It is an audit/readiness boundary, not a replay converter. The original
synthetic adapter and research assistant behavior remain unchanged. No real
records were passed to M8 quality/performance/replay, no probability or outcome
was generated and no frozen baseline was modified.

**M9.1 and a new prospective round are required for contemporaneous prediction
evidence unless a separate authentic pre-existing archive is independently
available and approved.** Repeating current M9 unchanged is insufficient.
See [minimal schema delta](../architecture/V3_M9_1_MINIMAL_SCHEMA_DELTA.md).
Approve the actual predictor/real target contract before collection; add
market definition/status, validation health, Prediction and Outcome events,
with prespecified resolution follow-up semantics. Do not touch the first seal.
This report proposes the next round; it does not create or start it.

## Verification and limitations

New synthetic audit tests cover root/role/window/identity rejection, unsealed
and tampered evidence, immutable reads, no network/disclosure, malformed depth
and mutation during inspection. Full suite: **904 passed, 2 skipped**; 24 new
synthetic audit cases passed. Protected lock: **95/95 hashes unchanged**;
original main, v3-dev and frozen tag references unchanged. Staged-file and
reachable-history credential scans both returned **zero findings**. Remote CI is not
claimed without a pushed branch/run. Hash consistency is not external
authenticity; basic structure is not full M1 validity or executable liquidity.
