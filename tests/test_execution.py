from copy import deepcopy
from dataclasses import asdict
import json
import pytest
from btc5.config import load_config
from btc5.predictfun import Market,normalize_book,bind_market,PredictClient
from btc5.execution import fee_amount,fill_buy,prepare,execute,settle_fill
from btc5.database import Database
from btc5.venue import VenueService,replay


@pytest.fixture
def policy():
    return load_config()['predictfun']


def quote(at=180000,feed='BINANCE'):
    m=Market(1,0,300000,True,200,feed,100.,'btc-example')
    return normalize_book({'marketId':1,'updateTimestampMs':at,'asks':[[.4,10],[.41,100]],'bids':[[.39,100]]},m,at)


def signal(at=180000):
    return dict(timestamp=at,cycle_id=0,cycle_open=100.,direction='UP',probability=.8,model_version='test')


def test_yes_no_ladder_and_fee_formula(policy):
    b=quote()
    assert b['down_asks']==[[.61,100.]]
    assert fee_amount(100,.2,200)==pytest.approx(.4)
    assert fee_amount(100,.8,200)==pytest.approx(.4)
    assert fee_amount(100,.2,200,.9)==pytest.approx(.36)
    f=fill_buy(b,'UP',10,.405,policy)
    assert f['status']=='PARTIAL'
    assert f['spent_usdt']==4
    assert f['net_shares']==pytest.approx(9.8)
    assert f['fee_usdt_equivalent']==pytest.approx(.08)
    assert f['unspent_usdt']==6
    assert settle_fill({**f,'market':b['market']},'UP',1)['pnl_usdt']==pytest.approx(5.8)


def test_cash_fee_alternative_and_budget_cap(policy):
    policy['fee_deduction']='collateral'
    f=fill_buy(quote(),'UP',4,.405,policy)
    assert f['spent_usdt']<=4
    assert f['net_shares']==f['gross_shares']
    assert f['gross_shares']==pytest.approx(4/.408)


def test_latency_cannot_use_old_book_and_price_limit_is_frozen(policy):
    order,status=prepare(signal(),quote(),policy)
    assert status=='QUEUED'
    assert execute(order,quote(180100),policy)[1]=='WAIT_LATENCY'
    old=quote(180000); old['received_at']=180600
    assert execute(order,old,policy)[1]=='NO_POST_LATENCY_BOOK'
    moved=quote(180600); moved['up_asks']=[[.6,100]]
    fill,status=execute(order,moved,policy)
    assert status=='UNFILLED' and fill['spent_usdt']==0
    assert order['limit_price']==pytest.approx(.404)
    fill,status=execute(order,quote(180600),policy)
    assert status=='PARTIAL' and fill['filled_at']==180600


def test_ev_spread_empty_stale_wrong_cycle_and_oracle_guards(policy):
    s=signal(); s['probability']=.3
    assert prepare(s,quote(),policy)[1]=='NON_POSITIVE_EXPECTED_VALUE_AFTER_FEES'
    b=quote(); b['up_asks']=[]
    assert prepare(signal(),b,policy)[1]=='EMPTY_BOOK'
    assert prepare(signal(190000),quote(),policy)[1]=='STALE_OR_FUTURE_RECEIPT'
    s=signal(); s['cycle_id']=300000
    assert prepare(s,quote(),policy)[1]=='WRONG_CYCLE'
    assert prepare(signal(),quote(feed='CHAINLINK'),policy)[1]=='VENUE_ORACLE_DIFFERS_FROM_MODEL'
    altered=quote(); altered['market']['start_price']=101
    assert prepare(signal(),altered,policy)[1]=='VENUE_START_PRICE_DIFFERS_FROM_MODEL'
    assert prepare(signal(),quote(180001),policy)[1]=='STALE_OR_FUTURE_RECEIPT'
    with pytest.raises(ValueError):
        fee_amount(1,float('nan'),200)


def test_authoritative_split_payout_is_not_legacy_void(policy):
    b=quote(); f={**fill_buy(b,'UP',4,.405,policy),'market':b['market']}
    result=settle_fill(f,'UP',.5)
    assert result['result']=='SPLIT' and result['pnl_usdt']==pytest.approx(.9)
    assert settle_fill(f,'UP',0)['pnl_usdt']==-4
    with pytest.raises(ValueError):
        settle_fill(f,'UP',float('nan'))


def test_binding_uses_explicit_duration_symbol_and_outcome():
    m=dict(id=1,marketVariant='CRYPTO_UP_DOWN',feeRateBps=200,categorySlug='btc',
           outcomes=[dict(name='Up',indexSet=1),dict(name='Down',indexSet=2)])
    c=dict(startsAt='2026-01-01T00:00:00Z',endsAt='2026-01-01T00:05:00Z',
           variantDetails={'crypto':dict(priceFeedProvider='CHAINLINK',priceFeedSymbol='BTC_USD',startPrice=90000)})
    assert bind_market(m,c).feed=='CHAINLINK'
    m['outcomes'][0]['name']='Yes'
    with pytest.raises(ValueError,match='MAPPING'):
        bind_market(m,c)
    assert bind_market(m,c,1).yes_is_up
    c['endsAt']='2026-01-01T00:15:00Z'
    with pytest.raises(ValueError,match='five-minute'):
        bind_market(m,c,1)


def test_read_only_api_auth_and_unknown_settlement(monkeypatch,policy):
    monkeypatch.delenv('PREDICT_API_KEY',raising=False)
    c=PredictClient(policy)
    with pytest.raises(PermissionError,match='MISSING'):
        c.get('/v1/markets')
    c.key='fixture'
    with pytest.raises(ValueError,match='GET'):
        c.get('/v1/orders')
    c.get=lambda path: {'data':{'status':'RESOLVED','outcomes':[]}}
    assert c.settlement(1)[0] is None


def test_recorded_replay_no_quotes_is_not_zero_profit(tmp_path,policy):
    cfg=load_config(); db=Database(str(tmp_path/'db.sqlite'))
    result=replay(db,cfg)
    assert result['status']=='NO_RECORDED_QUOTES' and result['pnl_usdt'] is None
    db.close()


def test_restart_pending_fill_persists_and_replay_matches(tmp_path,policy):
    cfg=load_config(); cfg['entry']['require_book']=False; cfg['predictfun']=policy
    cfg['storage']['database']=str(tmp_path/'db.sqlite')
    db=Database(str(tmp_path/'db.sqlite'))
    f={'remaining_seconds':120,'volatility':.001,'trend_15m':.01,'momentum_5m':1,'momentum_1m':1,'distance_absolute':0.}
    db.prediction(180000,0,100,.8,f,'fixture','CANDIDATE UP','test',True)
    service=VenueService(cfg,db)
    b=quote(); service.record(b,{}); service.process(b)
    assert db.conn.execute('SELECT status FROM venue_orders').fetchone()[0]=='QUEUED'
    db.close()
    db=Database(str(tmp_path/'db.sqlite')); service=VenueService(cfg,db)
    b=quote(180600); service.record(b,{}); service.process(b)
    assert db.conn.execute('SELECT status FROM venue_orders').fetchone()[0]=='PARTIAL'
    with db.conn:
        db.conn.execute('INSERT INTO venue_outcomes VALUES (1,310000,1,?)',('{}',))
    out=replay(db,cfg)
    assert out['settled']==1
    assert out['pnl_usdt']==pytest.approx(5.8)
    assert db.conn.execute('SELECT COUNT(*) FROM venue_orders').fetchone()[0]==1
    db.close()
