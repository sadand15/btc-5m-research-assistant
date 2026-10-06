"""M10 binding adapter for complete SYNTHETIC_TEST M9.1 archives only.

No real-to-synthetic relabeling. Readiness checks do not run performance replay.
"""
from dataclasses import dataclass
import json
import sqlite3
from decimal import Decimal

from btc5_v3.encoding import digest, canonical, timestamp
from btc5_v3.models.models import Prediction, TargetDefinition
from btc5_v3.analytics.models import ResolvedOutcome
from btc5_v3.path.models import MarketPathPoint
from btc5_v3.m8.models import Baseline, Dataset, DatasetManifest
from btc5_v3.data_quality.checks import assess
from btc5_v3.prospective.store import read
from btc5_v3.binding_collection.schema import require, validate_manifest
from btc5_v3.binding_collection.store import BindingStudy


@dataclass(frozen=True)
class BindingResult:
    readiness: str
    reasons: tuple[str, ...]
    dataset_root_hash: str | None = None
    dataset: Dataset | None = None
    origin: str = 'SYNTHETIC_TEST'


def load_binding_synthetic(study, *, now, expected_root):
    """Fail closed on incomplete markets, binding defects, or bad input quality."""
    try:
        require(type(study) is BindingStudy and timestamp(now), 'INVALID_REQUEST')
        m = study.manifest
        require(m['role']=='VALIDATION' and m['evidence_mode']=='PROSPECTIVE'
                and m['collection_origin']=='SYNTHETIC_TEST', 'SYNTHETIC_VALIDATION_ONLY')
        cfg = validate_manifest(m)
        require(now >= m['collection_end'], 'FOLLOWUP_NOT_ENDED')
        study.verify(require_sealed=True)
        index = read(study.path('sealed.json'))
        require(expected_root == index['dataset_root_hash'], 'ROOT_MISMATCH')
        baseline = Baseline()
        require(cfg.model_hash==baseline.model_hash and cfg.model_version==baseline.model_version
                and cfg.feature_hash==baseline.feature_hash and cfg.feature_schema_version==baseline.feature_version
                and cfg.calibration_version==baseline.calibration_version
                and cfg.reference_feed=='SYNTHETIC' and cfg.reference_source=='synthetic-oracle'
                and cfg.venue_source=='synthetic' and cfg.rule_hash=='synthetic-rule-v1'
                and cfg.settlement_source==baseline.analytics.outcome_source
                and cfg.settlement_version==baseline.analytics.settlement_version, 'M8_BINDING_UNSUPPORTED')
        events = study.events()
        ids = {}; positions = {}
        for n,e in enumerate(events):
            if 'id' in e['payload']:
                key = e['payload']['id']
                require(key not in ids, 'DUPLICATE_IDENTITY')
                ids[key] = e; positions[key] = n
        states = [e for e in events if e['kind']=='MARKET_STATE']
        markets = {e['payload']['market_id'] for e in states}
        require({e['payload']['market_start'] for e in states} ==
                set(range(m['collection_start'],m['quote_end'],300000)), 'MISSING_MARKET_CYCLE')
        require(len(markets)==(m['quote_end']-m['collection_start'])//300000, 'AMBIGUOUS_MARKET_CYCLE')
        predictions = [e for e in events if e['kind']=='PREDICTION']
        settlements = [e for e in events if e['kind']=='SETTLEMENT']
        require(markets and len(predictions) <= 2000, 'EMPTY_OR_RECORD_BUDGET')
        require({e['payload']['market_id'] for e in predictions} == markets
                and len(predictions)==len(markets), 'MISSING_OR_DUPLICATE_PREDICTION')
        require({e['payload']['market_id'] for e in settlements} == markets
                and len(settlements)==len(markets), 'MISSING_OR_DUPLICATE_SETTLEMENT')
        result = []
        for sequence,e in enumerate(predictions):
            p = e['payload']; market = p['market_id']
            require(not any(x['kind']=='REJECTED' and x['payload']['operation']=='SETTLEMENT'
                            and x['payload']['market_id']==market for x in events), 'SETTLEMENT_REQUIRES_REVIEW')
            associated = []
            for field,kind in (('state_id','MARKET_STATE'),('reference_id','BTC_REFERENCE'),('book_id','BOOK')):
                event = ids[p[field]]
                require(event['kind']==kind and positions[p[field]] < positions[p['id']], 'NONCAUSAL_INPUT')
                require(event['payload']['available_at'] <= event['at'] <= p['generated_at'], 'AVAILABILITY_MISMATCH')
                associated.append(event['payload'])
            state, reference, book = associated
            require(state['market_id']==book['market_id']==market, 'WRONG_MARKET')
            require(state['mapping']=={'YES':'UP','NO':'DOWN'} and state['status']=='OPEN'
                    and state['rule_hash']==cfg.rule_hash and book['raw']['rule_hash']==cfg.rule_hash,
                    'RULE_OR_MAPPING_MISMATCH')
            require(state['definition_hash']==digest(state['definition']) and
                    digest(state['definition']['rules'])==cfg.rule_document_hash, 'DEFINITION_HASH_MISMATCH')
            require(reference['source']==cfg.reference_source and reference['feed']==cfg.reference_feed
                    and reference['symbol']==cfg.reference_symbol and reference['semantics']==cfg.reference_semantics
                    and reference['source_health']=='HEALTHY' and state['source_health']=='HEALTHY', 'REFERENCE_MISMATCH')
            require(all(timestamp(p[k]) for k in ('generated_at','available_at','input_cutoff','market_start','market_end')),
                    'INVALID_PREDICTION_TIME')
            require(m['collection_start'] <= p['market_start']==state['market_start'] < p['market_end']==state['market_end']
                    <= m['quote_end'], 'TARGET_WINDOW_MISMATCH')
            require(p['input_cutoff']==max(x['available_at'] for x in associated)
                    <= p['generated_at'] <= p['available_at'] <= e['at'] < p['market_end'], 'PREDICTION_OUTCOME_ORDER')
            require(p['target_horizon_ms']==p['market_end']-p['generated_at']
                    and p['tte_ms']==p['market_end']-p['available_at'], 'TTE_MISMATCH')
            require(p['config_hash']==m['binding_config_hash'] and p['model_hash']==cfg.model_hash
                    and p['model_config_hash']==cfg.model_config_hash and p['model_version']==cfg.model_version
                    and p['feature_schema_version']==cfg.feature_schema_version
                    and p['feature_hash']==cfg.feature_hash
                    and p['calibration_version']==cfg.calibration_version, 'PREDICTION_BINDING_MISMATCH')
            require(p['input_snapshot_hash']==digest(dict(state=state,reference=reference,book=book)), 'INPUT_HASH_MISMATCH')
            for item,limit in ((state,cfg.max_state_age_ms),(reference,cfg.max_reference_age_ms),(book,cfg.max_book_age_ms)):
                require(0 <= p['available_at']-item['source_at'] <= limit, 'STALE_INPUT')
            require(Decimal(p['p_up'])+Decimal(p['p_down'])==1 and 0<=Decimal(p['p_down'])<=1, 'INVALID_PROBABILITY')
            heartbeat = next(x for x in events if x['hash']==p['heartbeat_hash'] and x['kind']=='HEARTBEAT')
            require(heartbeat['at']==p['health']['heartbeat_at']==p['health']['available_at']
                    <= p['generated_at'] and heartbeat['payload']['source_health']=='OK', 'HEALTH_BINDING')
            pred = Prediction(m['dataset_id'], p['id'], market, Decimal(p['p_up']), cfg.model_version,
                cfg.model_hash, cfg.feature_schema_version, cfg.feature_hash, p['input_cutoff'],p['available_at'],
                TargetDefinition('YES_UP',cfg.rule_hash,p['market_end'],target_source=cfg.reference_source,
                                 target_feed=cfg.reference_feed,
                                 reference_price=state['definition']['opening_reference_price'],
                                 reference_price_at=state['definition']['opening_reference_available_at']),cfg.calibration_version)
            outcome_event = next(x for x in settlements if x['payload']['market_id']==market)
            o = outcome_event['payload']; raw = o['raw_status']
            require(positions[o['id']] > positions[p['id']] and
                    e['at'] < p['market_end'] <= o['settled_at'] <= o['first_observed_at']
                    <= o['available_at'] <= outcome_event['at'] < m['collection_end'], 'SETTLEMENT_TIME_ORDER')
            require(o['raw_settlement_hash']==digest(raw) and raw['market_id']==market
                    and raw['outcome']==o['authoritative_outcome']==o['outcome'] and raw['status']=='RESOLVED'
                    and raw['settled_at']==o['settled_at'] and raw['rule_hash']==o['rule_hash']==cfg.rule_hash
                    and raw['source']==o['source']==cfg.settlement_source
                    and raw['settlement_version']==o['settlement_version']==cfg.settlement_version
                    and o['definition_hash']==state['definition_hash'], 'SETTLEMENT_BINDING_MISMATCH')
            payout = {'UP':Decimal(1),'DOWN':Decimal(0),'SPLIT':Decimal('.5')}[o['authoritative_outcome']]
            outcome = ResolvedOutcome(m['dataset_id'],market,o['settled_at'],o['available_at'],payout,
                                      cfg.settlement_source,cfg.rule_hash,cfg.settlement_version)
            books = []
            for x in events:
                if x['kind']=='BOOK' and x['payload']['market_id']==market and x['payload']['available_at'] > p['available_at']:
                    b = x['payload']; point = MarketPathPoint(b['snapshot_json'])
                    require(point.data()['market_id']==market and point.data()['available_at']==b['available_at']
                            <=x['at'] and point.data()['rule_hash']==cfg.rule_hash, 'BOOK_BINDING_MISMATCH')
                    books.append(dict(available_at=b['available_at'],point={'snapshot_json':point.snapshot_json}))
            require(bool(books), 'MISSING_EXECUTION_BOOK')
            record = dict(id=p['id'],at=p['available_at'],sequence=sequence,source=cfg.venue_source,
                received_at=book['received_at'],available_at=book['available_at'],raw=book['raw'],
                prediction=json.loads(pred.to_json()),health=p['health'],books=books,
                outcome=json.loads(outcome.to_json()),binding_provenance=dict(root=expected_root,
                    prediction_id=p['id'],settlement_id=o['id'],input_hash=p['input_snapshot_hash']))
            require(assess(record,baseline)['state']=='VALID', 'M8_QUALITY_NOT_VALID')
            result.append(record)
        dataset = Dataset(DatasetManifest(m['dataset_id'],'VALIDATION',m['collection_start'],
            m['collection_end']-1,cfg.venue_source,m['created_at'],digest(result)),canonical(result))
        study.verify(require_sealed=True)
        return BindingResult('REPLAY_READY', (), expected_root, dataset)
    except (ValueError, TypeError, KeyError, ArithmeticError, OSError, sqlite3.Error, StopIteration) as error:
        allowed = {'FOLLOWUP_NOT_ENDED','ROOT_MISMATCH','M8_BINDING_UNSUPPORTED',
                   'EMPTY_OR_RECORD_BUDGET','MISSING_MARKET_CYCLE','AMBIGUOUS_MARKET_CYCLE',
                   'MISSING_OR_DUPLICATE_PREDICTION','MISSING_OR_DUPLICATE_SETTLEMENT',
                   'MISSING_EXECUTION_BOOK','M8_QUALITY_NOT_VALID','SETTLEMENT_REQUIRES_REVIEW',
                   'PREDICTION_OUTCOME_ORDER','SETTLEMENT_TIME_ORDER','STALE_INPUT',
                   'SETTLEMENT_BINDING_MISMATCH','INPUT_HASH_MISMATCH'}
        reason = str(error) if type(error) is ValueError and str(error) in allowed else 'MISSING_OR_INVALID_BINDING'
        return BindingResult('NOT_READY', (reason,))
