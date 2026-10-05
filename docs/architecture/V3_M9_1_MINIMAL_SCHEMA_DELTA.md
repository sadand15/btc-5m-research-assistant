# Proposed M9.1 schema delta — not implemented or deployed

Purpose: collect the minimum truthful bindings for a later real-world M8 adapter.
This is a new version/new study proposal. Never upgrade or edit prospective-001.
Repeating M9 unchanged cannot fix the missing archived prediction/outcome inputs.
No second study is created or authorized by this document.

## Prerequisites that more quotes cannot fix

1. Approve an actual frozen predictor and its feature/calibration/target binding,
   or explicitly remain prediction-unavailable. The M8 synthetic-risk template
   is not such a predictor. Never convert venue mid into p_yes.
2. Define real resolution semantics and authoritative evidence; approve a
   separate real adapter contract instead of relabeling PROSPECTIVE as SYNTHETIC.
3. Specify decision cadence, availability conventions, shared YES/NO depth
   semantics and batching/state preservation before observing results.
   Do not choose thresholds from this dataset.

## Minimal event additions

All new events use immutable event_id, schema_version, source, source_at (null
when unknown), received_at, available_at, sequence, market_id, safe payload
hash and durable provenance reference. Redact credentials/headers/cookies;
allowlist exact evidence fields rather than collecting entire authenticated
responses. Raw invalid inputs and their rejection reasons remain retained.

| Event | Required additions |
|---|---|
| MARKET_DEFINITION | market_id, start/end, outcome indexes/labels and YES_UP/YES_DOWN mapping, market/condition/token identity when supplied by the source, rule text/artifact + hash + version, exact reference feed/source/instrument, reference opening price/time/availability, explicit tie/split/cancel/finality handling; contract price/quantity units |
| MARKET_STATUS | market_id, actual status, status source timestamp and receipt/availability, definition/rule reference; never assume OPEN from discovery |
| QUOTE | retain current YES levels and all three clocks, definition/status reference, quote type/units; document complement lots and non-independent depth or archive actual NO book with explicit independent-liquidity contract |
| VALIDATION_HEALTH | raw_event_id, validator/config versions, validation result/reasons, validated_at; causal heartbeat/source state, source time, last receipt, validation-failure count/window, evidence references; UNKNOWN is explicit |
| PREDICTION | actual experiment/prediction key/id, market, p_yes, model/feature/calibration hashes and versions, input_cutoff, actual available_at, support_status; full target mapping/rule/expiry/probability semantics/source/feed/reference binding; references to input snapshot/events |
| OUTCOME | authoritative event/market identity, actual resolution_at, received_at and available_at, payout including split, source, rule/version/finality semantics, safe original evidence reference/hash; pending/disputed/unknown remain explicit, never payout=0 by default |

No new observation may be retroactively added to prospective-001. If an
independent pre-existing authentic prediction archive exists, a later explicit
task could inspect it as a separately rooted binding source. This audit found
none in this dataset and did not search unrelated archives. Retrospective
inference cannot become a contemporaneous prospective Prediction.

## Availability and end of study

Prespecify the quote/prediction window separately from any resolution follow-up
window. The last market can resolve after its expiry or after quote collection
ends. A new schema must permit explicitly bounded outcome-only follow-up and
seal only after its prespecified end; never extend the quote window on results.
Unresolved at deadline stays pending/missing. Current M9 accepts observations
only inside its fixed window and lacks this event contract; merely expanding
its payload allowlist is insufficient.

Depth validation failures remain failures, not repaired/interpolated quotes.
Store measured clock evidence only if available; UNKNOWN must not become zero
offset. Preserve outages, duplicate identity decisions and source failure gaps.

## Optional versus blocking additions

A causal BTC reference series is needed for BTC shock/return features and for
reference-dependent targets; it is not universally required to validate a
standalone binary probability record. Preserve price units/feed/round IDs and
source/receipt/availability if collected. Two reference series are optional
for M8 cross-venue divergence. Fee-basis/rounding/minimum/version evidence is
required before claiming real fee/execution realism, not to count raw quotes.

The immediate mandatory replay blocker is missing archived Prediction plus
incompatible real target semantics. Missing market status/health blocks clean
quality eligibility. Missing outcome blocks resolved/calibrated/settled
research, but is not a required constructor field for an unresolved M8 row.
This distinction must survive in future readiness diagnostics.
