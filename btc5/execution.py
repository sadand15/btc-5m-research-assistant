"""Depth-limited paper buys, fee deduction, latency and authoritative payout."""
from decimal import Decimal, ROUND_DOWN
import math
from btc5.fees import fee_amount


def adverse_slippage(price,cfg,volatility=0,buy=True):
    bps=cfg.get('fixed_slippage_bps',0)
    if cfg.get('slippage_model')=='volatility':
        bps+=cfg.get('volatility_slippage_multiplier',1)*volatility*10000
    return min(.999999,max(.000001,price*(1+(1 if buy else -1)*bps/10000)))


def fill_buy(book: dict, side: str, budget: float, limit_price: float, cfg: dict) -> dict:
    if side not in ('UP','DOWN') or not math.isfinite(budget) or budget <= 0:
        raise ValueError('Invalid paper order')
    if not 0 < limit_price < 1:
        raise ValueError('Invalid limit price')
    levels = book['up_asks' if side=='UP' else 'down_asks']
    remaining, gross, net, fees, spent = budget,0.,0.,0.,0.
    fills = []
    unit = cfg['fee_deduction']
    if unit not in ('shares','collateral'):
        raise ValueError('Unknown fee deduction mode')
    for price, available in sorted(levels):
        price=adverse_slippage(price,cfg,cfg.get('_volatility',0))
        if price > limit_price or remaining <= 1e-10:
            break
        if available <= 0:
            continue
        fee_per_share = fee_amount(1,price,book['fee_bps'],cfg['fee_discount_multiplier'])
        cost_per_share = price + (fee_per_share if unit=='collateral' else 0)
        qty = min(available,remaining/cost_per_share)
        qty = float(Decimal(str(qty)).quantize(Decimal('0.00000001'),rounding=ROUND_DOWN))
        charge = fee_amount(qty,price,book['fee_bps'],cfg['fee_discount_multiplier'])
        net_qty = qty-charge/price if unit=='shares' else qty
        cost = qty*price + (charge if unit=='collateral' else 0)
        if qty <= 0:
            continue
        remaining -= cost
        gross += qty
        net += net_qty
        fees += charge
        spent += cost
        fills.append({'price':price,'gross_shares':qty,'net_shares':net_qty,'fee_usdt_equivalent':charge,'cost_usdt':cost})
    return {'status':'FILLED' if remaining < 1e-6 else 'PARTIAL' if spent else 'UNFILLED',
            'gross_shares':gross,'net_shares':net,'spent_usdt':spent,'unspent_usdt':max(0,remaining),
            'fee_usdt_equivalent':fees,'fee_deduction':unit,
            'vwap':sum(f['price']*f['gross_shares'] for f in fills)/gross if gross else None,
            'fills':fills}


def quote_ready(book: dict, signal: dict, cfg: dict, now: int, filling=False) -> str | None:
    market = book['market']
    if book.get('market_status','OPEN')!='OPEN':return 'MARKET_NOT_OPEN'
    if signal['cycle_id'] != market['start'] or signal['timestamp'] >= market['end']:
        return 'WRONG_CYCLE'
    if not market['start'] <= now < market['end']:
        return 'MARKET_EXPIRED'
    if not 0 <= now-book['received_at'] <= cfg['max_quote_age_ms']:
        return 'STALE_OR_FUTURE_RECEIPT'
    if not 0 <= now-book['source_at'] <= cfg['max_quote_age_ms']:
        return 'STALE_OR_FUTURE_BOOK'
    if filling and book['source_at'] < signal['timestamp']+cfg['latency_ms']:
        return 'NO_POST_LATENCY_BOOK'
    if market['feed'] != 'BINANCE' and not cfg['allow_basis_risk']:
        return 'VENUE_ORACLE_DIFFERS_FROM_MODEL'
    if not cfg['allow_basis_risk']:
        opening=signal.get('cycle_open')
        if opening is None or market.get('start_price') is None:
            return 'VENUE_OR_MODEL_OPEN_UNAVAILABLE'
        basis_bps=abs(market['start_price']/opening-1)*10000
        if basis_bps > cfg.get('max_open_basis_bps',0.0)+1e-9:
            return 'VENUE_START_PRICE_DIFFERS_FROM_MODEL'
    return None


