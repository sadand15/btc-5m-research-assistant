# M9.2 Offline Target Semantics Lab

Date: 2026-10-08. Base: `bf76a5b88de4342d78ebf80621dcc0f700dfcb27`.
Module: `src/btc5_v3/target_semantics/`. Branch: `codex/m9-1-binding-collection`.

**Offline research module implemented. Real compatibility remains
TARGET_MISMATCH and readiness remains NOT_READY.** Nothing in this module
enables a collector, builds a real manifest, bridges V2 probabilities, or starts
a prospective study. No production module imports this lab.

## Data and target contract

Only fixed, explicitly synthetic fixtures are supplied by the demo. The pure
library receives caller-provided in-memory points; it does not authenticate,
download, read datasets, train a model or simulate orders. The caller must not
mislabel real data as synthetic. No old sealed evidence or model artifacts are
inputs. Reports explicitly carry `origin=SYNTHETIC_TEST`.

Each immutable Point has market identity, source/receipt/availability timestamps
and optional trade, bid, ask, reference values. Price arithmetic uses Decimal;
non-finite/non-positive prices, crossed books and invalid time ordering are
rejected. Mid is computed only with both bid and ask. Missing reference or
quotes are never filled from trade prices or another feed.

Each Contract explicitly identifies market, feed, rule and a 300000 ms interval.
The default endpoint experiment samples exact source timestamps C and E-1 ms;
the predeclared alternate samples C and E. There is no nearest-quote search,
forward fill, interpolation, epsilon tie band or boundary rounding. Duplicate
endpoint events are ambiguous and rejected. These sampling rules are lab
definitions, **not a claim to reproduce Chainlink's native sampling algorithm**.

## Fixed counterexample

For the same synthetic [0,300000) market:

| Series | Initial value | Terminal value at 299999 ms | Post-hoc label |
|---|---:|---:|---|
| Traded price | 100 | 101 | UP |
| Bid / ask midpoint | (99+101)/2 = 100 | (97+101)/2 = 99 | DOWN |
| Independent reference | 100 | 100 | TIE |

At exactly 300000 ms, trade is 99. Including that next-boundary point instead
therefore changes the descriptive trade label to DOWN. The already bound UP
authority fixture is not overwritten: the alternate analysis reports
REFERENCE_OUTCOME_DISAGREEMENT. This demonstrates sensitivity, not a preferred
boundary or a discovered real-market trading effect.

UP means terminal > initial; DOWN means terminal < initial; TIE means exact
equality in Decimal. The independent reference is deliberately constructed;
no assertion is made that an observed real oracle followed this path.

## Probability and calibration contract

The three named probabilities must each be finite and in [0,1], with an exact
Decimal sum of one. Missing TIE, excess mass and negative values fail. The demo
uses fixed (UP,DOWN,TIE)=(0.6,0.3,0.1), never fitted to data.

The complement of UP includes TIE. With a hypothetical half-tie payout, expected
UP payout is p_up+p_tie/2 and expected DOWN payout is p_down+p_tie/2. Neither
identity grants a real venue mapping or specifies cancellation payout.

Scoring requires synthetically VALID rows with explicitly supplied outcome
bindings; post-hoc price labels alone are never accepted as authoritative
results. Multiclass Brier is the sum of three squared errors, averaged over
rows (range 0–2). Log loss uses the probability of the authoritative class;
zero true-class probability is explicitly INFINITE, represented by null plus
a status/count rather than clipping or JSON Infinity.

Classwise reliability tables include all five fixed bins for each of three
classes, including empty bins. Intervals are left-closed/right-open, except
the final bin includes 1. ECE is the mean of the three classwise weighted
absolute calibration errors. No bin/threshold optimization or recalibration
is performed.

