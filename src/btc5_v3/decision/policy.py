"""Pure admissibility. Intentionally does not import or invoke the M2 engine."""
from decimal import Decimal, localcontext

from btc5_v3.encoding import digest, identifier, timestamp
from btc5_v3.market.models import MarketSnapshot
from btc5_v3.models.models import Prediction
from btc5_v3.edge.models import EdgeEvaluation
from btc5_v3.edge.numeric import CONTEXT, rounded
from btc5_v3.decision.config import DecisionConfig
from btc5_v3.decision.models import Decision, GATES, GateResult


def _finite(value):
    return isinstance(value, Decimal) and value.is_finite()


def decide(snapshot, prediction, edge, config: DecisionConfig, *, experiment_id, attempt_key, evaluation_at):
    identifier(experiment_id); identifier(attempt_key)
    if not timestamp(evaluation_at):
        raise ValueError('explicit decision time required')
    for value, cls in ((snapshot,MarketSnapshot), (prediction,Prediction), (edge,EdgeEvaluation), (config,DecisionConfig)):
        if not isinstance(value,cls) and not (value is None and cls is not DecisionConfig):
            raise TypeError('invalid decision input type')
    with localcontext(CONTEXT):
        return _decide(snapshot,prediction,edge,config,experiment_id,attempt_key,evaluation_at)


