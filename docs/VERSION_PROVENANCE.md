# Version provenance

V2 was developed directly in the same project as V1. Before publication the local repository had no commits, but retained complete earlier Git tree objects.

- V1 source was recovered from tree `3a3830555790df35cbebffe19215a1ba2d7ae674` (21 original files, including core source, configuration, tests and first-run report).
- V1 packaging adds exclusions, byte-preserving Git attributes and an empty environment template. Its original research source is preserved.
- The first root commit is `feat: freeze BTC 5M Assistant v1`, annotated tag `v1.0.0`.
- The child commit is `feat: release BTC 5M Assistant v2`, annotated tag `v2.0.0`; `main` points here.
- These are release reconstruction commits made at publication time, not invented historical development timestamps.

No nested V1/V2 directory copies are published. Recover either source version with its tag. Data/model binaries remain local. The SHA of a release is obtained with `git rev-parse v2.0.0^{commit}` (quote this argument in PowerShell).

The forward study began before Git release registration. Registration is retrospective attribution of the **same verified source/model/policy bytes**, not a claim that early rows originally stored a Git SHA. See the separate `forward_release_provenance` table and `runtime/forward/release.json` on the observation host.
