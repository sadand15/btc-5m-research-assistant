"""Six fixed synthetic M6 cases; no external data or credentials."""
import argparse
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import subprocess

from btc5_v3.encoding import canonical, digest
from btc5_v3.config.models import StorageConfig, ValidatorConfig
from btc5_v3.market.normalize import raw_event
from btc5_v3.market.validation import validate_market
from btc5_v3.models.models import Prediction, TargetDefinition
from btc5_v3.edge.costs import EdgeConfig
from btc5_v3.edge.engine import evaluate_edge
from btc5_v3.decision.config import DecisionConfig
from btc5_v3.decision.policy import decide
from btc5_v3.analytics.models import ResearchObservation, ResolvedOutcome
from btc5_v3.path.models import MarketPathPoint
from btc5_v3.experiments.models import Experiment
from btc5_v3.execution.models import ExecutionConfig, ExitPolicy
from btc5_v3.storage.analytics_repository import RESEARCH_CONTRACT
from btc5_v3.storage.database import Database
from btc5_v3.storage.risk_repository import RiskRepository
from btc5_v3.risk.models import RiskConfig, HealthEvidence
from btc5_v3.risk.report import markdown

D = Decimal
START = 1704067200000
TD = START + 60000


def snapshot(exp, market, seq, at, *, expiry, bid='.48', ask='.50', quantity='1000', side='YES'):
    if side == 'NO': bid, ask = str(1-D(ask)), str(1-D(bid))
    cfg = ValidatorConfig(market, 'SYNTHETIC', 'synthetic-rule-v1')
    raw = raw_event(dict(market_id=market, source_at=at, expiry=expiry, market_type='CRYPTO_UP_DOWN',
        feed='SYNTHETIC', rule_hash=cfg.rule_hash, outcome_mapping='YES_UP',
        yes_bids=[[bid, quantity]], yes_asks=[[ask, quantity]], market_status='OPEN',
        market_status_at=at, market_status_available_at=at),
        experiment_id=exp, source='synthetic', received_at=at, sequence=seq)
    result = validate_market(raw, cfg, evaluation_at=at)
    if result.snapshot is None: raise ValueError('invalid synthetic risk snapshot')
    return result.snapshot


def candidate(exp='risk-test', market='m', *, at=TD, shares='100', ask='.50', side='YES', attempt=None, expiry=None):
    expiry = at+240000 if expiry is None else expiry
    s = snapshot(exp, market, 1, at-10, expiry=expiry, bid=str(D(ask)-D('.02')), ask=ask, side=side)
    model = digest('synthetic-risk-model')
    p = Prediction(exp, 'prediction-'+(attempt or market), market, D('.95') if side == 'YES' else D('.05'),
        'synthetic-risk-model', model, 'synthetic-features', 'b'*64, at-10, at-5,
        TargetDefinition('YES_UP', 'synthetic-rule-v1', expiry, target_source='synthetic-oracle', target_feed='SYNTHETIC'), 'none')
    ec = EdgeConfig(target_shares=D(shares)); e = evaluate_edge(s, p, ec, evaluation_at=at)
    dc = DecisionConfig(market, 'synthetic', 'SYNTHETIC', 'synthetic-rule-v1', 'YES_UP', 'synthetic-oracle', model, ec.hash,
        target_source_confirmed=True, semantic_contract_hash=digest('SYNTHETIC_ONLY'))
    d = decide(s, p, e, dc, experiment_id=exp, attempt_key='decision-'+(attempt or market), evaluation_at=at)
    return ResearchObservation.from_inputs(p, s, e, d)


def book(original, at, *, seq=2, bid='.48', ask='.50', quantity='1000'):
    s = original.data()['snapshot']; d = original.data()['decision']
    return MarketPathPoint.from_snapshot(snapshot(s['experiment_id'], s['market_id'], seq, at,
        expiry=s['expiry'], bid=bid, ask=ask, quantity=quantity, side=d['side'] or 'YES'))


def outcome(original, payout=0, available_at=None):
    s = original.data()['snapshot']
    return ResolvedOutcome(s['experiment_id'], s['market_id'], s['expiry'], available_at or s['expiry']+1000,
        D(payout), 'synthetic-settlement', 'synthetic-rule-v1', 'synthetic-settlement-v1')


def healthy(at):
    return HealthEvidence(at, at, at)


def approve(repo, run, original, **kwargs):
    at = original.data()['decision']['evaluated_at']
    return repo.evaluate(run, original, at=at, health=healthy(at), **kwargs)


