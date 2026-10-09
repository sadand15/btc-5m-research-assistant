"""Reproduction gate rejects dirty checkouts and altered golden artifacts."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('m102_verifier',ROOT/'scripts/verify_m102_reproduction.py')
verifier=importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def test_dirty_checkout_refused_before_generation(monkeypatch,tmp_path):
    monkeypatch.setattr(verifier.subprocess,'check_output',lambda *a,**k:b' M modified.py')
    with pytest.raises(ValueError,match='CLEAN_CHECKOUT_REQUIRED'): verifier.verify(tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('broken', ['hash','metric','rejection'])
def test_frozen_expectations_are_not_regenerated(monkeypatch,tmp_path,broken):
    monkeypatch.setattr(verifier.subprocess,'check_output',lambda *a,**k:b'')
    e=json.loads((ROOT/'tests/fixtures/m102_reproduction.json').read_text())
    if broken=='hash': e['files']['report.html']='0'*64
    if broken=='metric': e['calibration']={}
    if broken=='rejection': e['rejections']={}
    destination=tmp_path/'tests/fixtures/m102_reproduction.json'
    destination.parent.mkdir(parents=True)
    original=json.dumps(e); destination.write_text(original)
    with pytest.raises(ValueError,match='MISMATCH'): verifier.verify(tmp_path)
    assert destination.read_text()==original
