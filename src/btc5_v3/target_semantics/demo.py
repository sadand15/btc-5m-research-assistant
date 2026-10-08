"""Reproducible synthetic demo; output only, no input datasets or network."""
import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path

from .lab import Contract, Outcome, Point, analyze, calibration, digest

P = {'UP': '0.6', 'DOWN': '0.3', 'TIE': '0.1'}


def points(market='synthetic-cycle'):
    return (Point(market, 0, 0, 0, '100', '99', '101', '100'),
            Point(market, 150000, 150005, 150010, '100', '99', '101', '100'),
            Point(market, 299999, 300005, 300010, '101', '97', '101', '100'),
            Point(market, 300000, 300005, 300010, '99', '97', '99', '99'))


def bound(contract, side):
    return Outcome(contract.market_id, digest(asdict(contract)), side, 301000)


def build_report():
    pts = points()
    comparisons = {}
    for feed, side in (('trade', 'UP'), ('mid', 'DOWN'), ('reference', 'TIE')):
        c = Contract('synthetic-cycle', 0, 300000, feed)
        comparisons[feed] = analyze(pts, c, 150010, P, bound(c, side))
    c = Contract('synthetic-cycle', 0, 300000, 'trade')
    authority = bound(c, 'UP')
    sensitivities = {
        'end_exclusive_minus_1ms': analyze(pts, c, 150010, P, authority),
        'end_inclusive': analyze(pts, c, 150010, P, authority, end_offset_ms=0),
        'shifted_window_1ms': analyze(pts, replace(c, start=1, end=300001), 150010, P, authority),
        'zero_delay_budget': analyze(pts, c, 150010, P, authority, max_delay_ms=0),
        'missing_terminal': analyze(pts[:2], c, 150010, P, authority),
        'terminal_not_available_yet': analyze(pts, c, 150010, P, authority, analysis_at=300000),
        'no_authority': analyze(pts, c, 150010, P),
        'wrong_market_outcome': analyze(pts, c, 150010, P, replace(authority, market_id='other')),
        'outcome_known_before_prediction': analyze(pts, c, 150010, P, replace(authority, available_at=100000)),
    }
    calibrated = []
    miscalibrated = []
    for i, side in enumerate(['UP']*6 + ['DOWN']*3 + ['TIE']):
        mid = f'synthetic-calibration-{i}'
        cc = Contract(mid, 0, 300000, 'trade')
        pp = points(mid)
        pp = (*pp[:2], replace(pp[2], trade={'UP': '101', 'DOWN': '99', 'TIE': '100'}[side]), pp[3])
        calibrated.append(analyze(pp, cc, 150010, P, bound(cc, side)))
        miscalibrated.append(analyze(pp, cc, 150010,
            {'UP': '0.9', 'DOWN': '0.05', 'TIE': '0.05'}, bound(cc, side)))
    result = dict(schema_version=1, origin='SYNTHETIC_TEST', readiness='NOT_READY',
        real_compatibility='TARGET_MISMATCH', study_started=False, module='M9.2',
        comparisons=comparisons, sensitivities=sensitivities,
        calibration={'constructed_frequency_match': calibration(calibrated),
                     'fixed_overconfident_example': calibration(miscalibrated)},
        limitations=['No fitted model; probabilities and outcomes predeclared synthetic fixtures',
                     'Posthoc labels are not authoritative venue outcomes',
                     'No real-market validation, execution or parameter optimization'])
    result['report_hash'] = digest(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.project_root.resolve()
    report = build_report()
    parent = root
    for part in ('runtime', 'm92-target-semantics'):
        parent = parent / part
        if parent.is_symlink() or (hasattr(parent, 'is_junction') and parent.is_junction()):
            raise ValueError('output aliases forbidden')
        parent.mkdir(exist_ok=True)
    output = parent / (report['report_hash'] + '.json')
    encoded = (json.dumps(report, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()
    if output.exists():
        if output.is_symlink() or output.read_bytes() != encoded:
            raise ValueError('existing output conflict')
    else:
        with output.open('xb') as stream:
            stream.write(encoded)
    print(json.dumps(dict(origin='SYNTHETIC_TEST', readiness='NOT_READY',
                         report_hash=report['report_hash'], output=str(output))))


if __name__ == '__main__':
    main()
