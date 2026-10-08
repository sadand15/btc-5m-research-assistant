# M10.2 Final Report — Offline End-to-End Research Integration

Date: 2026-10-08. Integration branch: `codex/m10-2-offline-integration`.
Independent worktree: `runtime/worktrees/m10-2-offline-integration` under the
original repository. Base M9.2: `8fc310a250f3c59f5f9bc81eda43cc01efec9d27`.
M10 scaffold `440c16fd35f2e803a1104b7e098417b0f9a4ec56` is already an ancestor
of this base; no duplicate cherry-pick or copied repository was needed.

**Offline integration complete: SYNTHETIC_READY for the accepted subset.
Real data remains REAL_DATA_NOT_READY / TARGET_MISMATCH.** No live bridge,
collector, manifest, study or account is enabled by this integration.

## Interface audit and minimum adaptation

| Existing module | Contract | Integration decision |
|---|---|---|
| M10 `adapter.py` | Verified M9 prospective evidence eligibility; missing bindings stay NOT_READY | Unchanged; never fed offline envelopes |
| M10 `binding_dataset.py` | M9.1 synthetic archive -> M8 binary Prediction and YES payout; UP/DOWN/SPLIT settlement | Unchanged; no TIE probability coercion or modified M8 expectations |
| M9.2 `target_semantics.lab` | Explicit trade/mid/reference points, UP/DOWN/TIE simplex, causal timestamps, bound authority; fixed calibration scores | Reused directly, unchanged |
| New M10 `target_semantics.py` | Explicit OFFLINE_SYNTHETIC envelope -> M9.2 validation -> groupwise scoring | Thin dedicated three-class entry point in existing Research Adapter package |

This is not real-world M8 replay readiness. An offline three-class experiment
cannot honestly be routed through a two-class M8 object without losing meaning.
The new entry point preserves the original APIs and isolates the differing type
contract; it does not rewrite models, ingestion, collection or calibration.

## Reproducible data flow

1. Reuse M9.2 `points`, `bound` and fixed probability vector to build 12 positive
   fixtures (10 traded-price, one midpoint, one independent reference) and eight
   deliberately invalid records. All identities are synthetic.
2. Serialize explicit market/contract, points, generation time, probability
   vector, prediction input hash, authority, availability, quality and analysis
   settings into a versioned VALIDATION/OFFLINE_SYNTHETIC envelope.
3. Verify SYNTHETIC_TEST origin, role/mode, SEALED status, pinned root hash,
   row budget and unique IDs. The root is recomputed before decoding domain rows.
4. Run unchanged M9.2 label/time semantics; check the predeclared prediction
   input hash and quality status. Missing/invalid fields reject the row, never
   acquire default bindings or inferred outcomes.
5. Score only accepted rows, grouped by feed/rule/endpoint hypothesis. Preserve
   all three probabilities, Brier, Log Loss and five fixed bins per class.
6. Write input.json, report.json and a standalone HTML report in a dedicated,
   ignored runtime directory. Replays are deterministic; conflicting existing
   files and output aliases are refused instead of overwritten.

The envelope seal is a canonical content hash for synthetic reproducibility,
not an authenticated venue signature, M9 hash-chain segment seal, or proof that
real observations were collected prospectively. Origin labels alone cannot
authenticate third-party data. No real-origin input is supported by this API.
Caller mutation does not alter the adapter's snapshot of its input.

## Demonstration results and report

- **12 accepted / 8 rejected**. All rejected records stay visible and contribute
  no probabilities/outcomes to calibration aggregates.
- Rejections demonstrate missing market identity, absent authority, invalid
  outcome time, invalid quality, wrong/future input binding, absent terminal
  price, crossed book and absent prediction time.
- The constructed ten-row trade group retains M9.2's Brier **0.54** and
  classwise ECE **0** by construction, not evidence of real predictive skill.
- Mid and reference groups have one sample each and are not pooled with trade.
  Their scores do not establish calibration. No confidence interval is claimed.
- “Confidence” is explicitly the maximum class probability, not an empirical
  accuracy or statistical confidence interval. Input age reports the maximum
  source age among inputs already available at generation, in milliseconds.
- HTML shows all probabilities, post-hoc labels, acceptance, quality, reasons,
  grouped scores, all calibration bins, input root and report hash. It escapes
  values and uses no external assets, scripts, network or account widgets.

SYNTHETIC_READY means there are scoreable synthetic rows; it does not hide the
rejected subset or certify every row. No accepted row changes REAL_DATA_NOT_READY.
The frozen binary complement remains P(non-UP), not strict DOWN; the new entry
point never manufactures p_down from 1-p_up.

## One-command execution

From any directory on this workstation:

```powershell
& 'C:\Users\31534\Documents\ChatGPT\crypto\.venv\Scripts\python.exe' 'C:\Users\31534\Documents\ChatGPT\crypto\runtime\worktrees\m10-2-offline-integration\scripts\run_m102_offline.py'
```

On another installed Python environment, run `python scripts/run_m102_offline.py`
inside the integration worktree. The launcher adds only that worktree's src
directory to its own import path; no package installation or server is required.
Open the printed report.html path in a browser.

Deterministic report hash:
`cc3676a69c734acfee586e2b3b4076fa37a842d9055348d3609536e49c3930b7`.
Output: `runtime/m102-offline-integration/<report_hash>/report.html`.
Synthetic input.json is sufficient for `adapt_offline` replay with its pinned
root; no model file, network source or old sealed evidence is needed.

## Verification and preserved state

New end-to-end suite: **23 passed**, including serialized replay, repeated output,
tampering, eligibility bypass, malformed/late/missing records, causal future
mutation, input-binding mismatch, duplicates, source immutability and HTML escaping.
Full suite: **1095 passed, 2 skipped**, 77.83 seconds. Credential scans:
**index 0 findings** (256 files), **pre-commit history 0 findings** (366 blobs).
Bit-identical floating-point reports are scoped to the
same Python/runtime, as in M9.2; no cross-platform libm identity is assumed.

Protected baseline: **95/95 hashes match**. main, v3-dev, frozen V2 tag,
M10 scaffolding and M9.1/M9.2 branch references are unchanged. M9.2 source and
both existing M10 adapters are byte-identical to the base commit. Old sealed
evidence was not read or changed. No deployment checkout or VPS was accessed.
Remote CI and production process status are not asserted by this local audit.

## Remaining real-world blockers

The [M9.1 public-rule audit](V3_M9_1_PHASE3B_OFFLINE_CONTRACT_REVIEW.md) remains
authoritative for target mismatch and missing real token/time/finality binding.
This demo supplies no new real-market evidence. Genuine oracle-target prediction,
tie/cancel payout, irreversible settlement, native/observed timestamps and
prospective causal bindings require separately approved work. No automatic
execution or second prospective study is started by this delivery.
