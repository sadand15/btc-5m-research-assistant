from dataclasses import replace
from decimal import Decimal as D
import pytest

from btc5_v3.decision_assistant import DecisionInput, DecisionPolicy, evaluate


def policy():
    return DecisionPolicy(D(".03"), D(".05"), D("10"), 30_000, 240_000)


def item(**changes):
    base = dict(as_of=100_000, market_id="m1", market_start=0, market_end=300_000,
        market_rule_hash="rule", token_mapping="YES_UP_NO_DOWN_HALF_TIE",
        target_contract_hash="target", source_at=90_000, received_at=90_100,
        available_at=90_200, prediction_generated_at=90_300, prediction_expires_at=120_000,
        p_up=D(".60"), p_down=D(".30"), p_tie=D(".10"), calibration_verified=True,
        quality_verified=True, approval_digest="proof", approved_digests=frozenset({"proof"}),
        yes_bid=D(".47"), yes_ask=D(".50"), no_bid=D(".32"), no_ask=D(".35"),
        yes_depth=D("100"), no_depth=D("100"), fee_per_share=D(".01"),
        slippage_per_share=D(".01"), origin="SYNTHETIC_TEST",
        prediction_market_id="m1", prediction_rule_hash="rule", prediction_target_contract_hash="target",
        quote_market_id="m1",quote_rule_hash="rule",quote_token_mapping="YES_UP_NO_DOWN_HALF_TIE",
        quote_source_at=99_000,quote_received_at=99_100,quote_available_at=99_200)
    return DecisionInput(**{**base, **changes})


def test_valid_up_keeps_tie_explicit():
    result = evaluate(item(), policy())
    assert result.signal == "UP"
    assert result.state == "EVALUATED"
    assert result.probabilities == (D(".60"), D(".30"), D(".10"))


def test_down_can_win_when_up_probability_is_higher_but_price_is_worse():
    result = evaluate(item(p_up=D(".65"), p_down=D(".30"), p_tie=D(".05"), yes_bid=D(".87"), yes_ask=D(".90"), no_bid=D(".17"), no_ask=D(".20")), policy())
    assert result.signal == "DOWN"


@pytest.mark.parametrize("changes,reason", [
    ({"market_id": None}, "MISSING_MARKET_ID"),
    ({"market_rule_hash": None}, "MISSING_MARKET_RULE_HASH"),
    ({"token_mapping": "UNKNOWN"}, "AMBIGUOUS_TOKEN_MAPPING"),
    ({"calibration_verified": False}, "CALIBRATION_NOT_VERIFIED"),
    ({"quality_verified": False}, "DATA_QUALITY_NOT_VERIFIED"),
    ({"fee_per_share": None}, "MISSING_FEE_PER_SHARE"),
    ({"approved_digests": frozenset()}, "PREDICTION_APPROVAL_NOT_VERIFIED"),
    ({"prediction_generated_at": 101_000}, "NONCAUSAL_PREDICTION_TIME"),
    ({"market_end": 301_000}, "NOT_UTC_5M_MARKET"),
    ({"p_tie": D(".20")}, "INVALID_THREE_CLASS_PROBABILITY"),
])
def test_binding_failure_is_not_evaluated(changes, reason):
    result = evaluate(item(**changes), policy())
    assert result.signal == "WAIT"
    assert result.state == "NOT_EVALUATED"
    assert reason in result.reasons


def test_edge_or_tte_gates_wait():
    result=evaluate(item(yes_bid=D('.62'),yes_ask=D(".65"), no_ask=D(".35")), policy())
    assert result.signal == "WAIT" and result.state == "EVALUATED"
    assert "EDGE_TOO_SMALL_OR_UNAVAILABLE" in result.reasons
    result = evaluate(item(as_of=290_000), policy())
    assert result.signal == "WAIT" and "PREDICTION_EXPIRED" in result.reasons


def test_tie_probability_is_not_strict_down_complement():
    result = evaluate(item(p_up=D(".60"), p_down=D(".20"), p_tie=D(".20")), policy())
    assert result.probabilities[1] != D(".40")


def test_real_origin_without_approved_evidence_waits():
    result = evaluate(item(origin="REAL_VERIFIED", approval_digest=None, approved_digests=frozenset()), policy())
    assert result.signal == "WAIT" and "MISSING_APPROVAL_DIGEST" in result.reasons


