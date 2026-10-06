"""Versioned bindings and strict definitions. No production model defaults."""
from dataclasses import asdict, dataclass
from decimal import Decimal
import json
import re

from btc5_v3.encoding import canonical, digest, identifier, timestamp
from btc5_v3.monitoring.diagnostics import redact
from btc5_v3.prospective.models import definition as m9_definition

VERSION = 'binding-collection-v1'


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(value):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value), 'INVALID_HASH')
    return value


def number(value, *, probability=False):
    require(not isinstance(value, (bool, float)), 'EXPLICIT_DECIMAL_REQUIRED')
    v = Decimal(value)
    require(v.is_finite() and abs(v) <= Decimal('1e18'), 'INVALID_NUMBER')
    require(0 <= v <= 1 if probability else v > 0, 'INVALID_NUMBER')
    return v


def copy(value):
    return json.loads(canonical(value))


@dataclass(frozen=True)
class BindingConfig:
    model_version: str
    model_hash: str
    feature_schema_version: str
    feature_hash: str
    calibration_version: str
    model_config_hash: str
    rule_hash: str
    rule_document_hash: str
    venue_source: str
    reference_source: str
    reference_feed: str
    reference_symbol: str
    reference_semantics: str
    settlement_source: str
    settlement_version: str
    max_reference_age_ms: int
    max_book_age_ms: int
    max_state_age_ms: int

    def __post_init__(self):
        for name in ('model_hash','feature_hash','model_config_hash','rule_document_hash'):
            sha(getattr(self, name))
        for name in ('model_version','feature_schema_version','calibration_version','rule_hash',
                     'venue_source','reference_source','reference_feed','reference_symbol',
                     'reference_semantics','settlement_source','settlement_version'):
            identifier(getattr(self, name))
        for name in ('max_reference_age_ms','max_book_age_ms','max_state_age_ms'):
            require(type(getattr(self, name)) is int and 0 < getattr(self, name) <= 60000,
                    'EXPLICIT_FRESHNESS_LIMIT_REQUIRED')

    @property
    def hash(self):
        return digest(asdict(self))


def definition(study_id, dataset_id, created_at, start, quote_end, followup_end, proof, config,
               *, origin='SYNTHETIC_TEST'):
    require(type(config) is BindingConfig, 'BINDING_CONFIG_REQUIRED')
    require(origin == 'SYNTHETIC_TEST', 'LIVE_COLLECTION_NOT_IMPLEMENTED')
    require(study_id != 'prospective-001', 'LEGACY_STUDY_PROTECTED')
    require(all(timestamp(x) for x in (start, quote_end, followup_end)), 'INVALID_WINDOW')
    require(start < quote_end < followup_end and quote_end % 300000 == 0, 'FIXED_WINDOWS_REQUIRED')
    # Reuse the M9 immutable manifest/storage contract. collection_end is the
    # FINAL acquisition deadline; quote_end is a separate, earlier deadline.
    spec = dict(name=config.venue_source, type='BINDING_EVENTS', endpoint='synthetic://explicit-source',
                symbol=config.reference_symbol, timestamp_semantics='UTC_EPOCH_MS',
                received_at_semantics='COLLECTOR_RECEIPT', mode='SYNTHETIC_ONLY_NO_BACKFILL',
                poll_ms=5000, rule_profile={'rule_hash':config.rule_hash})
    m = m9_definition(study_id, dataset_id, created_at, start, followup_end, spec, proof, origin)
    m.update(schema_version=2, collector_version=VERSION, quote_end=quote_end,
             settlement_followup_end=followup_end, binding_config=asdict(config), binding_config_hash=config.hash,
             prediction_policy='ONE_PER_MARKET_NO_REGENERATION',
             followup_policy='SETTLEMENT_ONLY_NO_WINDOW_EXTENSION',
             notes='Synthetic binding machinery only; real model and authoritative transport are not implemented')
    require(canonical(redact(m)) == canonical(m), 'UNSAFE_MANIFEST')
    return m


def validate_manifest(m):
    require(m['schema_version'] == 2 and m['collector_version'] == VERSION, 'WRONG_BINDING_SCHEMA')
    require(m['collection_origin'] == 'SYNTHETIC_TEST', 'LIVE_COLLECTION_NOT_IMPLEMENTED')
    cfg = BindingConfig(**m['binding_config'])
    require(cfg.hash == m['binding_config_hash'], 'BINDING_CONFIG_CHANGED')
    require(all(timestamp(m[k]) for k in ('created_at','collection_start','quote_end','collection_end',
                                          'settlement_followup_end')), 'INVALID_WINDOW')
    require(m['created_at'] < m['collection_start'] < m['quote_end'] < m['collection_end']
            == m['settlement_followup_end'], 'FIXED_WINDOWS_REQUIRED')
    require(m['prediction_policy'] == 'ONE_PER_MARKET_NO_REGENERATION'
            and m['followup_policy'] == 'SETTLEMENT_ONLY_NO_WINDOW_EXTENSION', 'POLICY_CHANGED')
    return cfg
