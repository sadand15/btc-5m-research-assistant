# M10 scaffold delivery

Date: 2026-10-05 (Asia/Shanghai). Branch `codex/m10-scaffolding`, independent
worktree `runtime/worktrees/m10-scaffolding`, based on frozen M9
`265d6dd7f5f53baa98a8dbb3e45331e1245891bf`. This is preliminary M10 framework
development, not completion of the real-world adapter milestone.

## Isolation and delivered behavior

No SSH/VPS operation was performed. No running collector, image, volume,
manifest, study window, source, heartbeat scheduler or real observation was
read/modified. No second real study was created. Local main and v3-dev stay on
their previous commits; only the new branch receives this work. No model,
calibration, production threshold or old domain implementation changed.

- `research_adapter`: reuses unchanged M9 verification for explicitly supplied
  ended, sealed SYNTHETIC_TEST/VALIDATION/PROSPECTIVE archives. Reports separate
  evidence-candidate acceptance and NOT_READY/MISSING_BINDING. Refuses real
  origin before journal access, and rejects unsealed/tampered/wrong-role inputs.
  No prediction/outcome generation or real-to-synthetic relabeling.
- `research_assistant`: immutable offline inputs/results, explicit clock and
  policy with deterministic hash, probability/calibration/confidence evidence,
  freshness, both sides' spread/depth, TTE and UP/DOWN/WAIT. Unknown evidence
  remains unknown; all gates must pass. No I/O, implicit model, order or
  execution path. Gross probability-minus-ask gap is explicitly not net edge
  or execution profitability. Thresholds have no production defaults.
- Synthetic tests, contract, README and architecture/roadmap navigation.

The assistant requires explicit `outcome_mapping=YES_UP`: supplied p_up
corresponds to YES and p_down to NO. Unknown or different mappings return
WAIT/TARGET_MAPPING; actual real target normalization remains deferred.
Each visible-depth field means the minimum
of the side's observed bid and ask depths; either side failing blocks signals.
Future timestamps cannot become usable at an earlier as-of. Confidence is
supplied evidence and is never manufactured from the larger probability.

## Verification

Final local full pytest: **880 passed, 2 skipped** (138 new synthetic cases).
Tests are synthetic/offline and use temporary
archives; no partial real dataset is a fixture. Original M9 protected lock:
95/95 file hashes unchanged. Existing M0–M9 source, deployment files, runbook,
baseline lock, model/config and frozen tags are unchanged. Credential scans
cover staged files and reachable Git history; both returned zero findings.
Existing Windows/Linux CI workflow discovers the new tests without
configuration changes. Remote CI is not claimed until this branch is pushed
and its run succeeds; this delivery only creates a local commit.

## Remaining gate and assumptions

The running study must naturally finish its original window, followed by the
existing operational end -> seal -> verify -> adapter sequence. Only after
that gate and an explicit next task may final real-data schema/bindings be
inspected and implemented. Missing archived prediction, resolution, target,
health or compatible M8 semantics must remain NOT_READY; a sealed archive
alone does not solve those omissions. No backfill or retrospective inference
may be represented as prospective contemporaneous evidence.

This phase does not establish real feed authenticity, completeness, model
calibration, prediction quality, executable liquidity or profitability. It
does not report current prospective performance or current VPS health.