def _decide(s,p,e,c,experiment_id,attempt_key,t):
    found = set()
    mark = found.add
    if any(x is None for x in (s,p,e)): mark('DATA_INCOMPLETE')
    if any(x is not None and x.experiment_id != experiment_id for x in (s,p,e)): mark('EXPERIMENT_MISMATCH')
    if s and s.market_id != c.market_id: mark('MARKET_MISMATCH')
    if p and p.market_id != c.market_id: mark('MARKET_MISMATCH')
    if s and (s.outcome_mapping != c.outcome_mapping): mark('TARGET_MISMATCH')
    if s and s.rule_hash != c.rule_hash: mark('RULE_MISMATCH')
    if s and s.feed != c.feed: mark('FEED_MISMATCH')
    target = p.target_definition if p else None
    if target:
        if target.probability_semantics != 'MARKET_YES' or target.outcome_mapping != c.outcome_mapping:
            mark('TARGET_MISMATCH')
        if s and target.expiry != s.expiry: mark('TARGET_MISMATCH')
        if target.rule_hash != c.rule_hash: mark('RULE_MISMATCH')
        if target.target_feed is not None and target.target_feed != c.feed: mark('FEED_MISMATCH')
    if e:
        if p and e.prediction_id != p.prediction_id: mark('PREDICTION_MISMATCH')
        if s and e.snapshot_id != s.snapshot_id: mark('SNAPSHOT_MISMATCH')
        identity = dict(experiment_id=e.experiment_id,prediction_id=e.prediction_id,
                        snapshot_id=e.snapshot_id,evaluated_at=e.evaluated_at,config_hash=e.config_hash)
        if (e.edge_id != digest(identity) or e.config_hash != c.expected_edge_config_hash
                or e.edge_version != c.expected_edge_version): mark('EDGE_LINEAGE_MISMATCH')
        if p and e.p_yes != p.p_yes: mark('EDGE_LINEAGE_MISMATCH')
        if s and (e.yes_mid != s.yes_mid or e.no_mid != s.no_mid): mark('EDGE_LINEAGE_MISMATCH')
        if s and (e.receipt_age_ms != e.evaluated_at-s.received_at or e.source_age_ms != e.evaluated_at-s.source_at):
            mark('EDGE_LINEAGE_MISMATCH')
        if e.candidate_action in ('BUY_YES','BUY_NO'):
            if (s and e.evaluated_at < s.available_at) or (p and e.evaluated_at < p.available_at):
                mark('EDGE_LINEAGE_MISMATCH')

    if s and s.available_at > t: mark('SNAPSHOT_NOT_AVAILABLE')
    if p and (p.available_at > t or p.input_cutoff > t): mark('PREDICTION_NOT_AVAILABLE')
    if e and e.evaluated_at > t: mark('EDGE_NOT_AVAILABLE')
    if s and s.reference_price_at is not None and s.reference_price_at > t: mark('REFERENCE_NOT_AVAILABLE')
    if target and target.reference_price_at is not None and target.reference_price_at > t: mark('REFERENCE_NOT_AVAILABLE')
    if s and s.market_status_available_at is not None and s.market_status_available_at > t: mark('STATUS_NOT_AVAILABLE')
    if s and s.market_status not in ('OPEN','CLOSED','SUSPENDED'):
        mark('MARKET_STATUS_UNKNOWN')
    elif s and s.market_status != 'OPEN': mark('MARKET_NOT_OPEN')
    if s and (s.market_status_at is None or s.market_status_available_at is None):
        mark('DATA_INCOMPLETE')
    elif s:
        if s.market_status_at > t: mark('STATUS_NOT_AVAILABLE')
        if t - s.market_status_at > c.max_market_status_age_ms: mark('MARKET_STATUS_STALE')
    receipt_age = t-s.received_at if s else None
    source_age = t-s.source_at if s else None
    tte = s.expiry-t if s else None
    if tte is not None and tte <= 0: mark('MARKET_EXPIRED')
    if receipt_age is not None:
        if receipt_age < 0: mark('NEGATIVE_RECEIPT_AGE')
        if receipt_age > c.max_receipt_age_ms: mark('STALE_RECEIPT')
        if source_age < 0: mark('NEGATIVE_SOURCE_AGE')
        if source_age > c.max_source_age_ms: mark('STALE_SOURCE')

    semantics = bool(s and p and c.target_source_confirmed and p.model_hash == c.expected_model_hash
                     and s.experiment_id == p.experiment_id == experiment_id
                     and s.market_id == p.market_id == c.market_id and target.expiry == s.expiry
                     and target.target_source == c.prediction_target_source and target.target_feed == c.feed
                     and s.source == c.source and s.feed == c.feed and s.rule_hash == c.rule_hash
                     and target.rule_hash == c.rule_hash and target.outcome_mapping == c.outcome_mapping
                     and s.outcome_mapping == c.outcome_mapping and target.probability_semantics == 'MARKET_YES')
    if s and s.source != c.source: mark('PRICE_SOURCE_MISMATCH')
    if not semantics: mark('TARGET_SOURCE_MISMATCH')
    basis = observed_basis = None
    if c.require_reference_price or c.require_basis:
        if s is None or s.reference_underlying_price is None: mark('REFERENCE_PRICE_MISSING')
        elif s.reference_price_at is None: mark('REFERENCE_PRICE_MISSING')
        elif t-s.reference_price_at > c.max_reference_age_ms: mark('REFERENCE_STALE')
    if c.require_basis:
        if target is None or target.reference_price is None: mark('REFERENCE_PRICE_MISSING')
        elif t-target.reference_price_at > c.max_reference_age_ms: mark('REFERENCE_STALE')
        if (semantics and s.reference_underlying_price is not None and target.reference_price is not None
                and 'REFERENCE_NOT_AVAILABLE' not in found and 'REFERENCE_STALE' not in found):
            observed_basis = target.reference_price-s.reference_underlying_price
            basis = rounded(observed_basis/s.reference_underlying_price*10000)
            if abs(observed_basis)*10000 > c.max_basis_bps*s.reference_underlying_price: mark('BASIS_TOO_WIDE')

    action = e.candidate_action if e else 'NO_TRADE'
    if action not in ('BUY_YES','BUY_NO','NO_TRADE'):
        mark('EDGE_LINEAGE_MISMATCH'); action='NO_TRADE'
    side = 'YES' if action=='BUY_YES' else 'NO' if action=='BUY_NO' else None
    selected = (e.yes if side=='YES' else e.no) if e and side else None
    if e and action=='NO_TRADE': mark('UPSTREAM_NO_EDGE')
    if side and (selected is None or not selected.eligible): mark('EDGE_INELIGIBLE')
    if side and e.preferred_side != side: mark('EDGE_LINEAGE_MISMATCH')
    if selected and selected.side != side: mark('EDGE_LINEAGE_MISMATCH')
    spread = normalized = fraction = None
    requested = e.requested_shares if e else None
    executable = selected.executable_shares if selected else None
    edge_value = selected.net_edge_per_share if selected else None
    ev_total = selected.net_ev_total if selected else None
    liquidity = selected.liquidity_used if selected else ()
    if selected and s:
        spread = s.yes_spread if side=='YES' else s.no_spread
        mid = s.yes_mid if side=='YES' else s.no_mid
        normalized = rounded(spread/mid)
        if (spread > c.max_absolute_spread
                or (c.max_normalized_spread is not None and spread > c.max_normalized_spread*mid)):
            mark('SPREAD_TOO_WIDE')
        if selected.requested_shares != requested: mark('EDGE_LINEAGE_MISMATCH')
        if not _finite(edge_value) or not _finite(ev_total): mark('DATA_INCOMPLETE')
        lots = s.yes_asks if side=='YES' else s.no_asks
        by_id = {lot.liquidity_id:lot for lot in lots}
        seen = set()
        total = Decimal(0)
        for use in liquidity:
            lot = by_id.get(use.liquidity_id)
            if (lot is None or use.liquidity_id in seen or not _finite(use.shares)
                    or use.shares <= 0 or use.shares > lot.quantity or use.price != lot.price
                    or use.liquidity_origin != lot.origin_side or use.derived != lot.derived):
                mark('EDGE_LINEAGE_MISMATCH')
            seen.add(use.liquidity_id)
            if _finite(use.shares): total += use.shares
        if total != executable: mark('EDGE_LINEAGE_MISMATCH')
    if selected:
        if not _finite(requested) or requested <= 0: mark('INVALID_REQUESTED_SHARES')
        if not _finite(executable) or executable < 0: mark('INVALID_EXECUTABLE_SHARES')
        elif _finite(requested) and requested > 0:
            if executable > requested: mark('INVALID_EXECUTABLE_SHARES')
            fraction = rounded(executable/requested)
            if (executable <= 0 or executable < c.minimum_executable_fraction*requested
                    or (c.minimum_executable_shares is not None and executable < c.minimum_executable_shares)):
                mark('INSUFFICIENT_DEPTH')
            if selected.unfilled_shares != requested-executable: mark('EDGE_LINEAGE_MISMATCH')
    if tte is not None and 0 < tte < c.min_time_to_expiry_ms: mark('MARKET_NEAR_SETTLEMENT')

    ordered = tuple(reason for _,reasons in GATES for reason in reasons if reason in found)
    if found-set(ordered): raise AssertionError('unregistered gate reason')
    audit = tuple(GateResult(name,tuple(r for r in reasons if r in found),
                            'BLOCKED' if name=='FINAL' and ordered else
                            'REJECT' if any(r in found for r in reasons) else
                            'NOT_APPLICABLE' if name in ('SPREAD','LIQUIDITY') and selected is None else 'PASS')
                  for name,reasons in GATES)
    final = action if not ordered else 'NO_TRADE'
    # Input hashes are audit evidence; no probability/edge re-estimation occurs here.
    inputs = digest([x.to_json() if x is not None else None for x in (s,p,e)])
    return Decision(digest([experiment_id,attempt_key]),attempt_key,experiment_id,
                    p.prediction_id if p else None,s.snapshot_id if s else None,e.edge_id if e else None,
                    t,action,final,ordered[0] if ordered else None,ordered,source_age,receipt_age,tte,
                    spread,normalized,requested,executable,fraction,edge_value,ev_total,side,liquidity,
                    False,basis,observed_basis,s.market_status if s else None,audit,e.reasons if e else (),
                    c.hash,c.decision_version,inputs)
