"""Pure validation: no database, environment, network, or wall-clock access."""
from dataclasses import fields, MISSING
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json

from btc5_v3.config.models import ValidatorConfig
from btc5_v3.encoding import digest, timestamp
from btc5_v3.market.models import DepthLevel, MarketSnapshot, Reason, ValidationResult
from btc5_v3.market.normalize import normalize_levels

VALIDATOR_VERSION='m1-validator-1'


def validate_market(event, config: ValidatorConfig, *, evaluation_at: int) -> ValidationResult:
    if not timestamp(evaluation_at): raise ValueError('explicit evaluation time required')
    if hashlib.sha256(event.safe_payload.encode()).hexdigest()!=event.payload_hash:
        raise ValueError('raw payload integrity failure')
    data=json.loads(event.safe_payload)
    status_keys = {'market_status', 'market_status_at', 'market_status_available_at'}
    extended = isinstance(data, dict) and bool(status_keys & data.keys())
    version = 'm3-market-metadata-1' if extended else VALIDATOR_VERSION
    reasons=[]
    def reject(reason):
        if reason not in reasons: reasons.append(reason)
    context_hash=digest([config.hash,version,evaluation_at])
    validation_id=digest([event.id,context_hash])
    def result(snapshot=None):
        return ValidationResult(validation_id,event.id,event.experiment_id,'INVALID' if reasons else 'VALID',
                                reasons[0] if reasons else None,tuple(reasons),version,
                                evaluation_at,context_hash,snapshot)
    if not isinstance(data,dict) or data.get('_malformed'):
        reject(Reason.MALFORMED);return result()
    if evaluation_at<event.received_at:reject(Reason.NEGATIVE_QUOTE_AGE)
    if evaluation_at<event.recorded_at:reject(Reason.INVALID_TIMESTAMP)
    if data.get('market_id')!=config.market_id:reject(Reason.WRONG_MARKET)
    if data.get('market_type')!=config.market_type:reject(Reason.UNSUPPORTED_MARKET)
    if data.get('outcome_mapping')!=config.outcome_mapping:reject(Reason.UNKNOWN_OUTCOME_MAPPING)
    if data.get('rule_hash')!=config.rule_hash or data.get('feed')!=config.feed:reject(Reason.RULE_MISMATCH)
    source=data.get('source_at');expiry=data.get('expiry')
    if not timestamp(source) or not timestamp(expiry):reject(Reason.INVALID_TIMESTAMP)
    else:
        if source>event.received_at+config.clock_skew_tolerance_ms:reject(Reason.FUTURE_SOURCE_TIME)
        if expiry<=event.received_at or expiry<=source:reject(Reason.INVALID_TIMESTAMP)

    def numeric(value,reason):
        if value=='[NON_FINITE]':reject(Reason.NON_FINITE);return None
        if isinstance(value,bool) or value is None:
            reject(reason);return None
        try: number=Decimal(str(value))
        except (InvalidOperation,ValueError):reject(reason);return None
        if not number.is_finite():reject(Reason.NON_FINITE);return None
        # Bounded precision/size makes arithmetic and hashes reproducible.
        if len(number.as_tuple().digits)>28 or number.as_tuple().exponent < -18:
            reject(reason);return None
        return number

    def depth(key,missing):
        rows=data.get(key)
        if rows is None or rows==[]:reject(missing);return ()
        if not isinstance(rows,list) or len(rows)>config.max_levels:
            reject(Reason.INVALID_DEPTH);return ()
        valid=[]
        for row in rows:
            if not isinstance(row,list) or len(row)!=2:
                reject(Reason.INVALID_DEPTH);continue
            p=numeric(row[0],Reason.INVALID_PRICE);q=numeric(row[1],Reason.INVALID_QUANTITY)
            if p is not None and not 0<p<1:reject(Reason.INVALID_PRICE)
            if q is not None and not 0<q<=Decimal('1e18'):reject(Reason.INVALID_QUANTITY)
            if p is not None and q is not None and 0<p<1 and 0<q<=Decimal('1e18'):valid.append((p,q))
        normalized=normalize_levels(valid,descending=key=='yes_bids')
        if any(q>Decimal('1e18') for _,q in normalized):reject(Reason.INVALID_QUANTITY)
        return normalized

    bids=depth('yes_bids',Reason.MISSING_BID);asks=depth('yes_asks',Reason.MISSING_ASK)
    if bids and asks and bids[0][0]>asks[0][0]:reject(Reason.CROSSED_BOOK)
    reference=data.get('reference_underlying_price');reference_at=data.get('reference_price_at')
    if reference is not None:
        reference=numeric(reference,Reason.INVALID_PRICE)
        if reference is not None and not 0<reference<=Decimal('1e18'):reject(Reason.INVALID_PRICE)
        if not timestamp(reference_at):reject(Reason.INVALID_TIMESTAMP)
        elif reference_at>event.received_at+config.clock_skew_tolerance_ms:reject(Reason.FUTURE_SOURCE_TIME)
    elif reference_at is not None:reject(Reason.MALFORMED)
    if extended:
        if data.get('market_status') not in ('OPEN', 'CLOSED', 'SUSPENDED', 'UNKNOWN'):
            reject(Reason.MALFORMED)
        status_at = data.get('market_status_at')
        status_available = data.get('market_status_available_at')
        if (not timestamp(status_at) or not timestamp(status_available)
                or status_at > status_available or status_available > evaluation_at):
            reject(Reason.INVALID_TIMESTAMP)
        elif status_at > event.received_at+config.clock_skew_tolerance_ms:
            reject(Reason.FUTURE_SOURCE_TIME)
    if reasons:return result()
    def levels(rows,side):
        return tuple(DepthLevel(p,q,digest([event.id,side,p]),side,False) for p,q in rows)
    yes_bids=levels(bids,'YES_BID');yes_asks=levels(asks,'YES_ASK')
    def complementary(rows,descending):
        with localcontext() as ctx:
            ctx.prec=80
            values=[DepthLevel(Decimal(1)-x.price,x.quantity,x.liquidity_id,x.origin_side,True) for x in rows]
        return tuple(sorted(values,key=lambda x:x.price,reverse=descending))
    values=dict(snapshot_id=digest([event.id,config.hash,version]),raw_event_id=event.id,
                experiment_id=event.experiment_id,market_id=config.market_id,source=event.source,
                source_at=source,received_at=event.received_at,available_at=evaluation_at,
                sequence=event.sequence,expiry=expiry,yes_bids=yes_bids,yes_asks=yes_asks,
                no_bids=complementary(yes_asks,True),no_asks=complementary(yes_bids,False),
                feed=config.feed,rule_hash=config.rule_hash,outcome_mapping=config.outcome_mapping,
                reference_underlying_price=reference,reference_price_at=reference_at,
                clock_skew_tolerance_ms=config.clock_skew_tolerance_ms,validator_version=version,
                config_hash=config.hash)
    if extended:
        values.update({key: data[key] for key in status_keys})
    # The only normal construction path. No permissive deserializer is exposed.
    snapshot=object.__new__(MarketSnapshot)
    for field in fields(MarketSnapshot):
        value=values[field.name] if field.name in values else field.default
        if value is MISSING:raise ValueError('incomplete snapshot')
        object.__setattr__(snapshot,field.name,value)
    return result(snapshot)
