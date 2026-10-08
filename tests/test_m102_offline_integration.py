"""End-to-end synthetic integration; no real archive or service is read."""
from copy import deepcopy
import json
from html.parser import HTMLParser

import pytest

from btc5_v3.research_adapter.target_semantics import adapt_offline, seal_offline
from btc5_v3.research_adapter.offline_demo import fixtures, render, run
from btc5_v3.target_semantics.lab import digest


def adapt(records):
    e=seal_offline(records)
    return adapt_offline(e,expected_root=e['root_hash'])


def test_complete_input_adapter_scores_html(tmp_path):
    report,path=run(tmp_path)
    assert report['status']=='SYNTHETIC_READY'
    assert report['real_status']=='REAL_DATA_NOT_READY'
    assert report['real_compatibility']=='TARGET_MISMATCH'
    assert report['accepted']==12 and report['rejected']==8
    assert len(report['calibration'])==3
    trade=next(v for k,v in report['calibration'].items() if k.startswith('trade:'))
    assert trade['n']==10 and trade['multiclass_brier']==pytest.approx(.54)
    assert trade['classwise_ece']==0
    assert all(r['probabilities']['TIE']=='0.1' for r in report['rows'] if r['scores_included'])
    html=path.read_text(encoding='utf-8')
    assert 'P(TIE)' in html and 'REAL_DATA_NOT_READY' in html and 'rejected-authority' in html
    assert '<script' not in html and '<iframe' not in html
    parser=HTMLParser(); parser.feed(html); parser.close()


def test_deterministic_serialized_replay_and_idempotence(tmp_path):
    a,path=run(tmp_path); before={p.name:p.read_bytes() for p in path.parent.iterdir()}
    e=json.loads((path.parent/'input.json').read_text())
    assert adapt_offline(e,expected_root=e['root_hash'])==a
    b,p2=run(tmp_path)
    assert a==b and p2==path
    assert before=={p.name:p.read_bytes() for p in path.parent.iterdir()}


@pytest.mark.parametrize('change', ['origin','role','mode','unsealed','tampered','root'])
def test_archive_gate_cannot_be_bypassed(change):
    e=seal_offline(fixtures()); root=e['root_hash']
    if change=='origin': e['payload']['origin']='REALTIME'
    if change=='role': e['payload']['role']='BLIND'
    if change=='mode': e['payload']['evidence_mode']='PROSPECTIVE'
    if change=='unsealed': e['status']='OPEN'
    if change=='tampered': e['payload']['records'][0]['prediction']['probabilities']['UP']='0.7'
    if change=='root': root='0'*64
    r=adapt_offline(e,expected_root=root)
    assert r['status']=='NOT_READY' and r['calibration']=={} and not r['verified']


def test_origin_relabel_even_rehashed_rejected():
    e=seal_offline(fixtures()); e['payload']['origin']='REALTIME'
    from btc5_v3.encoding import digest as root_digest
    e['root_hash']=root_digest(e['payload'])
    assert adapt_offline(e,expected_root=e['root_hash'])['status']=='NOT_READY'


@pytest.mark.parametrize('field', ['market','outcome','generation','quality','simplex','stale','receipt','reference'])
def test_bad_data_not_scored(field):
    r=fixtures()[0]
    if field=='market': r['contract']['market_id']=''
    if field=='outcome': r['outcome']=None
    if field=='generation': del r['prediction']['generated_at']
    if field=='quality': r['quality']='UNKNOWN'
    if field=='simplex': r['prediction']['probabilities'].pop('TIE')
    if field=='stale': r['points'][2]['available_at']=400000
    if field=='receipt': r['points'][0]['received_at']=-1
    if field=='reference': r['points'][2]['trade']=None
    result=adapt([r])
    assert result['status']=='NOT_READY' and result['accepted']==0
    assert result['calibration']=={} and result['rows'][0]['reasons']


def test_future_changes_do_not_change_prediction_and_cannot_replace_authority():
    a=fixtures()[0]; b=deepcopy(a)
    b['points'][2]['trade']='90'
    ra=adapt([a])['rows'][0]; rb=adapt([b])['rows'][0]
    assert ra['prediction']==rb['prediction']
    assert rb['status']=='REJECTED' and 'REFERENCE_OUTCOME_DISAGREEMENT' in rb['reasons']


def test_future_point_cannot_be_in_input_hash():
    r=fixtures()[0]
    r['prediction']['input_hash']=digest(r['points'])
    result=adapt([r])
    assert 'PREDICTION_INPUT_BINDING_MISMATCH' in result['rows'][0]['reasons']


def test_duplicate_id_and_empty_envelopes():
    r=fixtures()[0]
    for rows in ([],[r,r]):
        result=adapt(rows)
        assert not result['verified'] and result['status']=='NOT_READY'


def test_source_not_mutated():
    e=seal_offline(fixtures()); before=deepcopy(e)
    adapt_offline(e,expected_root=e['root_hash'])
    assert e==before


def test_html_escapes_untrusted_labels():
    report=adapt(fixtures()); report['rows'][0]['id']='<img src=x onerror=alert(1)>'
    html=render(report)
    assert '<img' not in html and '&lt;img' in html


def test_output_conflict_never_overwritten(tmp_path):
    _,path=run(tmp_path); path.write_text('changed',encoding='utf-8')
    with pytest.raises(ValueError,match='output conflict'): run(tmp_path)
    assert path.read_text()=='changed'