def run_demo(root, code):
    root = Path(root); rows = []
    cases = ('normal', 'position-reduction', 'reservation-competition', 'partial-fill', 'daily-pause-exit', 'drawdown')
    with Database(StorageConfig(root, Path('runtime/v3/m6-demo.sqlite'))) as db:
        repo = RiskRepository(db)
        for name in cases:
            exp = 'm6-'+name+'-'+code
            repo.register(Experiment(exp, code, 'm6-synthetic-v1', 42, START, digest(RESEARCH_CONTRACT)))
            cfg = RiskConfig()
            if name == 'reservation-competition':
                cfg = replace(cfg, starting_capital=D(100), max_position_fraction=D(1), max_total_open_exposure_fraction=D(1))
            if name == 'drawdown':
                cfg = replace(cfg, max_position_notional=D(300), max_position_fraction=D(1), max_market_exposure=D(500),
                              max_daily_simulated_loss=D(1000))
            run = repo.create_run(exp, code, cfg, TD)
            original = candidate(exp, ask='.60' if name == 'daily-pause-exit' else '.50', shares='180' if name == 'position-reduction' else '80' if name == 'reservation-competition' else '300' if name == 'drawdown' else '100')
            policy = ExitPolicy('FIXED_TTE', tte_ms=60000) if name == 'daily-pause-exit' else ExitPolicy()
            a = approve(repo, run, original, policy=policy); rid = a['risk_decision']['risk_decision_id']; cutoff = TD
            if name == 'reservation-competition':
                b = approve(repo, run, candidate(exp, 'second', shares='50'))
                assert D(b['risk_decision']['approved_shares']) == 20
            else:
                books = [book(original, TD+250, bid='.58' if name == 'daily-pause-exit' else '.48', ask='.60' if name == 'daily-pause-exit' else '.50', quantity='60' if name == 'partial-fill' else '1000')]
                cutoff = TD+250
                repo.execute(run, rid, books, cutoff=cutoff)
                if name == 'daily-pause-exit':
                    # A separate held position already exists before the first loss.
                    other = candidate(exp, 'existing', at=cutoff, ask='.60')
                    other_a = approve(repo, run, other, policy=ExitPolicy('FIXED_TTE', tte_ms=60000))
                    other_rid = other_a['risk_decision']['risk_decision_id']
                    other_books = [book(other, TD+500, bid='.58', ask='.60')]
                    repo.execute(run, other_rid, other_books, cutoff=TD+500)
                    books += [book(original, TD+180250, seq=3, bid='.10', ask='.12')]
                    cutoff = TD+180250
                    repo.execute(run, rid, books, cutoff=cutoff)
                    blocked = approve(repo, run, candidate(exp, 'blocked', at=cutoff))
                    assert 'DAILY_LOSS_LIMIT' in blocked['risk_decision']['all_reasons']
                    other_books += [book(other, TD+180500, seq=3, bid='.40', ask='.42')]
                    cutoff = TD+180500
                    result = repo.execute(run, other_rid, other_books, cutoff=cutoff)
                    assert result['execution']['accounting']['completed']
                elif name == 'drawdown':
                    cutoff = original.data()['snapshot']['expiry']+1000
                    repo.execute(run, rid, books, outcome(original), cutoff=cutoff)
                    blocked = approve(repo, run, candidate(exp, 'blocked', at=cutoff))
                    assert 'MAX_DRAWDOWN_REACHED' in blocked['risk_decision']['all_reasons']
            r = repo.report(run, at=cutoff)
            rows.append(dict(case=name, report=r))
    result = dict(mode='M6_SYNTHETIC_ONLY', code_git=code, cases=rows)
    StorageConfig(root, Path('runtime/v3/m6-report.json')).resolved_path().write_bytes(canonical(result).encode())
    content = '# M6 fixed synthetic cases\n\n'+'\n\n'.join('# '+r['case']+'\n\n'+markdown(r['report']) for r in rows)
    StorageConfig(root, Path('runtime/v3/m6-report.md')).resolved_path().write_bytes(content.encode())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=Path.cwd()); args = parser.parse_args()
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=args.project_root, text=True).strip():
        raise ValueError('clean committed risk source required')
    code = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=args.project_root, text=True).strip()
    result = run_demo(args.project_root, code)
    print(canonical(dict(mode=result['mode'], cases=len(result['cases']), artifacts=['runtime/v3/m6-report.json', 'runtime/v3/m6-report.md'])))


if __name__ == '__main__': main()
