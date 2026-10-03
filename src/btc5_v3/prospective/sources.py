"""Read-only polling. No historical ranges, trading methods, or fallback feeds."""
from decimal import Decimal
from urllib.parse import quote
import requests
from btc5_v3.encoding import digest


class RuleChanged(ValueError):
    pass


def source_spec(name='binance', poll_ms=5000, profile=None):
    if name not in ('binance', 'predictfun', 'synthetic'):
        raise ValueError('UNSUPPORTED_SOURCE')
    return dict(name=name, type='VENUE_BOOK' if name == 'predictfun' else 'REFERENCE_TRADE',
                endpoint={'binance':'https://data-api.binance.vision/api/v3/aggTrades',
                          'predictfun':'https://api.predict.fun/v1/markets', 'synthetic':'synthetic://fixture'}[name],
                symbol='BTCUSDT', timestamp_semantics='source update UTC milliseconds',
                received_at_semantics='local UTC response receipt milliseconds', mode='READ_ONLY_POLL_NO_BACKFILL',
                poll_ms=poll_ms, rule_profile=profile or {'feed':name, 'symbol':'BTCUSDT'})


class Binance:
    def __init__(self, clock, session=None):
        self.clock, self.http = clock, session or requests.Session()

    def poll(self):
        response = self.http.get('https://data-api.binance.vision/api/v3/aggTrades',
                                 params={'symbol':'BTCUSDT', 'limit':1}, timeout=10, allow_redirects=False)
        if response.status_code != 200:
            raise ValueError('SOURCE_HTTP_FAILURE')
        data = response.json()
        received = self.clock()
        if not isinstance(data, list) or len(data) != 1:
            raise ValueError('MALFORMED_SOURCE')
        p = data[0]
        price, quantity = Decimal(str(p['p'])), Decimal(str(p['q']))
        if not price.is_finite() or not quantity.is_finite() or price <= 0 or quantity < 0:
            raise ValueError('MALFORMED_SOURCE')
        return dict(source='binance', event_key=str(p['a']), source_at=int(p['T']), received_at=received,
                    payload={'price':str(price), 'quantity':str(quantity), 'symbol':'BTCUSDT', 'feed':'BINANCE', 'quote_type':'REFERENCE_TRADE'})


def rule_profile(binding, raw, category):
    """Pin the exact description and explicit feed/mapping, never a guessed rule."""
    description = raw.get('description') or category.get('description')
    if not isinstance(description, str) or not description.strip():
        raise ValueError('UNVERIFIED_RULE_DESCRIPTION')
    return dict(description_hash=digest(description), feed=binding.feed, symbol='BTCUSDT',
                cycle_ms=300000, yes_is_up=binding.yes_is_up, fee_bps=binding.fee_bps,
                variant='CRYPTO_UP_DOWN', rule_semantics='EXACT_DESCRIPTION_HASH_NOT_EXTERNAL_ORACLE_VERIFICATION')


class PredictFun:
    def __init__(self, clock, profile=None, client=None):
        from btc5.predictfun import PredictClient
        self.clock, self.profile = clock, profile
        self.client = client or PredictClient({'api_key_env':'PREDICTFUN_API_KEY'})

    def discover_profile(self):
        binding, raw, category = self.client.discover(self.clock())
        return rule_profile(binding, raw, category)

    def poll(self):
        from btc5.predictfun import bind_market
        binding, raw, category = self.client.discover(self.clock())
        # Refetch current rules before the quote; no inference from old binding.
        raw = self.client.get(f'/v1/markets/{binding.id}')['data']
        category = self.client.get('/v1/categories/' + quote(binding.category_slug, safe=''))['data']
        current = bind_market(raw, category)
        profile = rule_profile(current, raw, category)
        if profile != self.profile:
            raise RuleChanged('RULE_CHANGED')
        book = self.client.get(f'/v1/markets/{current.id}/orderbook')['data']
        received = self.clock()
        if str(book['marketId']) != str(current.id) or not current.start <= received < current.end:
            raise ValueError('WRONG_OR_EXPIRED_MARKET')
        # Preserve actual safe book including malformed depths for later M1 validation.
        return dict(source='predictfun', event_key=f"{current.id}:{book['updateTimestampMs']}",
                    source_at=int(book['updateTimestampMs']), received_at=received, market_id=str(current.id),
                    payload=dict(bids=book.get('bids'), asks=book.get('asks'), rule_hash=digest(profile),
                                 feed=current.feed, symbol='BTCUSDT', market_start=current.start,
                                 market_end=current.end, quote_type='YES_BOOK'))
