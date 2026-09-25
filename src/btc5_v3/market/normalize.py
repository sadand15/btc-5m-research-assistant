"""A small versioned YES-book input dialect; not a network collector.

Unknown fields and transport metadata are never persisted. Unparseable bytes
are replaced by an explicit safe marker, not retained under an unsafe raw label.
"""
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import re

from btc5_v3.encoding import canonical, decimal_text, digest, identifier, timestamp
from btc5_v3.market.models import RawMarketEvent

FIELDS = {'market_id','source_at','expiry','market_type','feed','rule_hash','outcome_mapping',
          'yes_bids','yes_asks','reference_underlying_price','reference_price_at',
          'market_status','market_status_at','market_status_available_at'}
TEXT = {'market_id','market_type','feed','rule_hash','outcome_mapping','market_status'}
MAX_PAYLOAD_BYTES = 262144
MAX_LEVELS = 1000


def safe_payload(payload):
    redacted = False
    def placeholder():
        return canonical({'_malformed': True}), 'REDACTED_UNSAFE_PAYLOAD'
    if isinstance(payload, (str, bytes)):
        if len(payload) > MAX_PAYLOAD_BYTES: return placeholder()
        try:
            def pairs(items):
                d={}
                for k,v in items:
                    if k in d: raise ValueError('duplicate JSON key')
                    d[k]=v
                return d
            payload = json.loads(payload, parse_float=Decimal, object_pairs_hook=pairs,
                                 parse_constant=lambda s:s)
        except (ValueError, UnicodeError, RecursionError): return placeholder()
    if not isinstance(payload, dict) or len(payload)>1000: return placeholder()
    if set(payload)-FIELDS: redacted=True

    def number(value):
        nonlocal redacted
        if value is None or type(value) in (int, bool):
            if type(value) is int and value.bit_length() > 210:
                redacted=True; return '[REDACTED]'
            return value
        if isinstance(value, (float, Decimal)):
            value=str(value)
        if isinstance(value, str) and len(value)<=64:
            if value.lower() in ('nan','infinity','-infinity','inf','-inf'):
                redacted=True
                return '[NON_FINITE]'
            if re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d{1,3})?',value):
                try:
                    d=Decimal(value)
                    if d.is_finite() and -100<=d.adjusted()<=100: return decimal_text(d)
                except InvalidOperation: pass
        redacted=True
        return '[REDACTED]'

    out={}
    for key in sorted(FIELDS & payload.keys()):
        value=payload[key]
        if key in TEXT:
            try: out[key]=identifier(value)
            except ValueError: out[key]='[REDACTED]';redacted=True
        elif key in ('yes_bids','yes_asks'):
            if not isinstance(value,list) or len(value)>MAX_LEVELS:
                out[key]='[INVALID_DEPTH]';redacted=True
            else:
                out[key]=[]
                for row in value:
                    if not isinstance(row,(list,tuple)) or len(row)!=2:
                        out[key].append('[INVALID_DEPTH]');redacted=True
                    else: out[key].append([number(row[0]),number(row[1])])
        else: out[key]=number(value)
    encoded=canonical(out)
    if len(encoded.encode())>MAX_PAYLOAD_BYTES: return placeholder()
    return encoded, 'REDACTED' if redacted else 'NONE'


def raw_event(payload, *, experiment_id, source, received_at, sequence, event_key=None,
              recorded_at=None, transport_metadata=None):
    """transport_metadata is deliberately neither serialized nor logged."""
    identifier(experiment_id);identifier(source)
    if not timestamp(received_at) or type(sequence) is not int or not 0<=sequence<2**63:
        raise ValueError('invalid ingestion envelope')
    recorded_at=received_at if recorded_at is None else recorded_at
    if not timestamp(recorded_at) or recorded_at<received_at:
        raise ValueError('invalid recorded_at')
    key=identifier(event_key) if event_key is not None else 'sequence:'+str(sequence)
    encoded,redaction=safe_payload(payload)
    if transport_metadata is not None and redaction=='NONE':redaction='REDACTED'
    parsed=json.loads(encoded)
    source_at=parsed.get('source_at')
    market_id=parsed.get('market_id')
    return RawMarketEvent(digest([experiment_id,source,key]),experiment_id,source,
                          source_at if type(source_at) is int else None,received_at,sequence,
                          market_id if isinstance(market_id,str) and market_id!='[REDACTED]' else None,
                          encoded,hashlib.sha256(encoded.encode()).hexdigest(),1,redaction,'RECEIVED',key,recorded_at,
                          'allowlist-m3-status-v1' if any(k in parsed for k in
                              ('market_status','market_status_at','market_status_available_at')) else 'allowlist-v1')


def normalize_levels(rows, *, descending):
    """Called only on validated positive finite Decimal levels."""
    totals={}
    with localcontext() as context:
        context.prec=80
        for price,quantity in rows:totals[price]=totals.get(price,Decimal(0))+quantity
    return tuple(sorted(totals.items(),reverse=descending))
