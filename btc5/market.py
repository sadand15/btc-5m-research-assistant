"""Read-only live, recorded-as-of and explicitly simulated quote providers."""
from abc import ABC,abstractmethod
from bisect import bisect_right
from copy import deepcopy
import json
import math
from pathlib import Path
from btc5.predictfun import PredictClient,Market,normalize_book


class MarketDataProvider(ABC):
    mode='DISABLED'
    @abstractmethod
    def quote(self,timestamp,context=None): ...


def metadata(book,mode):
    book=deepcopy(book)
    bids,asks=book['yes_bids'],book['yes_asks']
    bid=bids[0][0] if bids else None; ask=asks[0][0] if asks else None
    book.update(timestamp=book['source_at'],best_bid=bid,best_ask=ask,
        spread=ask-bid if bid is not None and ask is not None else None,
        depth={'bids':bids,'asks':asks},market_status=book.get('market_status','OPEN'),source=mode)
    return book


class MockQuoteProvider(MarketDataProvider):
    mode='SIMULATED QUOTE'
    def __init__(self,cfg):self.cfg=cfg
    def quote(self,timestamp,context=None):
        if not context or context['timestamp']>timestamp or timestamp//300000*300000!=context['cycle_id']:
            return None
        # A stated synthetic pricing process, never a model prediction or future label.
        z=float(context.get('distance_remaining_z',0))
        mid=.5*(1+math.erf(z/math.sqrt(2)))
        mid=max(.04,min(.96,mid+.004*math.sin(timestamp/233.0)))
        spread=self.cfg.get('mock_spread',.02)
        bid=max(.001,mid-spread/2);ask=min(.999,mid+spread/2)
        depth=self.cfg.get('mock_depth_shares',200)
        market=Market(context['cycle_id'],context['cycle_id'],context['cycle_id']+300000,
            True,self.cfg.get('mock_fee_bps',200),'BINANCE',context.get('cycle_open',1),'SIMULATED')
        book=normalize_book({'marketId':market.id,'updateTimestampMs':timestamp,
            'bids':[[max(.001,bid-i*.005),depth] for i in range(3)],
            'asks':[[min(.999,ask+i*.005),depth] for i in range(3)]},market,timestamp)
        return metadata(book,self.mode)


class ReplayQuoteProvider(MarketDataProvider):
    mode='REPLAY DATA'
    def __init__(self,rows):
        self.rows=sorted(rows,key=lambda r:r['received_at']);self.times=[r['received_at'] for r in self.rows]
        for index,r in enumerate(self.rows):
            if r['source_at']>r['received_at']:raise ValueError('Quote received before source timestamp')
            # Validate prices and full YES/NO mapping, even for normalized JSON imports.
            checked=normalize_book({'marketId':r['market_id'],'updateTimestampMs':r['source_at'],
                'bids':r['yes_bids'],'asks':r['yes_asks']},Market(**r['market']),r['received_at'])
            self.rows[index]=checked
            self.rows[index]['market_status']=r.get('market_status','OPEN')
    def quote(self,timestamp,context=None):
        i=bisect_right(self.times,timestamp)-1
        return metadata(self.rows[i],self.mode) if i>=0 else None
    @classmethod
    def from_file(cls,path):
        path=Path(path)
        if path.suffix.lower()=='.csv':
            import csv
            with path.open(encoding='utf-8-sig',newline='') as f:raw=list(csv.DictReader(f))
        else:raw=json.loads(path.read_text(encoding='utf-8'))
        rows=[]
        for r in raw:
            if 'yes_bids' in r:rows.append(r);continue
            t=int(r['timestamp']);cycle=int(r.get('cycle_id',t//300000*300000))
            # Fee is required; depth must be observed rather than invented.
            depth=r['depth'];depth=json.loads(depth) if isinstance(depth,str) else depth
            m=Market(int(r.get('market_id',cycle)),cycle,cycle+300000,True,int(r['fee_bps']),
                r.get('feed','UNKNOWN'),float(r['cycle_open']) if r.get('cycle_open') else None,'IMPORTED')
            book=normalize_book({'marketId':m.id,'updateTimestampMs':t,'bids':depth['bids'],'asks':depth['asks']},m,int(r.get('received_at',t)))
            if abs(book['yes_bids'][0][0]-float(r['bid']))>1e-8 or abs(book['yes_asks'][0][0]-float(r['ask']))>1e-8:
                raise ValueError('Top quote disagrees with recorded depth')
            rows.append(book)
        return cls(rows)


class LiveProvider(MarketDataProvider):
    mode='LIVE DATA'
    def __init__(self,cfg):self.client=PredictClient(cfg);self.market=None
    def quote(self,timestamp,context=None):
        if not self.client.key:return None
        if not self.market or not self.market.start<=timestamp<self.market.end:
            self.market,_,_=self.client.discover(timestamp)
        book,_=self.client.book(self.market)
        return metadata(book,self.mode)
