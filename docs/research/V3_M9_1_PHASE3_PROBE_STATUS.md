# M9.1 Phase 3: authenticated venue probe status

Date: 2026-10-06. Branch: `codex/m9-1-binding-collection`.
Base: `bee5f8ca7c488bf6f01a05b7dfd6063ba6c0f656`.

**NOT_READY / BLOCKED_NO_PROCESS_CREDENTIAL. Authenticated verification has
not been performed. This is a preflight receipt, not a completed venue audit.**

## Actual actions and fixtures

Both `PREDICTFUN_API_KEY` and `PREDICT_API_KEY` are absent from this process
environment. Only presence booleans were checked; no secret value was printed.
No credential files, VPS configuration or old sealed evidence were opened.
No requests were sent to Predict.fun; no testnet/public proxy substituted.
No study, prediction bridge, wallet, balance or trading operation was started.

Saved real response fixtures: **none**. Existing
`tests/fixtures/source_contract/capture_status.json` remains an explicit missing
capture record, not a response fixture. No market IDs, status history, outcomes,
native settlement times or rate-limit headers are invented.

## Venue Contract / Settlement Contract / lifecycle

The [source contracts](../architecture/V3_M9_1_SOURCE_CONTRACT_VERIFICATION.md)
remain the candidate verification requirements. Market/token identity, current
oracle and boundary rules, UP/DOWN/tie/cancellation payouts and authoritative
outcome/finality are **UNVERIFIED** against actual responses.

Observed lifecycle state set: empty. Verified transition edges: empty.
No OPEN -> CLOSED -> RESOLVED -> FINAL diagram is claimed as a venue fact.
Even eventual independent OPEN and RESOLVED snapshots would not establish their
transition ordering, irreversibility or absence of reopening/revision.

No `native_settled_at`, `first_observed_resolved_at`,
`first_observed_final_at` or `available_at` values were recorded. Future local
receipt times must remain distinguishable from native source occurrence times;
finality requires independent verification, not a label inferred from prices.

## Prediction compatibility

**NOT_EVALUATED_MISSING_VENUE_FIXTURES**. This is an evidence-availability state,
not a fourth compatibility verdict. None of EXACT_EQUIVALENCE,
DETERMINISTIC_TRANSFORM_POSSIBLE or TARGET_MISMATCH is issued without the
required venue evidence. Unknown compatibility blocks the bridge exactly as
an unresolved mismatch does, but is not represented as a proven mismatch.

The frozen model's verified target remains Binance Spot BTCUSDT, aligned UTC
five-minute candle close > open, with ties assigned label 0. The source contract
regressions test this target; they cannot validate a remote venue contract.

## Blockers

| Blocker | Status | Evidence / requirement |
|---|---|---|
| Frozen model target definition | RESOLVED | Prior source audit and synthetic semantic regression |
| Credential accessible through process environment | OPEN | Absent; never accept a key pasted into a command or repository |
| Credential and probe safely limited to read-only use | OPEN | Scope/access restriction not yet verified; no requests permitted if unsafe |
| Real market/category/status/result fixtures | OPEN | None captured |
| Actual rate limits/response headers | OPEN | No authenticated request |
| Venue identity, oracle, tie/cancel rules | OPEN | Requires actual rule-bearing responses |
| Authoritative final outcome and revision/finality policy | OPEN | No verified finality evidence |
| Native or honestly labelled local outcome time | OPEN | Contract proposed; no actual capture |
| Prediction compatibility | OPEN | No permitted verdict yet |
| Real M10 binding | OPEN | Synthetic-only adapter unchanged |

Frozen real study manifest: **cannot generate**. Collector stays disabled.

## Safe continuation requirements

Provide the credential through an approved process environment, not chat text,
repository files or command-line literals. For another host, first establish the
environment/host scope without reading or copying secrets into this workspace.
Verify that its use can be safely restricted before making any request.

Only fixed-host HTTPS GET metadata routes for bounded market discovery,
market detail and category detail are in scope. No arbitrary URL supplied by a
response, no redirects, no SDK/account/auth-signing helpers and no wallet/JWT
endpoints. Do not assume a generic API key is read-only without examining the
available restriction mechanism. Failure to establish safe read-only use stops
the probe. Actual contract-only capture is not a formal study.

Capture raw public response bytes and their SHA256 with local request/receipt
times and safe HTTP metadata after screening for unexpected sensitive data;
never persist authorization/cookie headers. Explicitly record missing tied,
cancelled or exceptional examples instead of synthesizing them. Do not trigger
429 intentionally or repeatedly poll markets to manufacture a lifecycle history.

## Verification

Full local regression: **968 passed, 2 skipped in 118.80 seconds**.
Staged-file and Git-history credential scans: **0 findings** in both.
95 protected hashes match; frozen main, v3-dev and V2 tag references unchanged.
Runtime code and configuration unchanged. No remote CI, push or deployment.
