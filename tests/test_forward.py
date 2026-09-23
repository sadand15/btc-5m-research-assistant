from copy import deepcopy
from dataclasses import asdict
import asyncio
import json
import joblib
import pytest
from btc5.config import load_config
from btc5.database import Database,dumps
from btc5.forward import freeze,verify,rule_profile,observe,report
from btc5.predictfun import Market,normalize_book
from btc5.venue import VenueService


def rules():
    return {'description':'greater than the price at the beginning; lower than the price at the beginning; '
        'exactly equal resolve 50-50; close price of the 5m candlestick; '
        'https://data.chain.link/streams/btc-usdt-topofbook-datalink',
        'variantData':{'priceFeedProvider':'CHAINLINK','priceFeedSymbol':'BTCUSDT','priceFeedId':'fixture-feed','startPrice':100}}


def setup(tmp_path):
    cfg=load_config();cfg['storage']['database']=str(tmp_path/'db.sqlite');cfg['storage']['model']=str(tmp_path/'model.joblib')
    cfg['entry']['require_book']=False
    joblib.dump({'version':'fixture-version'},cfg['storage']['model'])
    db=Database(cfg['storage']['database']);m=Market(1,300000,600000,True,200,'CHAINLINK',100,'fixture')
    with db.conn:db.conn.execute('INSERT INTO venue_markets VALUES (?,?,?,?,?)',(1,300000,dumps(asdict(m)),dumps(rules()),dumps({})))
    path=tmp_path/'study/manifest.json';manifest=freeze(cfg,path,now=200000)
    return cfg,db,m,path,manifest


def test_freeze_window_overwrite_and_mutation_guards(tmp_path):
    cfg,db,m,path,manifest=setup(tmp_path)
    assert manifest['start']==300000 and manifest['end']-manifest['start']==7*86400000
    assert verify(cfg,path,now=400000)['model_version']=='fixture-version'
    with pytest.raises(ValueError,match='already'):freeze(cfg,path,now=210000)
    changed=deepcopy(cfg);changed['entry']['up_threshold']=.8
    with pytest.raises(ValueError,match='POLICY'):verify(changed,path,now=400000)
    joblib.dump({'version':'different'},cfg['storage']['model'])
    with pytest.raises(ValueError,match='MODEL'):verify(cfg,path,now=400000)
    db.close()


def test_old_input_with_future_inference_completion_is_not_available(tmp_path):
    cfg,db,m,path,manifest=setup(tmp_path);prediction(db)
    with db.conn:db.conn.execute('UPDATE predictions SET available_at=481000')
    observe(db,cfg,record(db,m,480000),manifest)
    assert db.conn.execute('SELECT prediction_id FROM forward_observations').fetchone()[0] is None
    observe(db,cfg,record(db,m,481100),manifest)
    assert db.conn.execute('SELECT prediction_id FROM forward_observations ORDER BY id DESC LIMIT 1').fetchone()[0] is not None
    db.close()


def test_official_rule_profile_is_not_btcusd_or_other_tie_rule():
    assert rule_profile(rules(),{})['verified']
    raw=rules();raw['variantData']['priceFeedSymbol']='BTCUSD'
    assert not rule_profile(raw,{})['verified']
    raw=rules();raw['description']=raw['description'].replace('resolve 50-50','resolves Up')
    assert not rule_profile(raw,{})['verified']


def record(db,m,at):
    b=normalize_book({'marketId':m.id,'updateTimestampMs':at,'bids':[[.39,100]],'asks':[[.41,100]]},m,at)
    with db.conn:db.conn.execute('INSERT INTO venue_books(market_id,received_at,source_at,normalized,raw) VALUES (?,?,?,?,?)',(m.id,at,at,dumps(b),'{}'))
    return b


def prediction(db,at=480000):
    f={'distance_absolute':1,'remaining_seconds':120,'volatility':.001,'trend_15m':.01,'momentum_5m':1,'momentum_1m':1}
    db.prediction(at,300000,101,.8,f,'fixture-version','CANDIDATE UP','ENTRY_CANDIDATE',True)


def test_join_is_causal_deduped_and_primary_is_one_per_cycle(tmp_path):
    cfg,db,m,path,manifest=setup(tmp_path)
    prediction(db,480500) # Future output must not appear on the first observation.
    b=record(db,m,480000);observe(db,cfg,b,manifest)
    first=db.conn.execute('SELECT * FROM forward_observations').fetchone()
    assert first['prediction_id'] is None and not first['eligible']
    for at in (481000,482000):
        b=record(db,m,at);observe(db,cfg,b,manifest);observe(db,cfg,b,manifest)
    assert db.conn.execute('SELECT count(*) FROM forward_observations').fetchone()[0]==3
    pending=report(db,manifest,now=600001)
    assert pending['primary_cycles']==1 and pending['pending_settlements']==1
    with db.conn:db.conn.execute('INSERT INTO venue_outcomes VALUES (?,?,?,?)',(1,600001,1,'{}'))
    result=report(db,manifest,now=600002)
    assert result['binary_settled_cycles']==1 and result['paired_metrics']['model']['accuracy']==1
    assert result['paired_metrics']['market_midpoint']['accuracy']==0
    assert result['primary_coverage_completed']==1
    assert result['waiting_reasons']['VENUE_ORACLE_DIFFERS_FROM_MODEL']==2
    assert result['net_pnl'] is None
    db.close()


def test_changed_rules_ineligible_and_split_excluded_from_accuracy(tmp_path):
    cfg,db,m,path,manifest=setup(tmp_path);prediction(db)
    observe(db,cfg,record(db,m,480000),manifest)
    with db.conn:db.conn.execute('INSERT INTO venue_outcomes VALUES (?,?,?,?)',(1,600000,.5,'{}'))
    result=report(db,manifest,600001)
    assert result['split_settlements']==1 and result['paired_metrics']['model']['accuracy'] is None
    raw=rules();raw['description']+=' changed'
    with db.conn:db.conn.execute('UPDATE venue_markets SET raw_market=?',(dumps(raw),))
    observe(db,cfg,record(db,m,481000),manifest)
    last=db.conn.execute('SELECT eligible,payload FROM forward_observations ORDER BY id DESC LIMIT 1').fetchone()
    assert not last[0] and json.loads(last[1])['venue_reason']=='MARKET_RULES_CHANGED_OR_UNVERIFIED'
    db.close()


def test_unrecognized_resolution_raw_is_preserved_without_guessing(tmp_path):
    cfg,db,m,path,manifest=setup(tmp_path)
    service=VenueService(cfg,db)
    service.client.settlement=lambda market_id:(None,{'status':'RESOLVED','variantData':{'startPrice':100,'endPrice':100}})
    asyncio.run(service.settle())
    assert db.conn.execute('SELECT count(*) FROM venue_resolution_checks').fetchone()[0]==1
    assert db.conn.execute('SELECT count(*) FROM venue_outcomes').fetchone()[0]==0
    db.close()
