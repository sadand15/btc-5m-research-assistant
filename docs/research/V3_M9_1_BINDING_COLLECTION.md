# M9.1 binding collection delivery

2026-10-06, Asia/Shanghai. Base:
`440c16fd35f2e803a1104b7e098417b0f9a4ec56`.
Branch `codex/m9-1-binding-collection`; isolated worktree
`runtime/worktrees/m9-1-binding-collection`.

## Delivered

New `btc5_v3.binding_collection` schema, append-only storage extension,
explicit-clock collector, source/predictor interfaces and runnable synthetic
demo. New M10 `research_adapter.binding_dataset` validates complete synthetic
archives and constructs provenance-bound M8 inputs. No real source, model,
wallet, order or second study was started. No VPS operation or old evidence
read occurred. Protected root remains the previously sealed
`f8f6752c1afd349f39fef5cced0d374fc60444a9fa8b5547c9372fe26b9c9c95`;
it was not re-verified remotely in this development task.

Schema additions: PredictionSnapshot, BTCReferenceSnapshot, MarketStateSnapshot,
validated BOOK and SettlementEvidence, plus explicit REJECTED diagnostics.
The full [contract](../architecture/V3_M9_1_BINDING_COLLECTION_CONTRACT.md)
specifies all fields, clock meanings, identity/health gates and follow-up bounds.
Old M9 storage primitives are reused without changing their source or old data.

Prediction generation and append-at precede outcome resolution; predictor
input contains no outcome. Invalid/stale/ambiguous data reject safely.
Crash/restart preserves IDs and first receipts, and does not repeat inference
after a committed prediction. Follow-up reads only authoritative settlement
for observed markets and stops at its predeclared deadline. Missing settlement
prevents READY; contradictory settlements remain recorded and require review.

## Reproduce with synthetic data only

From this worktree, using the project's Python 3.12 environment:

```powershell
$env:PYTHONPATH = "src"
python -m btc5_v3.binding_collection.demo --project-root .
python -m pytest -q tests/v3/test_v3_m91.py
python -m pytest -q
```

The demo creates and removes a temporary synthetic study under this worktree's
ignored runtime, covers restart/one prediction/future book/settlement/seal and
reports `origin=SYNTHETIC_TEST`, `readiness=REPLAY_READY`,
`real_study_started=false`. Full M8 synthetic validation is exercised in tests;
no performance numbers from real evidence are computed or shown.

## Real second-round blockers

- An actual approved frozen predictor, feature pipeline, calibration and input
  target binding. No new predictor is trained or selected here; the demo's
  fixed probability is a fixture, not a research model.
- Verified read-only market/state/reference and authoritative settlement
  transports, including availability, status timestamps, rule text, opening
  reference, outcome asset identity, units, split/finality semantics and API
  error handling. No account/financial operation is needed for this scope.
- A reviewed real M10 adapter: frozen M8 still has synthetic-only target and
  settlement semantics. This phase cannot make REALTIME REPLAY_READY by a flag.
- Freeze the new deployment's code/config/model and host operation checks,
  then obtain explicit new-study authorization. Existing seals stay immutable.

## Recommended first binding shakedown window

For an eventual authorized operational trial: **24 hours quote/prediction
collection plus a fixed 24-hour settlement-only follow-up**. This is a proposed
operational test duration, not an observed venue settlement SLA or evidence of
statistical sufficiency. Verify authoritative source finality/latency before
freezing the actual window. At its deadline unresolved markets stay missing
and NOT_READY; never extend the window after seeing results. Do not repeat the
old M9 collector unchanged, which cannot record the required new bindings.

## Verification

- Full local regression: **965 passed, 2 skipped**, including 61 M9.1 tests.
- Final synthetic demo: **REPLAY_READY**, sealed, one replay record, zero
  duplicate predictions, `real_study_started=false`.
- All **95 protected baseline file hashes match**. Frozen M9 source,
  deployment and runbook have no changes; main, v3-dev, M10 base and the
  v2.0.0-frozen tag references are unchanged.
- Staged-file and Git-history credential scans: **0 findings** in both.

Windows/Linux CI is not claimed without a remote run. No push, merge or
deployment is performed by this task. The old real dataset root was not
re-read or remotely verified; old evidence was never opened or modified.
