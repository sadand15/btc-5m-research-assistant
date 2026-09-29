"""A deterministic IOC depth walk with a shared physical-lot budget."""
from dataclasses import asdict,dataclass
from decimal import Decimal,localcontext
from btc5_v3.edge.numeric import CONTEXT,number

D=Decimal


@dataclass(frozen=True)
class DepthFill:
    legs: tuple
    filled_shares: Decimal
    unfilled_shares: Decimal
    notional: Decimal
    vwap: Decimal | None
    status: str


def walk_depth(levels,requested,*,direction,consumed):
    """Buy asks ascending; sell bids descending. Shared budget keys are physical IDs."""
    with localcontext(CONTEXT):
        requested=number(requested,minimum=0,maximum=D('1e18'))
        if direction not in ('BUY','SELL'):raise ValueError('buy/sell depth direction required')
        rows=[asdict(x) if not isinstance(x,dict) else dict(x) for x in levels]
        prices=[number(x['price'],minimum=0,maximum=1) for x in rows]
        if prices!=sorted(prices,reverse=direction=='SELL'):raise ValueError('ordered executable depth required')
        if len({x['liquidity_id'] for x in rows})!=len(rows):raise ValueError('duplicate physical lot')
        remaining=requested;legs=[]
        for row,price in zip(rows,prices):
            quantity=number(row['quantity'],minimum=0,maximum=D('1e18'))
            key=row['liquidity_id'];used=number(consumed.get(key,D(0)),minimum=0)
            take=min(remaining,max(D(0),quantity-used))
            if take:
                legs.append(dict(liquidity_id=key,price=price,shares=take,derived=row['derived'],origin_side=row['origin_side']))
                consumed[key]=used+take;remaining-=take
            if not remaining:break
        filled=requested-remaining;cash=sum((x['price']*x['shares'] for x in legs),D(0))
        return DepthFill(tuple(legs),filled,remaining,cash,cash/filled if filled else None,
                         'NO_FILL' if not filled else 'PARTIAL_FILL' if remaining else 'FULL_FILL')
