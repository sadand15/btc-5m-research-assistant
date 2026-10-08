"""Synthetic-only target semantics and causality regressions."""
from dataclasses import replace
import json

import pytest

from btc5_v3.target_semantics.demo import P, bound, build_report, points
from btc5_v3.target_semantics.lab import Contract, Point, analyze, calibration, causal_inputs, probabilities


def setup():
    c = Contract('synthetic-cycle', 0, 300000, 'trade')
    return points(), c, bound(c, 'UP')


def test_same_window_three_different_labels():
    report = build_report()
    assert [report['comparisons'][f]['posthoc_label'] for f in ('trade','mid','reference')] == ['UP','DOWN','TIE']
    assert all(r['synthetic_status'] == 'VALID' and r['readiness'] == 'NOT_READY' for r in report['comparisons'].values())


@pytest.mark.parametrize('p', [dict(UP='1',DOWN='0'), dict(UP='.6',DOWN='.3',TIE='.2'),
    dict(UP='NaN',DOWN='0',TIE='0'), dict(UP='1.1',DOWN='-.1',TIE='0'),
    dict(UP=True,DOWN=0,TIE=0)])
def test_invalid_probability_simplex(p):
    with pytest.raises(ValueError): probabilities(p)


def test_tie_mass_is_not_down_complement():
    up, down, tie = probabilities(P)
    assert up+down+tie == 1 and 1-up != down
    assert up+tie/2 + down+tie/2 == 1


@pytest.mark.parametrize('field,value', [('trade','NaN'),('bid','102'),('reference','0'),('received_at',-1),('available_at',-1)])
def test_malformed_points_fail(field,value):
    with pytest.raises(ValueError): replace(points()[0], **{field:value})


def test_future_changes_never_modify_past_prediction():
    pts,c,o = setup()
    before = analyze(pts,c,150010,P,o)
    changed = (*pts[:2],replace(pts[2],trade='99'),pts[3])
    after = analyze(changed,c,150010,P,o)
    assert before['prediction'] == after['prediction']
    assert before['posthoc_label'] != after['posthoc_label']
    assert 'REFERENCE_OUTCOME_DISAGREEMENT' in after['reasons']


def test_delayed_receipt_not_available_to_prediction():
    pts,c,o = setup()
    delayed = (pts[0],replace(pts[1],received_at=160000,available_at=160000),*pts[2:])
    assert len(causal_inputs(delayed,c.market_id,150010)) == 1
    assert analyze(delayed,c,150010,P,o)['prediction']['input_hash'] != analyze(pts,c,150010,P,o)['prediction']['input_hash']


@pytest.mark.parametrize('mutation,reason', [
    ('missing','MISSING_AUTHORITATIVE_OUTCOME'),('identity','OUTCOME_BINDING_MISMATCH'),
    ('hash','OUTCOME_BINDING_MISMATCH'),('early','OUTCOME_TIME_BINDING_INVALID'),
    ('future','OUTCOME_TIME_BINDING_INVALID'),('authority','UNSUPPORTED_AUTHORITY_OR_OUTCOME')])
def test_missing_or_invalid_binding_never_ready(mutation,reason):
    pts,c,o=setup()
    if mutation=='missing': o=None
    if mutation=='identity': o=replace(o,market_id='wrong')
    if mutation=='hash': o=replace(o,contract_hash='wrong')
    if mutation=='early': o=replace(o,available_at=150010)
    if mutation=='future': o=replace(o,available_at=600001)
    if mutation=='authority': o=replace(o,authority='guessed-from-price')
    r=analyze(pts,c,150010,P,o)
    assert r['synthetic_status']=='NOT_READY' and reason in r['reasons']
    with pytest.raises(ValueError): calibration([r])


@pytest.mark.parametrize('at', [-1,300000,400000])
def test_prediction_must_precede_end(at):
    pts,c,o=setup()
    assert 'INVALID_PREDICTION_TIME' in analyze(pts,c,at,P,o)['reasons']


def test_boundary_missing_and_delay_sensitivities():
    rows=build_report()['sensitivities']
    assert rows['end_exclusive_minus_1ms']['posthoc_label']=='UP'
    assert rows['end_inclusive']['posthoc_label']=='DOWN'
    for name in ('shifted_window_1ms','missing_terminal','terminal_not_available_yet'):
        assert rows[name]['posthoc_label'] is None
    assert 'STALE_REFERENCE' in rows['zero_delay_budget']['reasons']


def test_duplicate_endpoint_and_missing_feed():
    pts,c,o=setup()
    assert 'MISSING_OR_AMBIGUOUS_ENDPOINT' in analyze((*pts,pts[2]),c,150010,P,o)['reasons']
    absent=(*pts[:2],replace(pts[2],trade=None),pts[3])
    assert 'MISSING_FEED_PRICE' in analyze(absent,c,150010,P,o)['reasons']


def test_market_identity_missing_and_cross_contamination():
    pts,c,o=setup()
    assert 'MISSING_OR_WRONG_MARKET_IDENTITY' in analyze(pts,replace(c,market_id=''),150010,P,o)['reasons']
    assert 'MISSING_OR_WRONG_MARKET_IDENTITY' in analyze((*pts,replace(pts[0],market_id='other')),c,150010,P,o)['reasons']


def test_reproducible_order_and_no_mutation():
    pts,c,o=setup(); original=repr(pts)
    a=analyze(pts,c,150010,P,o); b=analyze(tuple(reversed(pts)),c,150010,P,o)
    assert a==b and repr(pts)==original
    assert build_report()==build_report()
    json.dumps(build_report(),allow_nan=False)


def test_calibration_analytic_values():
    result=build_report()['calibration']
    good=result['constructed_frequency_match']; bad=result['fixed_overconfident_example']
    assert good['classwise_ece']==0
    assert good['multiclass_brier']==pytest.approx(.54)
    assert bad['classwise_ece']>0 and bad['multiclass_brier']>good['multiclass_brier']
    assert len(good['reliability'])==15 and not good['calibration_fitted']


def test_zero_probability_is_infinite_not_silently_clipped():
    pts,c,o=setup()
    r=analyze(pts,c,150010,dict(UP='0',DOWN='1',TIE='0'),o)
    result=calibration([r])
    assert result['log_loss'] is None and result['log_loss_status']=='INFINITE'
    assert result['zero_true_probability_count']==1


def test_input_dict_not_aliased_and_config_hash_changes():
    pts,c,o=setup(); p=dict(P)
    r=analyze(pts,c,150010,p,o); p['UP']='1'
    assert r['prediction']['probabilities']==P
    assert r['config_hash']!=analyze(pts,c,150010,P,o,end_offset_ms=0)['config_hash']
