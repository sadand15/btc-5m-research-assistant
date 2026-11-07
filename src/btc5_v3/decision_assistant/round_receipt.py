"""Offline structural decoding only; never approves a venue or prediction.

ABI reference and limitations: docs/research/PUBLIC_ROUND_EVIDENCE.md.
No network, credentials, unit scaling, outcome inference, or source mutation.
"""

from dataclasses import dataclass
import re


START_PRICE_TOPIC = "0xe89432ca865d9fe64c45661232e27514f35299be7d69f2703a7b73e617a8f8ca"
CREATED_TOPIC = "0x678643534cc22e42cd6eb75c34df1efd42e6af33f80d5939d6cafc4e8fb7d485"


class ReceiptRejected(ValueError):
    """Input is structurally inconsistent, not evidence of a valid round."""


def _hex(value, size):
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{%d}" % (size * 2), value):
        raise ReceiptRejected("INVALID_HEX_FIELD")
    return value.lower()


def _quantity(value):
    if not isinstance(value, str) or not re.fullmatch(r"0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)", value):
        raise ReceiptRejected("INVALID_RPC_QUANTITY")
    return int(value, 16)


def _uint32(word):
    value = int(word, 16)
    if value >= 2**32:
        raise ReceiptRejected("UINT32_OVERFLOW")
    return value


@dataclass(frozen=True)
class CandidateRoundEvent:
    kind: str
    log_index: int
    feed_id: str
    interval_seconds: int
    start_timestamp_seconds: int
    raw_start_price: int | None = None
    question_id: str | None = None


@dataclass(frozen=True)
class CandidateReceipt:
    transaction_hash: str
    block_hash: str
    block_number: int
    adapter_address: str
    events: tuple[CandidateRoundEvent, ...]
    unclassified_log_indices: tuple[int, ...]

    @property
    def readiness(self):
        return "NOT_READY"

    @property
    def blockers(self):
        return (
            "DEPLOYMENT_AND_ABI_NOT_VERIFIED",
            "FEED_ID_AND_PRICE_UNITS_NOT_VERIFIED",
            "MARKET_TOKEN_CONDITION_BINDING_MISSING",
            "SETTLEMENT_AND_FINALITY_NOT_VERIFIED",
            "HISTORICAL_AVAILABILITY_NOT_VERIFIED",
            "MATCHED_PREDICTOR_VALIDATION_MISSING",
        )


def decode_candidate_receipt(receipt: dict, *, adapter_address: str) -> CandidateReceipt:
    """Decode two known event layouts without establishing their authenticity.

    adapter_address is an explicit candidate, NOT an approved deployment.
    RPC receipt consistency is not a cryptographic inclusion/finality proof.
    A RoundStartPriceSet event is not itself a settlement outcome. Adjacent
    ConditionResolution logs are intentionally left unclassified, not joined.
    """
    if not isinstance(receipt, dict):
        raise ReceiptRejected("INVALID_RECEIPT")
    if receipt.get("status") != "0x1":
        raise ReceiptRejected("RECEIPT_NOT_SUCCESSFUL")
    tx = _hex(receipt.get("transactionHash"), 32)
    block = _hex(receipt.get("blockHash"), 32)
    number = _quantity(receipt.get("blockNumber"))
    adapter = _hex(adapter_address, 20)
    logs = receipt.get("logs")
    if not isinstance(logs, list):
        raise ReceiptRejected("MISSING_LOGS")
    events, unclassified, indices = [], [], set()
    for log in logs:
        if not isinstance(log, dict):
            raise ReceiptRejected("INVALID_LOG")
        if (log.get("removed") is not False
                or _hex(log.get("transactionHash"), 32) != tx
                or _hex(log.get("blockHash"), 32) != block
                or _quantity(log.get("blockNumber")) != number):
            raise ReceiptRejected("LOG_RECEIPT_BINDING_INVALID")
        index = _quantity(log.get("logIndex"))
        if index in indices:
            raise ReceiptRejected("DUPLICATE_LOG_INDEX")
        indices.add(index)
        address = _hex(log.get("address"), 20)
        topics = log.get("topics")
        if not isinstance(topics, list):
            raise ReceiptRejected("INVALID_TOPICS")
        topics = [_hex(topic, 32) for topic in topics]
        if address != adapter or not topics or topics[0] not in (START_PRICE_TOPIC, CREATED_TOPIC):
            unclassified.append(index)
            continue
        if len(topics) != 3:
            raise ReceiptRejected("EVENT_TOPIC_COUNT")
        data = _hex(log.get("data"), 64)[2:]
        interval = _uint32(topics[2])
        if interval == 0:
            raise ReceiptRejected("ZERO_INTERVAL")
        timestamp = _uint32(data[:64])
        if topics[0] == START_PRICE_TOPIC:
            value = int(data[64:], 16)
            if value >= 2**255:
                value -= 2**256
            if not -(2**191) <= value < 2**191:
                raise ReceiptRejected("INT192_NONCANONICAL")
            event = CandidateRoundEvent("START_PRICE_SET", index, topics[1], interval, timestamp,
                                        raw_start_price=value)
        else:
            event = CandidateRoundEvent("ROUND_CREATED", index, topics[1], interval, timestamp,
                                        question_id="0x" + data[64:])
        events.append(event)
    if not events:
        raise ReceiptRejected("NO_KNOWN_CANDIDATE_EVENTS")
    return CandidateReceipt(tx, block, number, adapter,
                            tuple(sorted(events, key=lambda e: e.log_index)),
                            tuple(sorted(unclassified)))
