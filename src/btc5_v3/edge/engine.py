"""Pure decision-time arithmetic. No clock, feeds, orders or liquidity mutation."""
from decimal import Decimal, localcontext

from btc5_v3.encoding import digest, timestamp
from btc5_v3.market.models import MarketSnapshot
from btc5_v3.models.models import Prediction
from btc5_v3.edge.costs import CostBreakdown, EdgeConfig
from btc5_v3.edge.models import EdgeEvaluation, LiquidityUse, SideEvaluation
from btc5_v3.edge.numeric import CONTEXT, rounded


def _side(side, probability, mid, asks, config):
    remaining = config.target_shares
    used = []
    for level in asks:
        take = min(remaining, level.quantity)
        if take > 0:
            used.append(LiquidityUse(level.liquidity_id, level.origin_side, level.derived, take, level.price))
            remaining -= take
        if remaining == 0:
            break
    quantity = config.target_shares - remaining
    # A valid M1 snapshot has a nonempty ask side with strictly positive depth.
    notional = sum((lot.shares * lot.price for lot in used), Decimal(0))
    vwap = notional / quantity
    fee = config.fee
    cash_fee = (notional * fee.rate + quantity * fee.collateral_per_share
                if fee.denomination == 'COLLATERAL' else Decimal(0))
    share_fee = quantity * fee.rate if fee.denomination == 'SHARES' else Decimal(0)
    net_shares = quantity - share_fee
    spent = notional + cash_fee + quantity * (config.latency_cost_assumption + config.extra_cost_assumption)
    ev = net_shares * probability - spent
    net_edge = rounded(ev / quantity)
    reasons = []
    if quantity / config.target_shares < config.minimum_executable_fraction:
        reasons.append('INSUFFICIENT_DEPTH')
    if net_edge <= config.minimum_net_edge_per_share:
        reasons.append('EDGE_BELOW_THRESHOLD')
    costs = CostBreakdown(
        asks[0].price, mid, asks[0].price - mid, rounded(vwap), rounded(vwap - asks[0].price),
        rounded(cash_fee / quantity), fee.denomination, cash_fee, share_fee,
        config.latency_cost_assumption, config.extra_cost_assumption, rounded(spent / quantity),
        spent, quantity, net_shares, config.assumptions_version, fee.version)
    return SideEvaluation(side, probability, probability - mid, config.target_shares, quantity, remaining,
                          remaining > 0, rounded(vwap), rounded(probability - vwap), costs,
                          net_edge, ev, tuple(used), not reasons, tuple(reasons))


def choose_candidate(yes, no):
    """Mutually exclusive hypothetical choice; strict threshold was applied per side."""
    if yes.eligible and no.eligible:
        if yes.net_edge_per_share == no.net_edge_per_share:
            return None, 'NO_TRADE', ('EXACT_EDGE_TIE',)
        side = 'YES' if yes.net_edge_per_share > no.net_edge_per_share else 'NO'
    elif yes.eligible or no.eligible:
        side = 'YES' if yes.eligible else 'NO'
    else:
        return None, 'NO_TRADE', tuple(dict.fromkeys(yes.reasons + no.reasons))
    return side, 'BUY_' + side, ()


def evaluate_edge(snapshot: MarketSnapshot, prediction: Prediction, config: EdgeConfig, *, evaluation_at: int):
    if not isinstance(snapshot, MarketSnapshot) or not isinstance(prediction, Prediction) or not isinstance(config, EdgeConfig):
        raise TypeError('validated snapshot, explicit prediction and edge config required')
    if not timestamp(evaluation_at):
        raise ValueError('invalid explicit evaluation time')
    with localcontext(CONTEXT):
        reasons = []
        if snapshot.experiment_id != prediction.experiment_id: reasons.append('EXPERIMENT_MISMATCH')
        if snapshot.market_id != prediction.market_id: reasons.append('MARKET_MISMATCH')
        target = prediction.target_definition
        if (target.probability_semantics != 'MARKET_YES' or target.outcome_mapping != snapshot.outcome_mapping
                or target.rule_hash != snapshot.rule_hash or target.expiry != snapshot.expiry):
            reasons.append('TARGET_MISMATCH')
        if prediction.support_status != 'SUPPORTED': reasons.append('UNSUPPORTED_PREDICTION')
        receipt_age = evaluation_at - snapshot.received_at
        source_age = evaluation_at - snapshot.source_at
        if receipt_age < 0: reasons.append('NEGATIVE_RECEIPT_AGE')
        if source_age < 0: reasons.append('NEGATIVE_SOURCE_AGE')
        if snapshot.reference_price_at is not None and snapshot.reference_price_at > evaluation_at:
            reasons.append('REFERENCE_PRICE_NOT_AVAILABLE')
        if snapshot.available_at > evaluation_at: reasons.append('SNAPSHOT_NOT_AVAILABLE')
        if prediction.available_at > evaluation_at: reasons.append('PREDICTION_NOT_AVAILABLE')
        if evaluation_at >= snapshot.expiry: reasons.append('MARKET_EXPIRED')
        yes = no = preferred = None
        action = 'NO_TRADE'
        if not reasons:
            yes = _side('YES', prediction.p_yes, snapshot.yes_mid, snapshot.yes_asks, config)
            no = _side('NO', 1 - prediction.p_yes, snapshot.no_mid, snapshot.no_asks, config)
            preferred, action, selected_reasons = choose_candidate(yes, no)
            reasons.extend(selected_reasons)
        identity = dict(experiment_id=snapshot.experiment_id, prediction_id=prediction.prediction_id,
                        snapshot_id=snapshot.snapshot_id, evaluated_at=evaluation_at, config_hash=config.hash)
        return EdgeEvaluation(digest(identity), snapshot.experiment_id, prediction.prediction_id,
                              snapshot.snapshot_id, evaluation_at, prediction.p_yes, 1 - prediction.p_yes,
                              snapshot.yes_mid, snapshot.no_mid, config.target_shares, receipt_age, source_age,
                              yes, no, preferred, action, tuple(reasons), config.hash, config.edge_version,
                              config.split_treatment)
