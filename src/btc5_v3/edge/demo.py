"""Synthetic edge arithmetic only; no venue calls, observations or actual trading."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess

from btc5_v3.config.models import StorageConfig, ValidatorConfig
from btc5_v3.encoding import canonical
from btc5_v3.experiments.models import Experiment
from btc5_v3.models.models import Prediction, TargetDefinition
from btc5_v3.edge.costs import EdgeConfig
from btc5_v3.storage.database import Database
from btc5_v3.storage.repository import Repository
from btc5_v3.storage.edge_repository import EdgeRepository


def run_demo(project_root, git_commit):
    cfg = ValidatorConfig(market_id='m2-synthetic', feed='SYNTHETIC', rule_hash='m2-rule-v1')
    experiment = Experiment('m2-demo-' + git_commit, git_commit, 'synthetic-m2-v1', 42, 900, cfg.hash)
    payload = dict(market_id=cfg.market_id, source_at=1000, expiry=301000, market_type='CRYPTO_UP_DOWN',
                   feed=cfg.feed, rule_hash=cfg.rule_hash, outcome_mapping='YES_UP',
                   yes_bids=[['.59', '10']], yes_asks=[['.61', '10']])
    with Database(StorageConfig(project_root=Path(project_root), database=Path('runtime/v3/m2-demo.sqlite'))) as db:
        market = Repository(db, cfg)
        market.register(experiment)
        snapshot = market.ingest(payload, experiment_id=experiment.id, source='synthetic', received_at=4000,
                                 sequence=1, evaluation_at=4000).snapshot
        repo = EdgeRepository(market)
        results = []
        for probability, key in (('.70', 'positive-example'), ('.60', 'no-trade-example')):
            prediction = Prediction(experiment.id, key, cfg.market_id, probability, 'synthetic-v1', 'a'*64,
                                    'synthetic-features-v1', 'b'*64, 4000, 4500,
                                    TargetDefinition('YES_UP', cfg.rule_hash, 301000), 'none')
            result = repo.evaluate_and_store(snapshot.snapshot_id, prediction, EdgeConfig(), evaluation_at=5000)
            assert repo.get_edge(result.edge_id) == result
            results.append(asdict(result))
    return dict(mode='SYNTHETIC_EDGE_MATH_ONLY', experiment_id=experiment.id, evaluations=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=Path.cwd())
    args = parser.parse_args()
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=args.project_root, text=True).strip():
        raise ValueError('Commit changes before running a versioned demo')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=args.project_root, text=True).strip()
    print(json.dumps(json.loads(canonical(run_demo(args.project_root, commit))), indent=2))


if __name__ == '__main__':
    main()
