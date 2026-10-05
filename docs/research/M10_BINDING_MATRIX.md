# M10 binding matrix — prospective-001

Audited 2026-10-06; this is structure/semantics only, not a performance report.
Root `f8f6752c1afd349f39fef5cced0d374fc60444a9fa8b5547c9372fe26b9c9c95`.
Original M9 verification: valid=true, sealed=true, 25 segments. 3250 observations.
Manifest hash `747ee0f9ffa981033a5661560e36f8ba53a132c078f773432e5c631060fdf21a`.
The gate pins the full dataset root and collector/baseline/dataset identities.

PRESENT = archived non-null evidence, not necessarily semantically valid.
DERIVABLE = deterministic provenance-preserving transformation, not yet an
approved real M8 binding. MISSING = no required evidence. AMBIGUOUS = some
evidence exists but meaning/compatibility is insufficient. No default value
is used to change these classifications. All per-observation presence counts
refer to 3250 OBSERVATION events, not diagnostics or independent predictions.

## Dataset and record envelope

| M8 field | Status | Evidence / constraint |
|---|---|---|
| manifest.dataset_id | PRESENT | prospective-001-validation |
| manifest.role | PRESENT | VALIDATION |
| manifest.time_start | PRESENT | collection_start=1791115500000 |
| manifest.time_end | AMBIGUOUS | collection_end=1791201900000 is exclusive; M8 coverage uses inclusive end |
| manifest.source | PRESENT | declared Predict.fun source |
| manifest.created_at | PRESENT | immutable M9 manifest |
| manifest.payload_hash | DERIVABLE | hash derived canonical records separately; retain sealed root, not substitute it |
| manifest.evidence_mode | AMBIGUOUS | PROSPECTIVE retained; M8 DatasetManifest only accepts SYNTHETIC |
| manifest.quality_status | DERIVABLE | new adapter state NOT_EVALUATED, never infer VALID |
| manifest.cadence_ms | AMBIGUOUS | poll_ms is receipt polling, not prediction/decision cadence |
| record.id | DERIVABLE | root + segment + journal seq or immutable source/event identity |
| record.at | MISSING | actual prediction/decision time absent; processed_at is not inference completion |
| record.sequence | DERIVABLE | global segment order + local seq; local seq restarts per segment |
| record.source | PRESENT | 3250/3250 |
| record.received_at | PRESENT | 3250/3250 local response receipt |
| record.available_at | AMBIGUOUS | processed_at 3250/3250 is persistence attempt; not historical M1 validation time |
| record.schema_version | DERIVABLE | version of NEW binding; not an invented observed field |
| record.raw | DERIVABLE | rename retained safe YES envelope after explicit binding/validation |
| record.prediction | MISSING | 0/3250, required for M8 inputs |
| record.health | MISSING | no per-decision HealthEvidence; heartbeat events only |
| record.books | DERIVABLE | later real quotes can be linked by market and availability; gaps stay missing |
| record.outcome | MISSING | 0/3250; unresolved cannot become payout 0 |
| record.venue_prices | MISSING | optional comparison unavailable; no two causal BTC reference series |
| record.reconstructed | DERIVABLE | adapter provenance flag, not a claim of reconstruction accuracy |
| venue_prices[].price | MISSING | optional reference diagnostic |
| venue_prices[].available_at | MISSING | optional reference diagnostic |

## Raw market dialect and real contract identity

| Field | Status | Evidence / constraint |
|---|---|---|
| raw.market_id | PRESENT | observation.market_id 3250/3250 |
| raw.source_at | PRESENT | 3250/3250 orderbook updateTimestampMs; not BTC oracle time |
| raw.expiry | PRESENT | payload.market_end 3250/3250 |
| market_start | PRESENT | 3250/3250 |
| raw.market_type | DERIVABLE | frozen rule_profile variant CRYPTO_UP_DOWN |
| raw.feed | AMBIGUOUS | CHAINLINK declaration present; does not make venue book a Chainlink tick |
| raw.rule_hash | PRESENT | 3250/3250 profile digest matches pinned profile |
| raw.outcome_mapping | DERIVABLE | frozen yes_is_up=true → YES_UP; not reconstructed from prices |
| raw.yes_bids | PRESENT | payload.bids 3250/3250; presence is not valid depth |
| raw.yes_asks | PRESENT | payload.asks 3250/3250; presence is not valid depth |
| raw.reference_underlying_price | MISSING | 0/3250 |
| raw.reference_price_at | MISSING | 0/3250 |
| raw.market_status | MISSING | 0/3250; successful polling does not prove OPEN |
| raw.market_status_at | MISSING | 0/3250 |
| raw.market_status_available_at | MISSING | 0/3250 |
| contract.condition_id | MISSING | not an M8 constructor field; real resolution identity needs binding |
| contract.yes_token_id | MISSING | 0/3250; contract identity not just display label |
| contract.no_token_id | MISSING | 0/3250 |
| contract.description_hash | PRESENT | frozen profile; raw resolution rule text not retained |
| contract.resolution_rule | AMBIGUOUS | hash alone does not define tie, cancellation, rounding or finality |
| contract.reference_feed_id | AMBIGUOUS | CHAINLINK label lacks exact feed/round/observation proof |
| contract.start_reference_price | MISSING | discovery code can parse startPrice, but M9 does not archive it |
| quote_type | PRESENT | YES_BOOK 3250/3250; market quote is not model probability |
| price_unit | AMBIGUOUS | binary book dialect suggests collateral/share; exact real token/unit metadata not frozen |
| quantity_unit | AMBIGUOUS | depth quantity needs explicit shares/lot/unit binding |
| fees | AMBIGUOUS | profile fee_bps is not a complete fee-basis/rounding/minimum/version contract |
| TTE at quote availability | DERIVABLE | market_end - processed_at, labeled quote TTE only |
| TTE at prediction/decision | MISSING | decision event/time absent |
| YES mid / spread | DERIVABLE | validated best bid/ask; mid is descriptive, never a fill |
| YES visible depth | DERIVABLE | validated depth only, no execution guarantee |
| direct NO bid/ask | MISSING | 0/3250 independent NO book |
| complementary NO view | AMBIGUOUS | mathematical 1-YES view possible only after explicit complementary contract; not independent liquidity |

