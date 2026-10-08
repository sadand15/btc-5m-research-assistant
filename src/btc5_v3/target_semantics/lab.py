"""Pure offline semantics and calibration functions; no IO or model fitting."""
from dataclasses import asdict, dataclass
from decimal import Decimal
import hashlib
import json
import math

SIDES = ('UP', 'DOWN', 'TIE')
FEEDS = ('trade', 'mid', 'reference')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def number(value):
    if isinstance(value, bool):
        raise ValueError('boolean is not a price/probability')
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('nonfinite number')
    return result


@dataclass(frozen=True)
class Point:
    market_id: str
    source_at: int
    received_at: int
    available_at: int
    trade: str | None
    bid: str | None
    ask: str | None
    reference: str | None

    def __post_init__(self):
        if any(type(t) is not int for t in (self.source_at, self.received_at, self.available_at)):
            raise ValueError('integer timestamps required')
        if not self.source_at <= self.received_at <= self.available_at:
            raise ValueError('source <= receipt <= availability required')
        for value in (self.trade, self.bid, self.ask, self.reference):
            if value is not None and number(value) <= 0:
                raise ValueError('price must be positive')
        if self.bid is not None and self.ask is not None and number(self.bid) > number(self.ask):
            raise ValueError('crossed book')

    def price(self, feed):
        if feed not in FEEDS:
            raise ValueError('unknown feed')
        if feed == 'mid':
            return None if self.bid is None or self.ask is None else (number(self.bid)+number(self.ask))/2
        value = getattr(self, feed)
        return None if value is None else number(value)


@dataclass(frozen=True)
class Contract:
    market_id: str
    start: int
    end: int
    feed: str
    rule_id: str = 'synthetic-strict-three-way-v1'

    def __post_init__(self):
        if type(self.start) is not int or type(self.end) is not int or self.end-self.start != 300000:
            raise ValueError('explicit 300000 ms interval required')
        if self.feed not in FEEDS or not self.rule_id:
            raise ValueError('explicit feed/rule required')


@dataclass(frozen=True)
class Outcome:
    market_id: str
    contract_hash: str
    side: str
    available_at: int
    authority: str = 'SYNTHETIC_AUTHORITY'


def probabilities(values):
    if set(values) != set(SIDES):
        raise ValueError('UP DOWN TIE all required')
    p = tuple(number(values[s]) for s in SIDES)
    if any(x < 0 or x > 1 for x in p) or sum(p) != 1:
        raise ValueError('probabilities must sum exactly to one')
    return p


def causal_inputs(points, market_id, generated_at):
    """Only already available input within this market; future receipt is excluded."""
    if type(generated_at) is not int:
        raise ValueError('integer generated_at required')
    if not market_id or any(p.market_id != market_id for p in points):
        raise ValueError('market identity mismatch')
    return tuple(sorted((p for p in points if p.available_at <= generated_at),
                        key=lambda p: (p.source_at, p.received_at, p.available_at)))