The ten predeclared outcome fixtures contain six UP, three DOWN, one TIE.
Constant (0.6,0.3,0.1) has Brier **0.54** and classwise ECE **0** by construction.
A fixed overconfident (0.9,0.05,0.05) example is also scored against the same
fixtures. This is a metric correctness check, not statistical evidence of
calibration, out-of-sample skill or profitability; ten designed rows cannot
support such a conclusion.

## Causality and readiness gates

- Every point enforces source_at <= received_at <= available_at.
- Prediction generation must lie in [C,E); only same-market points already
  available at generation enter its input hash. Out-of-cycle points are excluded.
- Synthetic probabilities are fixed inputs, not computed from terminal prices.
  Prediction records copy them and record generated_at, contract and input hashes.
- Outcome must identify the same market and contract hash, use the explicit
  synthetic authority, and satisfy generated_at < E <= outcome.available_at <=
  analysis_at. Missing/early/future outcomes fail closed.
- Endpoint labels use only data available by analysis_at; they remain post-hoc
  analysis. Changing future points cannot change a past prediction record.
- Synthetic validity is distinct from real readiness. Every result remains
  `readiness=NOT_READY`; absent identities, binding, authority, endpoint or price
  produce explicit reasons. A reference disagreement cannot silently replace
  an authoritative result.

The synthetic authority marker is a fixture convention, not cryptographic
verification of venue authority. Real finality and settlement semantics remain
outside this module and unresolved by its tests.

## Predeclared sensitivity grid

The deterministic report includes default E-1 and alternate E endpoints,
one-millisecond window shift, zero versus 1000 ms endpoint delivery budget,
missing terminal point, analysis before delivery, missing authority, wrong
market binding and outcome available before prediction. Reference disagreement
is additionally explicit in the three-series comparison and future mutation
regression. All scenarios are retained; none is selected as an optimal setting.

The delivery budget measures availability minus source time; it is not a claim
of live source health, exchange latency, execution feasibility or a trained
predictor's feature-freshness policy.

## Reproducibility and running

Canonical JSON provides source/config/input/report SHA256 hashes. Source input
order is normalized; no random generator, wall clock, network or private path
enters the report. Log-loss floating-point values can have last-bit differences
across Python/libm platforms; bit-identical report claims are scoped to the same
runtime. Record the Git commit and Python version when archiving a run.

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
python -m btc5_v3.target_semantics.demo --project-root .
python -m pytest -q tests/test_target_semantics_lab.py
python -m pytest -q
```

The demo writes only `runtime/m92-target-semantics/<report_hash>.json`, which is
ignored by Git. Re-running accepts byte-identical existing output and rejects
conflicting files or output-directory aliases. No generic input/output path
is provided for accessing old study files. Source fixtures are regenerated
from `demo.py`, so no market dataset or large model file is needed in Git.

## Verification and limits

New synthetic tests: **30 passed**. They cover distinct feed labels, simplex and
tie mass, malformed inputs, causal receipt/order, future mutation, missing or
incorrect bindings, boundaries/delay/missingness, duplicate events, source
immutability, deterministic reruns, calibration arithmetic and infinite loss.
Full suite: **1072 passed, 2 skipped** in 84.62 seconds. The shared parent Python
environment is not installed against this worktree; the demo command explicitly
sets its local src path instead of modifying that environment. Protected baseline:
**95/95 hashes match**, and main/v3-dev/frozen V2/M10 refs remain unchanged.

Two consecutive demo runs produced identical report bytes and hash:
`dbec58956e7d31524ffb75cf7217d55f2ad4735d6cc4e00c69790ab8021f719d`.
Credential scans: staged index **0 findings** (251 files), pre-commit history
**0 findings** (360 blobs). Remote CI was not run or claimed.

The pre-existing real collector enable gate is unmodified. No VPS runtime state
is queried or altered. Completion of this lab does not resolve M9.1's real
oracle target, token mapping, finality, cancellation, native timestamp or
prospective binding blockers. No real study or automatic trading is enabled.