254/3250 observations fail the audit's basic nonempty, two-column, finite,
strict-interior price, positive bounded quantity, noncrossed-book check.
This audit does not claim the remaining rows all pass the full M1 validator.
No source/receipt/processing window mismatch or rule-profile hash mismatch was
found by the implemented checks. These are operational data-quality counts,
not model, direction, profitability or strategy results.

## Archived Prediction (all fields read by Prediction.from_dict)

| Field | Status | Constraint |
|---|---|---|
| prediction.experiment_id | MISSING | study_id is not an archived prediction experiment binding |
| prediction.prediction_key | MISSING | actual archived inference identity |
| prediction.prediction_id | MISSING | derivable only from a real recorded key/experiment |
| prediction.market_id | MISSING | quote market exists, association to actual prediction does not |
| prediction.p_yes | MISSING | YES price/mid must not be used as a model prediction |
| prediction.model_version | MISSING | M8 synthetic manifest template is not a real model |
| prediction.model_hash | MISSING | no actual inference artifact binding |
| prediction.feature_version | MISSING | no inference feature binding |
| prediction.feature_hash | MISSING | no inference feature binding |
| prediction.input_cutoff | MISSING | cannot reconstruct from receipt timestamp |
| prediction.available_at | MISSING | cannot substitute processed_at |
| prediction.calibration_version | MISSING | never assume none means calibrated |
| prediction.support_status | MISSING | never use constructor default SUPPORTED as evidence |
| target_definition.outcome_mapping | MISSING | venue mapping exists; model target association absent |
| target_definition.rule_hash | MISSING | actual model target association absent |
| target_definition.expiry | MISSING | actual model target association absent |
| target_definition.probability_semantics | MISSING | MARKET_YES vs BTC-up probability must be explicit |
| target_definition.target_source | MISSING | no bound real target source |
| target_definition.target_feed | MISSING | no bound real target feed |
| target_definition.reference_price | MISSING | optional at constructor, necessary if target depends on opening reference |
| target_definition.reference_price_at | MISSING | causal reference pair |

## Health and settlement

2885 HEARTBEAT events contain source_health, baseline_valid, storage and
clock_offset fields; last_received_at is non-null in 2874. A heartbeat can
support a causal as-of join, not imply healthy status at arbitrary times.
Source clock offset presence does not mean a measured offset (M9 uses UNKNOWN).

| Field | Status | Constraint |
|---|---|---|
| health.available_at | AMBIGUOUS | heartbeat event.at exists; no decision-specific evidence object |
| health.source_at | AMBIGUOUS | heartbeat last_received_at is receipt, not source_at |
| health.heartbeat_at | DERIVABLE | most recent actual heartbeat at/before decision; no future join |
| health.provider_healthy | AMBIGUOUS | explicit mapping from as-of source_health needed; never default true |
| health.source_matches | AMBIGUOUS | profile check is narrower than full model/target-source match |
| health.validation_failures | MISSING | no contemporaneous M1 failure burst counter |
| health.reference | DERIVABLE | immutable heartbeat event/root reference |
| outcome.experiment_id | MISSING | explicit archived experiment binding |
| outcome.market_id | MISSING | no outcome event even though quote market IDs exist |
| outcome.resolution_at | MISSING | expiry is not resolution publication time |
| outcome.available_at | MISSING | must preserve original receipt/publication availability |
| outcome.yes_payout | MISSING | never infer from final price, path or expiry |
| outcome.source | MISSING | authoritative resolution source |
| outcome.rule_hash | MISSING | matching rule binding |
| outcome.settlement_version | MISSING | versioned real payout/finality interpretation |
| outcome.semantics | MISSING | frozen implementation only accepts SYNTHETIC_RESEARCH |
| outcome.outcome_id | MISSING | generate only from authentic outcome identity binding |