def analyze(points, contract, generated_at, probs, outcome=None, *, analysis_at=600000,
            end_offset_ms=-1, max_delay_ms=1000):
    """Labels are post-hoc, never predictions; no boundary filling/interpolation."""
    probabilities(probs)
    if end_offset_ms not in (-1, 0) or type(max_delay_ms) is not int or max_delay_ms < 0:
        raise ValueError('unsupported fixed sensitivity')
    if type(analysis_at) is not int or type(generated_at) is not int:
        raise ValueError('explicit integer times required')
    reasons = []
    ch = digest(asdict(contract))
    if not contract.market_id or any(p.market_id != contract.market_id for p in points):
        reasons.append('MISSING_OR_WRONG_MARKET_IDENTITY')
    if not contract.start <= generated_at < contract.end or analysis_at < generated_at:
        reasons.append('INVALID_PREDICTION_TIME')
    inputs = () if reasons else causal_inputs(points, contract.market_id, generated_at)
    inputs = tuple(p for p in inputs if contract.start <= p.source_at < contract.end)
    if not inputs:
        reasons.append('MISSING_CAUSAL_INPUT')
    prediction = dict(generated_at=generated_at, probabilities=dict(probs),
        contract_hash=ch, input_hash=digest([asdict(p) for p in inputs]),
        origin='SYNTHETIC_TEST')
    label = None
    endpoints = []
    for at in (contract.start, contract.end+end_offset_ms):
        matches = [p for p in points if p.market_id == contract.market_id and p.source_at == at
                   and p.available_at <= analysis_at]
        if len(matches) != 1:
            reasons.append('MISSING_OR_AMBIGUOUS_ENDPOINT')
            continue
        p = matches[0]
        if p.available_at-p.source_at > max_delay_ms:
            reasons.append('STALE_REFERENCE')
            continue
        value = p.price(contract.feed)
        if value is None:
            reasons.append('MISSING_FEED_PRICE')
        else:
            endpoints.append(value)
    if len(endpoints) == 2:
        label = 'UP' if endpoints[1] > endpoints[0] else 'DOWN' if endpoints[1] < endpoints[0] else 'TIE'
    if outcome is None:
        reasons.append('MISSING_AUTHORITATIVE_OUTCOME')
    else:
        if outcome.authority != 'SYNTHETIC_AUTHORITY' or outcome.side not in SIDES:
            reasons.append('UNSUPPORTED_AUTHORITY_OR_OUTCOME')
        if outcome.market_id != contract.market_id or outcome.contract_hash != ch:
            reasons.append('OUTCOME_BINDING_MISMATCH')
        if type(outcome.available_at) is not int or not generated_at < contract.end <= outcome.available_at <= analysis_at:
            reasons.append('OUTCOME_TIME_BINDING_INVALID')
        if label is not None and label != outcome.side:
            reasons.append('REFERENCE_OUTCOME_DISAGREEMENT')
    return dict(origin='SYNTHETIC_TEST', readiness='NOT_READY', real_compatibility='TARGET_MISMATCH',
        synthetic_status='VALID' if not reasons else 'NOT_READY', reasons=sorted(set(reasons)),
        prediction=prediction, posthoc_label=label, outcome=asdict(outcome) if outcome else None,
        source_hash=digest(sorted([asdict(p) for p in points], key=canonical)),
        config_hash=digest(dict(contract=asdict(contract), end_offset_ms=end_offset_ms,
                              max_delay_ms=max_delay_ms, analysis_at=analysis_at)))


def calibration(rows, bins=5):
    """Fixed classwise reliability bins; scoring only, no fitting or threshold selection."""
    if type(bins) is not int or bins < 1 or bins > 100:
        raise ValueError('invalid bin count')
    if not rows or any(r['synthetic_status'] != 'VALID' or r['origin'] != 'SYNTHETIC_TEST' for r in rows):
        raise ValueError('only bound valid synthetic rows are scoreable')
    rows = sorted(rows, key=canonical)
    ps = [probabilities(r['prediction']['probabilities']) for r in rows]
    ys = [SIDES.index(r['outcome']['side']) for r in rows]
    n = len(rows)
    brier = sum(sum((p[j]-int(y == j))**2 for j in range(3)) for p,y in zip(ps,ys))/n
    zero = sum(p[y] == 0 for p,y in zip(ps,ys))
    loss = None if zero else sum(-math.log(float(p[y])) for p,y in zip(ps,ys))/n
    tables = []
    for j, side in enumerate(SIDES):
        for b in range(bins):
            ids = [i for i,p in enumerate(ps) if min(int(p[j]*bins), bins-1) == b]
            count = len(ids)
            mean = sum(ps[i][j] for i in ids)/count if count else None
            freq = Decimal(sum(ys[i] == j for i in ids))/count if count else None
            tables.append(dict(side=side, bin=b, n=count,
                mean_probability=float(mean) if mean is not None else None,
                frequency=float(freq) if freq is not None else None))
    ece = sum(t['n']/n*abs(t['mean_probability']-t['frequency']) for t in tables if t['n'])/3
    return dict(origin='SYNTHETIC_TEST', n=n, multiclass_brier=float(brier), log_loss=loss,
        log_loss_status='INFINITE' if zero else 'FINITE', zero_true_probability_count=zero,
        classwise_ece=ece, reliability=tables, bins=bins,
        boundary_rule='[lower,upper), final bin includes 1', calibration_fitted=False,
        limitation='Synthetic scoring does not establish real calibration or trading value')
