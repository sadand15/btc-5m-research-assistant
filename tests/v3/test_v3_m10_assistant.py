"""Synthetic-only examples; threshold values are test fixtures, not live policy."""
from dataclasses import FrozenInstanceError, asdict, replace
from decimal import Decimal, localcontext
import builtins
import socket
import subprocess

import pytest

from btc5_v3.research_assistant import AssistantInput, AssistantPolicy, evaluate

D = Decimal
NOW = 1_000_000


def policy():
    return AssistantPolicy(D('.05'), D('.10'), D('10'), 1000, 800, 500,
                           30000, 240000, D('.70'))


def sample():
    return AssistantInput('synthetic-experiment', 'synthetic-market', 's1', 's1',
                          'SYNTHETIC_TEST', 'YES_UP', NOW - 900, NOW - 700, NOW - 500,
                          NOW - 400, NOW + 60000, D('.75'), D('.25'), D('.80'),
                          'synthetic-calibration-v1', True, True,
                          D('.55'), D('.60'), D('.35'), D('.40'), D('20'), D('20'))


def result(**changes):
    return evaluate(replace(sample(), **changes), policy(), as_of=NOW)


def test_up_down_are_research_labels():
    up = result()
    assert up.signal == 'UP' and up.gate_reasons == ()
    assert up.up_gross_edge == D('.15')
    assert result(p_up=D('.25'), p_down=D('.75')).signal == 'DOWN'
    assert up.source_age_ms == 900 and up.receipt_age_ms == 700
    assert up.prediction_age_ms == 400 and up.tte_ms == 60000
    assert up.yes_spread == up.no_spread == D('.05')
    assert up.calibration_passed and up.quality_passed


@pytest.mark.parametrize('changes,gate', [
    ({'p_up': D('.60'), 'p_down': D('.40')}, 'EDGE_TOO_SMALL'),
    ({'yes_bid': D('.40')}, 'SPREAD_TOO_WIDE'),
    ({'source_at': NOW - 1001}, 'STALE_DATA'),
    ({'received_at': NOW - 801}, 'STALE_DATA'),
    ({'available_at': NOW - 600, 'prediction_available_at': NOW - 501}, 'STALE_PREDICTION'),
    ({'yes_visible_depth': D('9.99')}, 'INSUFFICIENT_LIQUIDITY'),
    ({'no_visible_depth': None}, 'INSUFFICIENT_LIQUIDITY'),
    ({'settles_at': NOW + 29999}, 'TTE_OUT_OF_RANGE'),
    ({'settles_at': NOW + 240001}, 'TTE_OUT_OF_RANGE'),
    ({'settles_at': NOW - 1}, 'TTE_OUT_OF_RANGE'),
    ({'calibration_passed': False}, 'CALIBRATION_GATE'),
    ({'calibration_version': None}, 'CALIBRATION_GATE'),
    ({'quality_passed': None}, 'QUALITY_GATE'),
    ({'quality_passed': 1}, 'QUALITY_GATE'),
    ({'confidence': D('.69')}, 'CONFIDENCE_GATE'),
    ({'prediction_snapshot_id': 'another'}, 'IDENTITY_BINDING'),
    ({'market_id': ''}, 'IDENTITY_BINDING'),
    ({'source_at': None}, 'MISSING_OR_INVALID_TIME'),
    ({'source_at': True}, 'MISSING_OR_INVALID_TIME'),
    ({'prediction_available_at': NOW + 1}, 'NONCAUSAL_TIME'),
    ({'available_at': NOW + 1}, 'NONCAUSAL_TIME'),
    ({'source_at': NOW + 1}, 'NONCAUSAL_TIME'),
    ({'yes_bid': D('.61')}, 'INVALID_QUOTE'),
    ({'no_ask': None}, 'INVALID_QUOTE'),
    ({'p_up': None}, 'INVALID_PROBABILITY'),
    ({'p_down': D('.30')}, 'INVALID_PROBABILITY'),
    ({'origin': 'REALTIME'}, 'UNSUPPORTED_ORIGIN'),
    ({'origin': 'UNKNOWN'}, 'UNSUPPORTED_ORIGIN'),
])
def test_all_gates_wait(changes, gate):
    output = result(**changes)
    assert output.signal == 'WAIT'
    assert gate in output.gate_reasons


@pytest.mark.parametrize('field', ['p_up', 'p_down', 'confidence', 'yes_bid', 'yes_ask',
                                  'no_bid', 'no_ask', 'yes_visible_depth', 'no_visible_depth'])
@pytest.mark.parametrize('bad', [D('NaN'), D('sNaN'), D('Infinity'), D('-Infinity'),
                                 D('-1'), float('nan'), True])
