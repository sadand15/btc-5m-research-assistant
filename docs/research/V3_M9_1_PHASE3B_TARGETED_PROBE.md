# M9.1 Phase 3b — Targeted BTC 5m Venue Probe

2026-10-08. Base commit: `279057ac6fada6065eeb9c4b8354db2486ebfb9c`.
Branch: `codex/m9-1-binding-collection`.

**NOT_READY / INSUFFICIENT_EVIDENCE. This delivery prepares the targeted manual
capture. No authenticated request was executed by the agent.** The operator
confirmed that the authenticated run will be performed in local PowerShell.
No environment credential was inspected. No real BTC 5m IDs or fixtures from
this new probe are yet available; synthetic coverage is not venue evidence.

## Why another capture is necessary

The [Phase 3 review](V3_M9_1_PHASE3_CONTRACT_REVIEW.md) found no complete BTC 5m
market/category pair. Its daily/15m samples must not be used as evidence of a
five-minute target. Existing review and raw sanitized files are preserved.

The new entry point is `scripts/predict_fun_btc5m_probe.py`. It uses category
boundaries before spending detail-capture quota, followed by fixed search
queries if the required open/resolved coverage is incomplete. The old standalone
probe retains its original routes and twelve-request budget; its transport is
reused through a class-specific route allowlist and request cap.

## Read-only transport contract

Official API references checked on 2026-10-08:

- [Get categories](https://dev.predict.fun/get-categories-25326910e0):
  GET `/v1/categories`, `first`, `after`, `status`, `marketVariant`; response
  `cursor`, categories with `startsAt`, `endsAt` and nested `markets`.
- [Search categories and markets](https://dev.predict.fun/search-categories-and-markets-27399810e0):
  GET `/v1/search`, `query`, `includeResolved`, `limit`; category/market arrays.
  Documentation describes a default 50 RPM search limit; runtime headers/errors
  remain authoritative and no rate-limit retry is performed.

Only these discovery endpoints and GET `/v1/categories/{safe-slug}` /
`/v1/markets/{numeric-id}` can be sent, to fixed `https://api.predict.fun`.
No arbitrary URL/query, POST, wallet, account, balance, orders, cancellation,
funding, transfer, orderbook or execution request is allowed. No wallet JWT,
signing or account login is used. This client restriction does not prove that
the credential has server-enforced read-only scope.

Fixed limits: at most 80 requests, 10 category pages of 50 per OPEN/RESOLVED
filter, six detail-candidate attempts per state, four search queries, one second
between requests, existing bounded time/body limits. Redirects, proxies/netrc
inheritance and cookie reuse remain disabled. HTTP/auth/rate-limit errors stop
the run without retries. Repeated/invalid pagination cursors fail closed.

Only environment `PREDICT_FUN_API_KEY` is read by the operator-run CLI. Missing
or malformed credentials stop before output creation or network. No `.env`
loading, command-line key, credential echo or request-header recording exists.

## Target qualification and rejection

- BTC/Bitcoin identity plus explicit 300,000 ms category interval. A 5m title
  is only a discovery hint if boundaries are absent; a fresh category/detail
  pair must subsequently prove the interval. 15m/daily durations are rejected
  even if a title contains `5m`. No 299-second boundary is silently rounded.
- A category must unambiguously identify one market, whose detail ID and
  category slug are checked. Description must be present. Explicit Up/Down
  names, distinct numeric public token IDs and distinct positive outcome indexes
  are required. YES/NO without proven directional meaning stays rejected.
- Alignment to UTC five-minute boundaries is reported separately. An off-grid
  five-minute market is useful contract evidence, never assumed model-compatible.
- `CURRENT_OPEN`: REGISTERED, trading OPEN, no resolution, and receipt within
  [start,end). `RECENT_WINDOW_OPEN_STATUS`: same observed state, but cycle ended
  within the preceding fixed 24 hours. The latter does not prove historical
  transition order or tradability during the past cycle.
- `RESOLVED`: after cycle end, explicit resolution name/index/token/status must
  match the single WON outcome and the other outcome must be LOST. No winner
  is inferred from reference prices. Half-payout/cancelled cases remain retained
  but cannot satisfy this normal resolved-sample coverage gate automatically.
- Disputed, future, old, malformed and ambiguous pairs do not satisfy coverage.
  Inspected pairs keep reasons and fixture references. Discovery pages retain
  all sanitized entries, including rejected durations; they are not discarded.

`TARGETED_CAPTURE_REQUIRES_CONTRACT_REVIEW` means only that a structural
open/recent-open sample and a resolved sample were captured. It does not prove
identical rule families, source equivalence, finality, or readiness. No-result
or bounded-search exhaustion returns `BTC5M_COVERAGE_INCOMPLETE`, never a claim
that BTC 5m markets do not exist. A schema change stops rather than guessing.

## Evidence, settlement and lifecycle

Each run creates a new ignored UUID directory under
`runtime/venue-contract-probes/`; files are exclusive-create. Sanitized payload,
payload hash, raw-response hash, validated query description and local
request/receipt/availability timestamps are retained. Raw response bodies are
not saved; their hashes alone cannot be reverified later. Unknown fields are
dropped, so field absence only describes the retained allowlist.

Common safe native timestamp spellings are retained verbatim when present,
including `settledAt`, `settled_at`, `resolvedAt`, `resolutionTimestamp` and
`settlementTimestamp`. They remain `UNVERIFIED`: no native settled time is
invented, units inferred, or local receipt substituted. First resolved
observation is local to this run and linked to its earliest retained discovery
or detail evidence. `first_observed_final_at` stays null without verified finality.

One already captured CURRENT_OPEN market receives one additional detail request
at the end, without a long wait. Both snapshots are retained. Changed states
support only the observed sequence, not unobserved intermediate transitions,
irreversibility, or a claim that RESOLVED cannot reopen. No finality state machine
is manufactured from different markets.

## Current contract review gates

| Gate | State at this delivery |
|---|---|
| Targeted transport and rejection behavior | RESOLVED in synthetic tests |
| Real BTC 5m market IDs | OPEN — operator capture pending |
| Real open/resolved fixture counts | 0 / 0 for this Phase 3b delivery |
| Venue Contract: feed, reference samples, boundaries, tie/cancel | OPEN |
| Settlement Contract: authoritative outcome, native time semantics, finality | OPEN |
| Lifecycle transitions / reopen/revise evidence | OPEN |
| Same-family open/resolved sample verification | OPEN |
| Prediction compatibility | INSUFFICIENT_EVIDENCE |
| Frozen real M9.1 manifest | Prohibited / NOT_READY |

After capture, review exact source/instrument, endpoint sample semantics, UTC
alignment and tie rules against frozen Binance Spot BTCUSDT [C,C+300000),
UP iff close>open. `1-p_up` remains P(close<=open), not strict DOWN by default.
PYTH or another oracle must not be treated as Binance-equivalent without a
proven deterministic transform. No code in this probe creates that bridge.

## Operator command

Run in the PowerShell process where you already set the environment variable:

```powershell
& 'C:\Users\31534\Documents\ChatGPT\crypto\.venv\Scripts\python.exe' 'C:\Users\31534\Documents\ChatGPT\crypto\runtime\worktrees\m9-1-binding-collection\scripts\predict_fun_btc5m_probe.py'
```

The command contains no key. Share only its short report and output directory.
Do not share the environment value. A missing-key report requires fixing local
process inheritance; it does not authorize loading a key from another source.

## Validation and freeze protection

- Targeted and existing probe tests: **74 passed**, entirely synthetic transport.
- Protected baseline: **95/95 hashes match**. Main, v3-dev, frozen V2 tag and
  M10 scaffolding references are unchanged.
- Full suite: **1042 passed, 2 skipped**, 85.04 seconds. Remote CI not queried.
- Credential scans: **index 0 findings** (244 files), **pre-commit history
  0 findings** (352 blobs). No real credential was loaded for these checks.
- No study, SSH, sealed-data read/write, model change or prediction occurred.
- Stop after capture/review; even a later READY verdict does not arm/start a study.