def prepare(signal: dict, book: dict, cfg: dict) -> tuple[dict | None,str]:
    error = quote_ready(book,signal,cfg,signal['timestamp'])
    if error:
        return None,error
    bids,asks=book.get('yes_bids',[]),book.get('yes_asks',[])
    if not bids or not asks:
        return None,'MISSING_BID_ASK'
    spread=asks[0][0]-bids[0][0]
    if spread>cfg.get('max_prediction_spread',1) or spread/max((asks[0][0]+bids[0][0])/2,1e-8)>cfg.get('max_prediction_spread_pct',2):
        return None,'PREDICTION_SPREAD_TOO_WIDE'
    levels = book['up_asks' if signal['direction']=='UP' else 'down_asks']
    if not any(q>0 for p,q in levels):
        return None,'EMPTY_BOOK'
    limit = min(.999999, min(p for p,q in levels if q>0)*(1+cfg['max_slippage_bps']/10000))
    estimate = fill_buy(book,signal['direction'],cfg['budget_usdt'],limit,cfg)
    if estimate['spent_usdt'] < cfg['min_fill_usdt']:
        return None,'INSUFFICIENT_DEPTH'
    ev = signal['probability']*estimate['net_shares']-estimate['spent_usdt']
    if ev < cfg['min_expected_edge_usdt']:
        return None,'NON_POSITIVE_EXPECTED_VALUE_AFTER_FEES'
    return {**signal,'market_id':book['market_id'],'due_at':signal['timestamp']+cfg['latency_ms'],
            'limit_price':limit,'budget_usdt':cfg['budget_usdt'],'estimated_ev_usdt':ev,
            'quoted_price':min(p for p,q in levels if q>0),'spread':spread,
            'signal_quote_at':book['received_at'],'policy':dict(cfg)},'QUEUED'


def execute(order: dict, book: dict, cfg: dict) -> tuple[dict | None,str]:
    if book['market_id'] != order['market_id']:
        return None,'WRONG_MARKET'
    if book['received_at'] < order['due_at']:
        return None,'WAIT_LATENCY'
    error = quote_ready(book,order,cfg,book['received_at'],filling=True)
    if error:
        return None,error
    fill = fill_buy(book,order['direction'],order['budget_usdt'],order['limit_price'],cfg)
    return {**fill,'filled_at':book['received_at'],'book_source_at':book['source_at'],
            'quoted_price':order.get('quoted_price'),'slippage':fill['vwap']-order['quoted_price'] if fill['vwap'] is not None and order.get('quoted_price') is not None else None,
            'effective_latency_ms':book['received_at']-order['timestamp'],
            'market_id':book['market_id'], 'market':book['market'],
            'expected_ev_usdt':order['probability']*fill['net_shares']-fill['spent_usdt'],
            'model_probability_scope':'BINANCE_PROXY; not calibrated for predict.fun oracle outcome'},fill['status']


def settle_fill(fill: dict, direction: str, yes_payout: float) -> dict:
    if not math.isfinite(yes_payout) or not 0 <= yes_payout <= 1:
        raise ValueError('Missing authoritative payout fraction')
    own_yes = (direction=='UP') == fill['market']['yes_is_up']
    fraction = yes_payout if own_yes else 1-yes_payout
    payout = fill['net_shares']*fraction
    return {'payout_fraction':fraction,'payout_usdt':payout,'pnl_usdt':payout-fill['spent_usdt'],
            'gross_pnl':fill['gross_shares']*fraction-sum(x['gross_shares']*x['price'] for x in fill['fills']),
            'fees':fill['fee_usdt_equivalent'],'net_pnl':payout-fill['spent_usdt'],
            'result':'WIN' if fraction==1 else 'LOSS' if fraction==0 else 'SPLIT'}


def fill_sell(book,side,shares,limit_price,cfg):
    bids=book['yes_bids'] if (side=='UP')==book['market']['yes_is_up'] else [[1-p,q] for p,q in book['yes_asks']]
    remaining=shares;gross=fees=0.;fills=[]
    for p,q in sorted(bids,reverse=True):
        price=adverse_slippage(p,cfg,cfg.get('_volatility',0),buy=False)
        if price<limit_price:break
        quantity=min(remaining,q);remaining-=quantity
        fee=fee_amount(quantity,price,book['fee_bps'],cfg['fee_discount_multiplier'])
        gross+=quantity*price;fees+=fee;fills.append([price,quantity])
        if remaining<=1e-10:break
    return {'filled_shares':shares-remaining,'gross_proceeds':gross,'fees':fees,'net_proceeds':gross-fees,'fills':fills}