def test_half_tie_payout_is_in_both_edges():
    result=evaluate(item(),policy())
    assert result.up_edge==D('.13')
    assert result.down_edge==D('-.02')
    assert result.valid_until==104_000
    assert result.generated_at==100_000


@pytest.mark.parametrize('changes,reason',[
    ({'quote_source_at':94_999},'QUOTE_STALE'),
    ({'quote_source_at':95_000},'QUOTE_STALE'),
    ({'quote_available_at':100_001},'NONCAUSAL_QUOTE_TIME'),
    ({'prediction_expires_at':100_000},'PREDICTION_EXPIRED'),
    ({'prediction_market_id':'other'},'PREDICTION_MARKET_BINDING_MISMATCH'),
    ({'prediction_target_contract_hash':'binance'},'PREDICTION_TARGET_BINDING_MISMATCH'),
    ({'prediction_rule_hash':'other'},'PREDICTION_RULE_BINDING_MISMATCH'),
    ({'quote_market_id':'other'},'QUOTE_MARKET_BINDING_MISMATCH'),
    ({'quote_rule_hash':'other'},'QUOTE_RULE_BINDING_MISMATCH'),
    ({'quote_token_mapping':'reversed'},'QUOTE_TOKEN_MAPPING_BINDING_MISMATCH'),
    ({'quote_source_at':None},'MISSING_TIME_BINDING'),
    ({'as_of':True},'MISSING_TIME_BINDING'),
    ({'as_of':'now'},'MISSING_TIME_BINDING'),
    ({'market_start':1,'market_end':300001},'NOT_UTC_5M_MARKET'),
    ({'market_start':300000,'market_end':600000},'MARKET_NOT_CURRENT'),
    ({'yes_bid':D('.6')},'INVALID_MARKET_QUOTE'),
    ({'calibration_verified':False},'CALIBRATION_NOT_VERIFIED'),
    ({'calibration_verified':'false'},'CALIBRATION_NOT_VERIFIED'),
    ({'quality_verified':1},'DATA_QUALITY_NOT_VERIFIED'),
    ({'approval_digest':None,'approved_digests':frozenset({None})},'PREDICTION_APPROVAL_NOT_VERIFIED'),
    ({'approved_digests':'proof'},'PREDICTION_APPROVAL_NOT_VERIFIED'),
])
def test_missing_or_invalid_evidence_has_no_edge_or_validity(changes,reason):
    result=evaluate(item(**changes),policy())
    assert result.signal=='WAIT' and result.state=='NOT_EVALUATED'
    assert reason in result.reasons
    assert result.up_edge is result.down_edge is result.valid_until is None


def test_quote_can_follow_prediction_but_must_be_available_now():
    assert evaluate(item(),policy()).signal=='UP'
    assert item().quote_source_at > item().prediction_generated_at


def test_exact_validity_boundary_requires_new_evaluation():
    first=evaluate(item(),policy())
    expired=evaluate(item(as_of=first.valid_until),policy())
    assert expired.state=='NOT_EVALUATED'
    assert 'QUOTE_STALE' in expired.reasons


def test_flat_payout_cannot_be_guessed_for_other_contracts():
    mapping='YES_UP_NO_DOWN_STRICT'
    result=evaluate(item(token_mapping=mapping,quote_token_mapping=mapping),policy())
    assert 'TIE_PAYOUT_UNSPECIFIED' in result.reasons
    assert result.up_edge is None


def test_fully_evaluated_quality_gates_remain_wait_not_missing_evidence():
    result=evaluate(item(yes_depth=D('1')),policy())
    assert result.state=='EVALUATED' and result.signal=='WAIT'
    assert result.reasons==('LIQUIDITY_TOO_LOW',)
    assert result.up_edge==D('.13')


def test_future_quote_cannot_change_current_result():
    before=evaluate(item(),policy())
    future=evaluate(item(quote_source_at=101000,quote_received_at=101001,quote_available_at=101002),policy())
    assert future.state=='NOT_EVALUATED'
    assert evaluate(item(),policy())==before


def test_decimal_context_independence():
    from decimal import localcontext
    expected=evaluate(item(),policy())
    with localcontext() as ctx:
        ctx.prec=3
        assert evaluate(item(),policy())==expected
