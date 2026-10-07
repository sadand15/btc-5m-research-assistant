# Manual read-only venue probe

Standalone script: `scripts/predict_fun_readonly_probe.py`.
Run manually on the Windows host whose PowerShell process has
`PREDICT_FUN_API_KEY`. No `.env` is read, and no interactive key prompt, argument,
fallback credential, wallet or SDK is used by Python. Missing/invalid keys fail
before output creation or network access. No real authenticated request was
executed during development; tests use injected mock transports only.

From the isolated worktree, using the existing project virtual environment:

```powershell
& 'C:\Users\31534\Documents\ChatGPT\crypto\.venv\Scripts\python.exe' '.\scripts\predict_fun_readonly_probe.py'
```

The API key must already be in this PowerShell process environment. Do not put
it in the command or pass it as an argument. This command does not depend on
environment inheritance by Codex/Work.

The script permits only GET on the fixed `https://api.predict.fun` host:

- `/v1/markets` with fixed OPEN/RESOLVED, CRYPTO_UP_DOWN and first=50 queries;
- `/v1/markets/{numeric_id}` for metadata/status/result in one response;
- `/v1/categories/{validated_slug}` for category boundaries/rules.

It never calls orderbook, wallet, balance, order, cancel, transfer, funding,
signing or account endpoints. No redirects, ambient proxies, netrc credentials
or persistent cookies. TLS verification remains enabled. Maximum 12 requests,
at least one second between requests, finite time/body limits, no retry on
401/403/429 or redirects. The program confines its own credential use to these
reads; it does not change or certify the provider-side scope of an API key.

Discovery is intentionally bounded: first page per status, at most one OPEN
candidate and two RESOLVED candidates whose title/question mentions BTC/Bitcoin.
Category timestamps determine whether each candidate is an aligned five-minute
market. No extra pagination or fallback if candidates are unsuitable. Empty
results and missing tied/cancelled examples are not proof that none exist.
Actual source/oracle and outcome mapping still require human contract review.

Output: a new UUID directory in `runtime/venue-contract-probes/`. No selectable
output path, no overwriting existing files; runtime/output junctions and symlinks
are rejected. No study imports or changes to manifests/models/sealed evidence.
Existing `.gitignore` excludes all generated probe output.

Each fixture contains an allowlisted, sanitized public payload, raw-response
SHA256, sanitized-payload SHA256, endpoint and local capture timestamps. Unknown
fields and auth/cookie headers are discarded. Only numeric rate-limit headers
are retained. Sensitive free text is redacted; original response bodies are
never written. Therefore these are **sanitized fixtures, not lossless raw
evidence**; a raw hash does not turn removed content into verifiable evidence.
Unexpected fields must be reviewed before intentionally expanding the allowlist.

`report.json` contains fixture names, observed states, cycle checks and bounded
request count. Local `first_observed_resolved_at` refers only to this run, not
global first occurrence. `first_observed_final_at` and interpreted
`native_settled_at` remain null; source timestamp fields may remain in sanitized
payloads for review. No finality, prediction compatibility, readiness or lifecycle
transition is inferred from snapshots or prices.

Console output is short and contains only fixed status, counts and generated
relative output directory. Error messages/HTTP error bodies are never rendered.
Exit 0 means bounded capture finished, not contract acceptance; exit 2 means
fail-closed. Reports always remain NOT_READY. Do not publish fixtures without
review. No automatic commit, study arm/start or deployment is performed.

Tests: `python -m pytest -q tests/test_readonly_venue_probe.py` (mock only).

Development verification (2026-10-07): full suite **1003 passed, 2 skipped**;
final probe-only run **35 passed**. Staged-file/history credential scans have
zero findings. All 95 protected baseline hashes match and frozen references
are unchanged. No real credential was read and no authenticated call executed.
