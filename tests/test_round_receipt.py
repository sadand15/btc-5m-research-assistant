"""Synthetic-only checks; no chain access or approval of a real deployment."""
from copy import deepcopy

import pytest

from btc5_v3.decision_assistant.round_receipt import (
    CREATED_TOPIC, START_PRICE_TOPIC, ReceiptRejected, decode_candidate_receipt,
)

ADAPTER = "0x" + "ab" * 20
FEED = "0x" + "cd" * 32


def word(value):
    return format(value % 2**256, "064x")


def sample():
    receipt = dict(status="0x1", transactionHash="0x" + "12" * 32,
                   blockHash="0x" + "34" * 32, blockNumber="0xa")
    base = {k: receipt[k] for k in ("transactionHash", "blockHash", "blockNumber")}
    log = dict(base, address=ADAPTER, removed=False, logIndex="0x2",
               topics=[START_PRICE_TOPIC, FEED, "0x" + word(300)],
               data="0x" + word(600) + word(100))
    created = dict(log, logIndex="0x3", topics=[CREATED_TOPIC, FEED, "0x" + word(300)],
                   data="0x" + word(900) + "56" * 32)
    receipt["logs"] = [created, log]
    return receipt


def decode(r):
    return decode_candidate_receipt(r, adapter_address=ADAPTER)


def test_decode_is_deterministic_immutable_and_not_ready():
    r = sample()
    before = deepcopy(r)
    result = decode(r)
    assert result == decode(r)
    assert r == before
    assert [e.log_index for e in result.events] == [2, 3]
    assert result.events[0].raw_start_price == 100
    assert result.events[1].question_id == "0x" + "56" * 32
    assert result.events[0].interval_seconds == 300
    assert result.readiness == "NOT_READY"
    assert "MATCHED_PREDICTOR_VALIDATION_MISSING" in result.blockers
    assert not hasattr(result, "outcome")


@pytest.mark.parametrize("value", [0, -1, -(2**191), 2**191 - 1])
def test_raw_signed_values_have_no_inferred_scale_or_valid_price_status(value):
    r = sample()
    r["logs"][1]["data"] = "0x" + word(600) + word(value)
    assert decode(r).events[0].raw_start_price == value
    assert decode(r).readiness == "NOT_READY"


@pytest.mark.parametrize("field,value", [
    ("removed", True), ("removed", 0), ("blockHash", "0x" + "99" * 32),
    ("transactionHash", "0x" + "99" * 32), ("blockNumber", "0xb"),
    ("logIndex", "0x03"), ("topics", []), ("data", "0x01"),
    ("address", "invalid"),
])
def test_invalid_or_unclassified_log(field, value):
    r = sample()
    r["logs"][1][field] = value
    if field == "topics":
        assert decode(r).unclassified_log_indices == (2,)
    else:
        with pytest.raises(ReceiptRejected):
            decode(r)


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(status="0x0"),
    lambda r: r.update(logs=[]),
    lambda r: r["logs"].append(deepcopy(r["logs"][0])),
    lambda r: r["logs"][1]["topics"].append(FEED),
    lambda r: r["logs"][1]["topics"].__setitem__(2, "0x" + word(0)),
    lambda r: r["logs"][1]["topics"].__setitem__(2, "0x" + word(2**32)),
    lambda r: r["logs"][1].update(data="0x" + word(2**32) + word(1)),
    lambda r: r["logs"][1].update(data="0x" + word(600) + word(2**191)),
])
def test_fail_closed(mutate):
    r = sample()
    mutate(r)
    with pytest.raises(ReceiptRejected):
        decode(r)


def test_other_contract_event_is_not_joined_or_silently_dropped():
    r = sample()
    r["logs"][0]["address"] = "0x" + "ef" * 20
    result = decode(r)
    assert len(result.events) == 1
    assert result.unclassified_log_indices == (3,)
    assert result.readiness == "NOT_READY"