def test_bad_numbers_are_wait_and_not_propagated(field, bad):
    output = result(**{field: bad})
    assert output.signal == 'WAIT'
    assert all(not isinstance(v, Decimal) or v.is_finite() for v in asdict(output).values())


def test_inclusive_policy_boundaries():
    output = result(p_up=D('.65'), p_down=D('.35'), yes_bid=D('.50'),
                    confidence=D('.70'), yes_visible_depth=D('10'), no_visible_depth=D('10'),
                    source_at=NOW - 1000, received_at=NOW - 800,
                    available_at=NOW - 500, prediction_available_at=NOW - 500,
                    settles_at=NOW + 30000)
    assert output.signal == 'UP'
    assert result(settles_at=NOW + 240000).signal == 'UP'


def test_exact_expiry_waits_even_with_zero_minimum_tte():
    output = evaluate(replace(sample(), settles_at=NOW),
                      replace(policy(), min_tte_ms=0), as_of=NOW)
    assert output.signal == 'WAIT' and 'TTE_OUT_OF_RANGE' in output.gate_reasons


def test_unknown_quality_is_distinct_from_failure_and_provenance_is_retained():
    output = result(calibration_passed=None, quality_passed=None)
    assert output.calibration_passed is None and output.quality_passed is None
    assert output.origin == 'SYNTHETIC_TEST'
    assert output.experiment_id == 'synthetic-experiment'
    assert output.market_id == 'synthetic-market'
    assert output.snapshot_id == output.prediction_snapshot_id == 's1'
    rejected = result(calibration_passed=False, quality_passed=False)
    assert rejected.calibration_passed is False and rejected.quality_passed is False


def test_ambiguous_probability_gaps_wait():
    output = result(p_up=D('.5'), p_down=D('.5'), yes_bid=D('.35'), yes_ask=D('.4'))
    assert output.signal == 'WAIT' and 'AMBIGUOUS_DIRECTION' in output.gate_reasons


@pytest.mark.parametrize('origin', ['SYNTHETIC_TEST', 'MOCK', 'OFFLINE'])
def test_explicit_offline_origins(origin):
    assert result(origin=origin).signal == 'UP'


@pytest.mark.parametrize('mapping', ['YES_DOWN', 'UNKNOWN', '', None])
def test_wrong_or_unknown_outcome_mapping_waits(mapping):
    output = result(outcome_mapping=mapping)
    assert output.signal == 'WAIT' and 'TARGET_MAPPING' in output.gate_reasons
    assert output.outcome_mapping is None
    assert result().outcome_mapping == 'YES_UP'


def test_no_io_orders_or_wall_clock(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('offline assistant attempted I/O')
    monkeypatch.setattr(builtins, 'open', forbidden)
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    import time
    monkeypatch.setattr(time, 'time', forbidden)
    assert result().signal == 'UP'


def test_immutable_causal_repeatability():
    evidence = sample()
    original = asdict(evidence)
    before = evaluate(evidence, policy(), as_of=NOW)
    future = replace(evidence, p_up=D('.01'), p_down=D('.99'),
                     source_at=NOW + 1000, received_at=NOW + 1000,
                     available_at=NOW + 1000, prediction_available_at=NOW + 1000)
    assert evaluate(future, policy(), as_of=NOW).signal == 'WAIT'
    assert evaluate(evidence, policy(), as_of=NOW) == before
    assert asdict(evidence) == original
    with pytest.raises(FrozenInstanceError):
        before.signal = 'DOWN'


def test_hash_and_decimal_context_determinism():
    expected = result()
    with localcontext() as context:
        context.prec = 2
        assert result() == expected
    assert policy().hash == policy().hash
    assert replace(policy(), min_gross_edge=D('.06')).hash != policy().hash


@pytest.mark.parametrize('changes', [
    {'min_gross_edge': D(0)}, {'min_gross_edge': D('NaN')},
    {'max_spread': D('Infinity')}, {'min_visible_depth': D(0)},
    {'max_source_age_ms': True}, {'max_receipt_age_ms': -1},
    {'max_prediction_age_ms': 1.5}, {'min_tte_ms': 240001},
    {'min_confidence': D('1.1')},
])
def test_policy_rejects_invalid_configuration(changes):
    with pytest.raises(ValueError):
        replace(policy(), **changes)


@pytest.mark.parametrize('bad', [None, True, -1, 1.1])
def test_invalid_explicit_clock_raises(bad):
    with pytest.raises(ValueError):
        evaluate(sample(), policy(), as_of=bad)
