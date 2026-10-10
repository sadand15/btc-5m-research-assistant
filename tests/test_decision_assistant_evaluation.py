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
        slippage_per_share=D(".01"), origin="SYNTHETIC_TEST")
    return DecisionInput(**{**base, **changes})


def test_valid_up_keeps_tie_explicit():
    result = evaluate(item(), policy())
    assert result.signal == "UP"
    assert result.state == "EVALUATED"
    assert result.probabilities == (D(".60"), D(".30"), D(".10"))
    assert result.up_edge == D(".13")
    assert result.down_edge == D("-.02")


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
    result = evaluate(item(yes_bid=D(".63"), yes_ask=D(".65"), no_bid=D(".33"), no_ask=D(".35")), policy())
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


def test_real_input_cannot_self_approve():
    result = evaluate(item(origin="REAL_VERIFIED"), policy())
    assert result.state == "NOT_EVALUATED"
    assert "REAL_PREDICTOR_REGISTRY_UNAVAILABLE" in result.reasons
    assert result.up_edge is None and result.down_edge is None


@pytest.mark.parametrize("changes,reason", [
    ({"as_of": True}, "MISSING_TIME_BINDING"),
    ({"as_of": None}, "MISSING_TIME_BINDING"),
    ({"market_start": 1, "market_end": 300001}, "NOT_UTC_5M_MARKET"),
    ({"prediction_expires_at": 300001}, "INVALID_PREDICTION_VALIDITY"),
    ({"prediction_expires_at": 100000}, "PREDICTION_EXPIRED"),
    ({"source_at": 80000}, "STALE_QUOTE"),
    ({"calibration_verified": "false"}, "CALIBRATION_NOT_VERIFIED"),
    ({"quality_verified": "false"}, "DATA_QUALITY_NOT_VERIFIED"),
    ({"yes_depth": None}, "INVALID_LIQUIDITY"),
])
def test_invalid_evidence_never_has_computed_edges(changes, reason):
    result = evaluate(item(**changes), policy())
    assert result.state == "NOT_EVALUATED" and result.signal == "WAIT"
    assert reason in result.reasons
    assert result.up_edge is None and result.down_edge is None


@pytest.mark.parametrize("changes,reason", [
    ({"yes_depth": D("1")}, "LIQUIDITY_TOO_LOW"),
    ({"yes_bid": D(".3")}, "SPREAD_TOO_WIDE"),
])
def test_valid_policy_gate_is_evaluated_wait(changes, reason):
    result = evaluate(item(**changes), policy())
    assert result.state == "EVALUATED" and result.signal == "WAIT"
    assert reason in result.reasons


def test_half_tie_and_zero_tie_payout_are_distinct():
    half = evaluate(item(), policy())
    strict = evaluate(item(token_mapping="YES_UP_NO_DOWN_STRICT"), policy())
    assert half.up_edge - strict.up_edge == D(".05")
    assert half.down_edge - strict.down_edge == D(".05")