Outcome and books are optional in the M8 record parser, but their absence means
pending/unavailable downstream results, never successful completed execution.
The immediate mandatory-input blocker is the absent Prediction. Missing
market status/health further prevents a clean quality-passed replay cohort.

## Future book / MarketPathPoint / validated MarketSnapshot

| Field | Status | Constraint |
|---|---|---|
| books[].available_at | DERIVABLE | explicit quote availability semantics, same as point envelope |
| books[].point.snapshot_json | DERIVABLE | only successful normalize+validate output; not raw JSON |
| books[].point.decision_json | MISSING | optional; no historical decision may be fabricated |
| books[].point.observation_at | DERIVABLE | explicit research as-of, not future backfill |
| snapshot.snapshot_id | DERIVABLE | raw_event_id + config_hash + validator_version |
| snapshot.raw_event_id | DERIVABLE | canonical root/source event identity |
| snapshot.experiment_id | DERIVABLE | new explicit research experiment, not invented historical inference |
| snapshot.market_id | PRESENT | observation envelope |
| snapshot.source | PRESENT | observation envelope |
| snapshot.source_at | PRESENT | source book update time |
| snapshot.received_at | PRESENT | local receipt |
| snapshot.available_at | AMBIGUOUS | processed_at vs actual normalize/validate availability must be distinguished |
| snapshot.sequence | DERIVABLE | stable global segment/journal ordering |
| snapshot.expiry | PRESENT | market_end |
| snapshot.yes_bids | DERIVABLE | normalize validated actual retained levels |
| snapshot.yes_asks | DERIVABLE | normalize validated actual retained levels |
| snapshot.no_bids | AMBIGUOUS | requires approved complement semantics |
| snapshot.no_asks | AMBIGUOUS | requires approved complement semantics |
| snapshot.feed | AMBIGUOUS | target feed declaration vs book transport |
| snapshot.rule_hash | PRESENT | profile hash; semantic proof is incomplete |
| snapshot.outcome_mapping | DERIVABLE | frozen profile, never price direction |
| snapshot.reference_underlying_price | MISSING | absent |
| snapshot.reference_price_at | MISSING | absent |
| snapshot.clock_skew_tolerance_ms | DERIVABLE | explicit new validator policy, not observed clock accuracy |
| snapshot.validator_version | DERIVABLE | new audit/normalization version |
| snapshot.config_hash | DERIVABLE | explicit reviewed configuration hash |
| snapshot.price_unit | AMBIGUOUS | real contract unit binding required |
| snapshot.quantity_unit | AMBIGUOUS | real contract unit binding required |
| snapshot.mid_definition | DERIVABLE | descriptive best bid/ask mean |
| snapshot.no_derived | DERIVABLE | true only for explicitly derived complement view |
| snapshot.liquidity_independent | DERIVABLE | false for shared YES lots, never duplicate liquidity |
| snapshot.market_status | MISSING | absent |
| snapshot.market_status_at | MISSING | absent |
| snapshot.market_status_available_at | MISSING | absent |
| depth.price | PRESENT | raw levels present; invalid levels must remain rejected |
| depth.quantity | PRESENT | raw levels present; unit/validity gate remains |
| depth.liquidity_id | DERIVABLE | stable per-book level identity; not an exchange queue ID |
| depth.origin_side | DERIVABLE | YES_BID / YES_ASK provenance |
| depth.derived | DERIVABLE | actual YES=false, approved NO complement=true |

## Frozen baseline / invocation inputs (not collected quote fields)

| Field | Status | Constraint |
|---|---|---|
| baseline.source_git | PRESENT | frozen M8 Baseline internally pins e4b67ed; M9 approved M8 commit is separately 4dd8c798 |
| baseline.model_hash | AMBIGUOUS | synthetic template, not a real prediction binding |
| baseline.model_version | AMBIGUOUS | synthetic template |
| baseline.feature_hash | AMBIGUOUS | synthetic template |
| baseline.feature_version | AMBIGUOUS | synthetic template |
| baseline.calibration_version | AMBIGUOUS | synthetic template |
| baseline.edge | PRESENT | frozen configured research assumptions, not verified live costs |
| baseline.execution | PRESENT | synthetic execution configuration |
| baseline.risk | PRESENT | frozen risk configuration |
| baseline.policy | PRESENT | frozen exit policy |
| baseline.analytics | PRESENT | includes synthetic outcome source/version |
| baseline.max_spread | PRESENT | unchanged research parameter |
| baseline.variant | PRESENT | BASELINE; no tuning performed |
| invocation.cutoff | DERIVABLE | explicit post-seal research cutoff |
| invocation.code_git | DERIVABLE | new adapter implementation commit |
| invocation.cohort | DERIVABLE | explicit quality cohort; no selective deletion |

M8 `Dataset` also caps records at 2000. A one-to-one 3250-quote mapping would
exceed it. Actual decision cadence is missing, so the audit does not silently
subsample, partition portfolios or raise this bound. A future reviewed batching
contract must preserve chronological portfolio state and all excluded IDs.

Conclusion: **NOT_READY / replay_allowed=false**. Data completeness alone
cannot bypass frozen M8 synthetic target/settlement restrictions.
