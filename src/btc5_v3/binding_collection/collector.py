"""Explicit-clock synthetic collector. Prediction time is stamped after inference.

No network client, historical reader, wallet, order or real model is included.
The injected predictor receives only a copied contemporaneous input bundle.
"""
from dataclasses import asdict
from decimal import Decimal

from btc5_v3.encoding import digest, timestamp, identifier, canonical
from btc5_v3.config.models import ValidatorConfig
from btc5_v3.market.normalize import raw_event, safe_payload
from btc5_v3.market.validation import validate_market
from btc5_v3.monitoring.diagnostics import redact
from .schema import require, number, copy, validate_manifest

DEFINITION_FIELDS = {'rules','feed','target_source','symbol','price_unit','quantity_unit',
                     'condition_id','yes_asset_id','no_asset_id','opening_reference_price',
                     'opening_reference_at','opening_reference_available_at','resolution_semantics','tie_policy'}


class Collector:
    def __init__(self, writer, predictor):
        self.writer = writer
        self.study = writer.study
        self.m = self.study.manifest
        self.config = validate_manifest(self.m)
        self.predictor = predictor

    def events(self, kind=None):
        return [e for e in self.study.events() if kind is None or e['kind'] == kind]

    def _now(self, *, settlement=False):
        now = self.writer.clock()
        require(timestamp(now) and self.m['collection_start'] <= now < self.m['collection_end'],
                'OUTSIDE_FIXED_WINDOW')
        if not settlement:
            require(now < self.m['quote_end'], 'SETTLEMENT_ONLY_FOLLOWUP')
        return now

    def _last(self, kind, market=None):
        found = [e['payload'] for e in self.events(kind)
                 if market is None or e['payload'].get('market_id') == market]
        require(bool(found), 'MISSING_' + kind)
        return found[-1]

    def _reject(self, operation, raw, reason):
        # Preserve safe evidence for invalid books; never arbitrary transport data.
        now = self.writer.clock()
        raw = raw if isinstance(raw, dict) else {}
        market = raw.get('market_id')
        try: identifier(market)
        except ValueError: market = None
        if operation == 'BOOK':
            safe, _ = safe_payload({k:v for k,v in raw.items() if k in
                                    ('market_id','source_at','yes_bids','yes_asks','rule_hash')})
        else:
            safe = canonical(redact({k:v for k,v in raw.items() if k in
                ('market_id','source_at','status','mapping','rule_hash','symbol','source_health')}))
        payload = dict(id=digest(['REJECTED',operation,now,market,reason,safe]), schema_version=2,
                       operation=operation, market_id=market, available_at=now,
                       status='REJECTED', reason=reason, safe_payload=safe, payload_hash=digest(safe))
        if self.m['collection_start'] <= now < self.m['collection_end']:
            self.writer.put('REJECTED', payload)
        return dict(status='REJECTED', reason=reason)

    def _persist(self, kind, raw, payload):
        payload = copy(dict(payload, schema_version=2, receipt_hash=digest(raw)))
        key = payload['id']
        if key in self.writer.ids:
            old = self.writer.ids[key]['payload']
            require(old['receipt_hash'] == payload['receipt_hash'], 'EVENT_IDENTITY_CONFLICT')
            return old
        self.writer.put(kind, payload)
        return payload

    def state(self, raw):
        now = self._now()
        try:
            require(isinstance(raw, dict) and set(raw) == {'market_id','market_start','market_end',
                    'source_at','source_health','status','mapping','rule_hash','definition'}, 'STATE_SCHEMA')
            market = identifier(raw['market_id'])
            require(raw['source_health'] == 'HEALTHY', 'VENUE_UNHEALTHY')
            require(raw['mapping'] == {'YES':'UP','NO':'DOWN'}, 'AMBIGUOUS_MAPPING')
            require(raw['rule_hash'] == self.config.rule_hash, 'RULE_MISMATCH')
            start, end, source = raw['market_start'], raw['market_end'], raw['source_at']
            require(all(timestamp(t) for t in (start,end,source)), 'INVALID_TIMESTAMP')
            require(start % 300000 == 0 and end-start == 300000 and
                    self.m['collection_start'] <= start < end <= self.m['quote_end'], 'MARKET_WINDOW')
            require(start <= now and source <= now and now-source <= self.config.max_state_age_ms,
                    'STALE_STATE')
            require(raw['status'] in ('OPEN','CLOSED','RESOLVED','SUSPENDED','UNKNOWN'), 'UNKNOWN_STATE')
            require(raw['status'] != 'OPEN' or now < end, 'EXPIRED_OPEN_STATE')
            d = raw['definition']
            require(isinstance(d, dict) and set(d) == DEFINITION_FIELDS, 'DEFINITION_REQUIRED')
            require(isinstance(d['rules'], str) and 0 < len(d['rules']) <= 10000 and
                    digest(d['rules']) == self.config.rule_document_hash, 'RULE_DOCUMENT_MISMATCH')
            for k in DEFINITION_FIELDS - {'rules','opening_reference_price','opening_reference_at',
                                         'opening_reference_available_at'}: identifier(d[k])
            number(d['opening_reference_price'])
            require(timestamp(d['opening_reference_at']) and timestamp(d['opening_reference_available_at'])
                    and d['opening_reference_at'] <= start
                    and d['opening_reference_at'] <= d['opening_reference_available_at'] <= now,
                    'NONCAUSAL_OPENING_REFERENCE')
            require(d['resolution_semantics']=='AUTHORITATIVE_BINARY_OR_SPLIT'
                    and d['tie_policy']=='AUTHORITATIVE_SPLIT_HALF', 'UNSUPPORTED_RESOLUTION_SEMANTICS')
            require(d['feed'] == self.config.reference_feed and d['target_source'] == self.config.reference_source
                    and d['symbol'] == self.config.reference_symbol, 'REFERENCE_SEMANTICS')
            require(d['price_unit'] == 'COLLATERAL_PER_SHARE' and d['quantity_unit'] == 'SHARES', 'UNKNOWN_UNITS')
            require(d['yes_asset_id'] != d['no_asset_id'], 'AMBIGUOUS_MAPPING')
            previous = [e['payload'] for e in self.events('MARKET_STATE') if e['payload']['market_id']==market]
            if previous:
                require(previous[0]['definition_hash'] == digest(d) and previous[0]['market_start'] == start
                        and previous[0]['market_end'] == end, 'MARKET_DEFINITION_CHANGED')
            return self._persist('MARKET_STATE', raw, dict(raw,
                id=digest(['STATE',market,source,raw['status']]), observed_at=now, available_at=now,
                source=self.config.venue_source, definition_hash=digest(d)))
        except (ValueError, TypeError, KeyError, ArithmeticError):
            return self._reject('STATE', raw, 'INVALID_STATE_OR_RULE')

    def reference(self, raw):
        now = self._now()
        try:
            require(isinstance(raw, dict) and set(raw) == {'price','source','source_at','source_health',
                    'symbol','feed','semantics'}, 'REFERENCE_SCHEMA')
            number(raw['price'])
            require(raw['source'] == self.config.reference_source and raw['feed'] == self.config.reference_feed
                    and raw['symbol'] == self.config.reference_symbol and
                    raw['semantics'] == self.config.reference_semantics, 'REFERENCE_SEMANTICS')
            require(raw['source_health'] == 'HEALTHY', 'REFERENCE_UNHEALTHY')
            require(timestamp(raw['source_at']) and 0 <= now-raw['source_at'] <= self.config.max_reference_age_ms,
                    'STALE_REFERENCE')
            return self._persist('BTC_REFERENCE', raw, dict(raw,
                id=digest(['REFERENCE',raw['source'],raw['source_at']]), received_at=now, available_at=now))
        except (ValueError, TypeError, KeyError, ArithmeticError):
            return self._reject('REFERENCE', raw, 'INVALID_OR_STALE_REFERENCE')

    def book(self, raw):
        now = self._now()
        try:
            require(isinstance(raw, dict) and set(raw) == {'market_id','source_at','rule_hash',
                    'yes_bids','yes_asks'}, 'BOOK_SCHEMA')
            state = self._last('MARKET_STATE', raw['market_id'])
            require(raw['rule_hash'] == self.config.rule_hash, 'RULE_MISMATCH')
            require(state['status'] == 'OPEN' and 0 <= now-state['source_at'] <= self.config.max_state_age_ms,
                    'STATE_NOT_FRESH_OPEN')
            require(timestamp(raw['source_at']) and 0 <= now-raw['source_at'] <= self.config.max_book_age_ms,
                    'STALE_BOOK')
            envelope = dict(raw, expiry=state['market_end'], market_type='CRYPTO_UP_DOWN',
                feed=self.config.reference_feed, outcome_mapping='YES_UP', market_status='OPEN',
                reference_underlying_price=state['definition']['opening_reference_price'],
                reference_price_at=state['definition']['opening_reference_at'],
                market_status_at=state['source_at'], market_status_available_at=state['available_at'])
            key = digest(['BOOK',raw['market_id'],raw['source_at']])
            event = raw_event(envelope, experiment_id=self.m['dataset_id'], source=self.config.venue_source,
                              received_at=now, sequence=len(self.events()), event_key=key, recorded_at=now)
            cfg = ValidatorConfig(raw['market_id'], self.config.reference_feed, self.config.rule_hash)
            result = validate_market(event, cfg, evaluation_at=now)
            if result.snapshot is None:
                return self._reject('BOOK', raw, 'BOOK_STRUCTURAL_REJECTION')
            return self._persist('BOOK', raw, dict(id=key, market_id=raw['market_id'], source_at=raw['source_at'],
                received_at=now, available_at=now, state_id=state['id'], raw=envelope,
                snapshot_json=result.snapshot.to_json(), validator_version=result.validator_version,
                validator_config_hash=cfg.hash, validation_status='VALID'))
        except (ValueError, TypeError, KeyError, ArithmeticError):
            return self._reject('BOOK', raw, 'INVALID_BOOK_BINDING')

    def predict(self, market):
        self._now()
        identifier(market)
        key = digest(['PREDICTION',self.m['dataset_id'],market,self.m['binding_config_hash']])
        if key in self.writer.ids:
            return copy(self.writer.ids[key]['payload'])
        try:
            state = self._last('MARKET_STATE', market)
            reference = self._last('BTC_REFERENCE')
            book = self._last('BOOK', market)
            now = self.writer.clock()
            self._check_inputs(state, reference, book, now)
            require(self.predictor.binding_hash == self.m['binding_config_hash'], 'PREDICTOR_BINDING_MISMATCH')
            bundle = copy(dict(state=state, reference=reference, book=book))
            input_hash = digest(bundle)
            self.writer.source_health = 'OK'
            heartbeat = self.writer.heartbeat()
            # No historical timestamp arguments; only probabilities may return.
            result = self.predictor.predict(copy(bundle))
            generated = self.writer.clock()
            self._check_inputs(state, reference, book, generated)
            require(self.predictor.binding_hash == self.m['binding_config_hash'], 'PREDICTOR_BINDING_CHANGED')
            require(generated >= now, 'CLOCK_REVERSED')
            require(isinstance(result, dict) and set(result) == {'p_up','p_down'}, 'PREDICTION_SCHEMA')
            up, down = number(result['p_up'], probability=True), number(result['p_down'], probability=True)
            require(up + down == 1, 'PROBABILITY_SUM')
            available = self.writer.clock()
            self._check_inputs(state, reference, book, available)
            require(available >= generated, 'CLOCK_REVERSED')
            failures = sum(e['kind']=='REJECTED' and now-30000 <= e['at'] <= now for e in self.events())
            payload = dict(id=key, schema_version=2, market_id=market,
                market_start=state['market_start'], market_end=state['market_end'], generated_at=generated,
                available_at=available, p_up=str(up), p_down=str(down), model_version=self.config.model_version,
                feature_schema_version=self.config.feature_schema_version, calibration_version=self.config.calibration_version,
                feature_hash=self.config.feature_hash,
                model_hash=self.config.model_hash, model_config_hash=self.config.model_config_hash,
                config_hash=self.m['binding_config_hash'], input_snapshot_hash=input_hash,
                input_cutoff=max(state['available_at'],reference['available_at'],book['available_at']),
                target_horizon_ms=state['market_end']-generated, tte_ms=state['market_end']-available,
                state_id=state['id'], reference_id=reference['id'], book_id=book['id'],
                heartbeat_hash=heartbeat['hash'],
                health=dict(available_at=heartbeat['at'], source_at=book['source_at'], heartbeat_at=heartbeat['at'],
                            provider_healthy=True, source_matches=True, validation_failures=failures,
                            reference=key))
            self.writer.put('PREDICTION', copy(payload))
            return copy(payload)
        except (ValueError, TypeError, KeyError, ArithmeticError, AttributeError):
            return self._reject('PREDICT', {'market_id':market}, 'PREDICTION_REJECTED')

    def _check_inputs(self, state, reference, book, now):
        require(timestamp(now) and self.m['collection_start'] <= now < self.m['quote_end'], 'PREDICTION_WINDOW')
        require(state['status']=='OPEN' and now < state['market_end'], 'OUTCOME_MAY_BE_KNOWN')
        require(self._last('MARKET_STATE',state['market_id'])['id']==state['id'], 'MARKET_CHANGED_DURING_INFERENCE')
        require(0 <= now-reference['source_at'] <= self.config.max_reference_age_ms, 'STALE_REFERENCE')
        require(0 <= now-book['source_at'] <= self.config.max_book_age_ms, 'STALE_BOOK')
        require(0 <= now-state['source_at'] <= self.config.max_state_age_ms, 'STALE_STATE')
        require(all(x['available_at'] <= now for x in (state,reference,book)), 'FUTURE_INPUT')
        require(not any(e['kind']=='SETTLEMENT' and e['payload']['market_id']==state['market_id']
                        for e in self.events()), 'OUTCOME_ALREADY_OBSERVED')
        for op, current in (('STATE',state),('BOOK',book),('REFERENCE',reference)):
            events = self.events()
            index = next(i for i,e in enumerate(events) if e['payload'].get('id') == current['id'])
            require(not any(e['kind']=='REJECTED' and e['payload']['operation']==op
                            and (op=='REFERENCE' or e['payload']['market_id']==state['market_id'])
                            for e in events[index+1:]), 'LATEST_INPUT_REJECTED')

    def settlement(self, raw):
        now = self._now(settlement=True)
        try:
            require(isinstance(raw, dict) and set(raw)=={'market_id','outcome','status','settled_at',
                    'rule_hash','source','settlement_version'}, 'SETTLEMENT_SCHEMA')
            state = self._last('MARKET_STATE', raw['market_id'])
            require(raw['status']=='RESOLVED' and raw['outcome'] in ('UP','DOWN','SPLIT'), 'OUTCOME_REQUIRED')
            require(raw['rule_hash']==self.config.rule_hash and raw['source']==self.config.settlement_source
                    and raw['settlement_version']==self.config.settlement_version, 'SETTLEMENT_BINDING_MISMATCH')
            require(timestamp(raw['settled_at']) and state['market_end'] <= raw['settled_at'] <= now,
                    'INVALID_SETTLEMENT_TIME')
            require(all(e['payload']['available_at'] < raw['settled_at'] for e in self.events('PREDICTION')
                        if e['payload']['market_id']==raw['market_id']), 'PREDICTION_OUTCOME_ORDER')
            payload = dict(raw, id=digest(['SETTLEMENT',raw['market_id']]), first_observed_at=now,
                available_at=now, authoritative_outcome=raw['outcome'], raw_status=raw,
                raw_settlement_hash=digest(raw), definition_hash=state['definition_hash'])
            return self._persist('SETTLEMENT', raw, payload)
        except (ValueError, TypeError, KeyError, ArithmeticError):
            return self._reject('SETTLEMENT', raw, 'SETTLEMENT_REJECTED')

    def step(self, source):
        """Minimal source orchestration; follow-up never asks for inputs/prediction."""
        now = self.writer.clock()
        if now >= self.m['collection_end']:
            return {'phase':'ENDED'}
        self._now(settlement=True)
        if now < self.m['quote_end']:
            state = None
            for read_input, record in ((source.state,self.state),(source.reference,self.reference),(source.book,self.book)):
                if self.writer.clock() >= self.m['quote_end']:
                    break
                try:
                    raw = read_input()
                except Exception:
                    self._reject('SOURCE', {}, 'SOURCE_FAILURE')
                    break
                if self.writer.clock() >= self.m['quote_end']:
                    self._reject('SOURCE', {}, 'SOURCE_RECEIVED_AFTER_QUOTE_WINDOW')
                    break
                value = record(raw)
                if record == self.state: state = value
                if value.get('status')=='REJECTED': break
            else:
                if state is not None and state.get('status')=='OPEN' and self.writer.clock()<self.m['quote_end']:
                    self.predict(state['market_id'])
        for market in self.writer.pending_markets():
            if self.writer.clock() >= self.m['collection_end']:
                break
            try:
                value = source.settlement(market)
            except Exception:
                self._reject('SOURCE', {'market_id':market}, 'SETTLEMENT_SOURCE_FAILURE')
                continue
            if self.writer.clock() >= self.m['collection_end']:
                break
            if value is not None:
                self.settlement(value)
        return {'phase':'SETTLEMENT_FOLLOWUP' if now >= self.m['quote_end'] else 'COLLECTION'}
