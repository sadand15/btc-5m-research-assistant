"""Synthetic-only end-to-end demo. Never opens a real source or existing study."""
import argparse
from dataclasses import asdict
from pathlib import Path
import tempfile

from btc5_v3.encoding import digest, canonical
from btc5_v3.config.models import StorageConfig
from btc5_v3.m8.models import Baseline
from btc5_v3.prospective.identity import APPROVED
from btc5_v3.prospective.store import read
from btc5_v3.research_adapter.binding_dataset import load_binding_synthetic
from .schema import BindingConfig, definition
from .store import BindingStudy, BindingWriter
from .collector import Collector

RULES = 'Synthetic fixture only: authoritative mock UP/DOWN/SPLIT; not real venue semantics.'


class Clock:
    def __init__(self, at=300000): self.at = at
    def __call__(self): return self.at


def config():
    b = Baseline()
    return BindingConfig(b.model_version,b.model_hash,b.feature_version,b.feature_hash,
        b.calibration_version,digest({'fixed_probability':'.75'}),'synthetic-rule-v1',digest(RULES),
        'synthetic','synthetic-oracle','SYNTHETIC','BTCUSD','BTC_USD_REFERENCE',
        'synthetic-settlement','synthetic-settlement-v1',2000,2000,2000)


def proof():
    return dict(baseline_git_sha=APPROVED,collector_git_sha='a'*40,branch='synthetic-m91',
                baseline_config_hash=Baseline().hash)


class MockPredictor:
    def __init__(self, binding): self.binding_hash=binding.hash; self.calls=0
    def predict(self, inputs):
        self.calls += 1
        return {'p_up':'.75','p_down':'.25'}


class MockSource:
    def __init__(self, clock): self.clock=clock; self.settled=True
    def state(self):
        return dict(market_id='mock-market',market_start=300000,market_end=600000,
            source_at=self.clock(),source_health='HEALTHY',status='OPEN',mapping={'YES':'UP','NO':'DOWN'},
            rule_hash='synthetic-rule-v1',definition=dict(rules=RULES,feed='SYNTHETIC',
                target_source='synthetic-oracle',symbol='BTCUSD',price_unit='COLLATERAL_PER_SHARE',
                quantity_unit='SHARES',condition_id='mock-condition',yes_asset_id='mock-yes',no_asset_id='mock-no',
                opening_reference_price='50000',opening_reference_at=300000,opening_reference_available_at=300000,
                resolution_semantics='AUTHORITATIVE_BINARY_OR_SPLIT',tie_policy='AUTHORITATIVE_SPLIT_HALF'))
    def reference(self):
        return dict(price='50000',source='synthetic-oracle',source_at=self.clock(),source_health='HEALTHY',
                    symbol='BTCUSD',feed='SYNTHETIC',semantics='BTC_USD_REFERENCE')
    def book(self):
        return dict(market_id='mock-market',source_at=self.clock(),rule_hash='synthetic-rule-v1',
                    yes_bids=[['.48','1000']],yes_asks=[['.50','1000']])
    def settlement(self, market):
        if self.clock() < 600000 or not self.settled: return None
        return dict(market_id=market,outcome='UP',status='RESOLVED',settled_at=600000,
                    rule_hash='synthetic-rule-v1',source='synthetic-settlement',settlement_version='synthetic-settlement-v1')


def setup(root, name='synthetic-m91'):
    cfg=config(); study=BindingStudy(root,name)
    study.create(definition(name,name+'-dataset',1,300000,600000,900000,proof(),cfg))
    study.arm(2,proof())
    clock=Clock(); return study,clock,MockSource(clock),MockPredictor(cfg)


def complete(root):
    study,clock,source,predictor=setup(root)
    with BindingWriter(study,proof,clock) as writer:
        collector=Collector(writer,predictor)
        collector.step(source)
        clock.at+=1000; collector.step(source)
    # Crash-style restart (journal was committed but not explicitly finalized).
    with BindingWriter(study,proof,clock) as writer:
        collector=Collector(writer,predictor)
        collector.predict('mock-market')
        clock.at=601000; collector.step(source)
        clock.at=900000; sealed=writer.seal()
    result=load_binding_synthetic(study,now=clock(),expected_root=sealed['dataset_root_hash'])
    assert predictor.calls==1 and result.readiness=='REPLAY_READY'
    return study,result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',type=Path,required=True)
    args=parser.parse_args()
    parent=StorageConfig(args.project_root,Path('runtime/v3/m91-demo')).resolved_path()
    parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='synthetic-',dir=parent) as folder:
        study,result=complete(folder)
        print(canonical(dict(origin=result.origin,readiness=result.readiness,real_study_started=False,
                             sealed=study.verify(require_sealed=True)['sealed'],
                             records=len(result.dataset.records()),duplicate_predictions=0)))


if __name__=='__main__': main()
