"""Predict.fun public market-data adapter. GET only; no wallet or order API."""
from dataclasses import dataclass, asdict
from datetime import datetime
import math
import os
import time
from urllib.parse import quote
import requests


def timestamp(value: str) -> int:
    dt = datetime.fromisoformat(value.replace('Z','+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Market timestamps must include timezone')
    return int(dt.timestamp()*1000)


@dataclass(frozen=True)
class Market:
    id: int
    start: int
    end: int
    yes_is_up: bool
    fee_bps: int
    feed: str
    start_price: float | None
    category_slug: str


def bind_market(m: dict, category: dict, up_index_set: int | None = None) -> Market:
    start, end = timestamp(category['startsAt']), timestamp(category['endsAt'])
    if end-start != 300000 or start % 300000:
        raise ValueError('Not an aligned five-minute market')
    if m.get('marketVariant') != 'CRYPTO_UP_DOWN':
        raise ValueError('Not a crypto up/down market')
    details = (category.get('variantDetails') or {}).get('crypto') or category.get('variantData') or m.get('variantData') or {}
    symbol = str(details.get('priceFeedSymbol','')).upper().replace('/','').replace('_','').replace('-','')
    if symbol not in ('BTCUSDT','BTCUSD'):
        raise ValueError('BTC price feed could not be verified')
    outcomes = m['outcomes']
    if len(outcomes) != 2 or {int(o['indexSet']) for o in outcomes} != {1,2}:
        raise ValueError('Unsupported outcome shape')
    up = [int(o['indexSet']) for o in outcomes if str(o['name']).strip().lower() in ('up','higher','上涨')]
    if up_index_set is not None:
        if up_index_set not in (1,2):
            raise ValueError('up_index_set must be 1 or 2')
        up = [up_index_set]
    if len(up) != 1:
        raise ValueError('UNVERIFIED_OUTCOME_MAPPING: set up_index_set after checking market question')
    fee = int(m['feeRateBps'])
    if not 0 <= fee <= 10000:
        raise ValueError('Invalid feeRateBps')
    opening = details.get('startPrice')
    if opening is not None and (not math.isfinite(float(opening)) or float(opening) <= 0):
        raise ValueError('Invalid venue starting price')
    return Market(int(m['id']), start, end, up[0] == 1, fee, str(details['priceFeedProvider']),
                  float(opening) if opening is not None else None, str(m['categorySlug']))


def normalize_book(raw: dict, market: Market, received_at: int) -> dict:
    if int(raw['marketId']) != market.id:
        raise ValueError('Orderbook/market ID mismatch')
    bids = sorted([[float(p),float(q)] for p,q in raw['bids']], reverse=True)
    asks = sorted([[float(p),float(q)] for p,q in raw['asks']])
    for p,q in bids+asks:
        if not math.isfinite(p+q) or not 0 < p < 1 or q < 0:
            raise ValueError('Invalid prediction market depth')
    if bids and asks and bids[0][0] > asks[0][0]:
        raise ValueError('Crossed prediction book')
    # Official book is YES. Buying NO consumes YES bids at the complementary price.
    yes = asks
    no = sorted([[1-p,q] for p,q in bids])
    return {'market_id':market.id,'source_at':int(raw['updateTimestampMs']), 'received_at':received_at,
            'up_asks':yes if market.yes_is_up else no, 'down_asks':no if market.yes_is_up else yes,
            'yes_bids':bids,'yes_asks':asks,'fee_bps':market.fee_bps,'market':asdict(market)}


class PredictClient:
    BASE = 'https://api.predict.fun'

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.http = requests.Session()
        self.key = os.environ.get(cfg.get('api_key_env','PREDICTFUN_API_KEY')) or os.environ.get('PREDICT_API_KEY')
        if self.key:
            self.http.headers['x-api-key'] = self.key

    def get(self, path: str, **params):
        if not self.key:
            raise PermissionError('PREDICT_API_KEY_MISSING')
        if not (path.startswith('/v1/markets') or path.startswith('/v1/categories/')):
            raise ValueError('Only market-data GET endpoints are allowed')
        r = self.http.get(self.BASE+path,params=params,timeout=12,allow_redirects=False)
        if 300 <= r.status_code < 400:
            raise ValueError('Unexpected market-data redirect')
        if r.status_code in (401,403):
            raise PermissionError('PREDICT_MARKET_DATA_AUTH_FAILED')
        if r.status_code == 429:
            raise RuntimeError('PREDICT_RATE_LIMIT')
        r.raise_for_status()
        payload = r.json()
        if not payload.get('success'):
            raise ValueError('Predict API returned unsuccessful market response')
        return payload

    def discover(self, now: int) -> tuple[Market,dict,dict]:
        cursor = None
        for _ in range(self.cfg.get('discovery_pages',3)):
            params = dict(first=50,status='OPEN',marketVariant='CRYPTO_UP_DOWN')
            if cursor:
                params['after'] = cursor
            response = self.get('/v1/markets',**params)
            for m in response['data']:
                if not any(word in (m.get('title','')+' '+m.get('question','')).lower() for word in ('btc','bitcoin')):
                    continue
                if m.get('tradingStatus') != 'OPEN':
                    continue
                category = self.get('/v1/categories/'+quote(m['categorySlug'],safe=''))['data']
                try:
                    binding = bind_market(m,category,self.cfg.get('up_index_set'))
                except (KeyError,ValueError):
                    continue
                if binding.start <= now < binding.end:
                    return binding,m,category
            next_cursor = response.get('cursor')
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        raise ValueError('NO_VERIFIED_ACTIVE_BTC_5M_MARKET')

    def book(self, market: Market) -> tuple[dict,dict]:
        current=self.get(f'/v1/markets/{market.id}')['data']
        if current.get('tradingStatus')!='OPEN':
            raise ValueError('MARKET_NOT_OPEN')
        raw = self.get(f'/v1/markets/{market.id}/orderbook')['data']
        return normalize_book(raw,market,int(time.time()*1000)),raw

    def settlement(self, market_id: int) -> tuple[float | None,dict]:
        raw = self.get(f'/v1/markets/{market_id}')['data']
        if raw.get('status') != 'RESOLVED':
            return None,raw
        resolution = raw.get('resolution')
        if isinstance(resolution,dict) and resolution.get('indexSet') in (1,2):
            return float(resolution['indexSet']==1),raw
        winners = [o for o in raw.get('outcomes',[]) if o.get('status')=='WON']
        if len(winners)==1:
            return float(winners[0]['indexSet']==1),raw
        # Neither endPrice nor Binance is an authoritative substitute for an unknown
        # cancellation/tie payout. Keep it unresolved until explicit venue evidence.
        return None,raw
