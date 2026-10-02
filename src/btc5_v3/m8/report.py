"""Deterministic redacted research artifacts under isolated ignored runtime only."""
from pathlib import Path
from btc5_v3.config.models import StorageConfig
from btc5_v3.encoding import canonical,digest
from btc5_v3.monitoring.diagnostics import redact

LIMITATIONS='''M8 evaluates data quality, out-of-sample replay behavior,
and research robustness.
It does not demonstrate live profitability, real execution quality,
optimal parameters, or safety for live trading.
Sensitivity and ablation analyses are research diagnostics only.
They do not replace the frozen baseline.
Synthetic/replay evidence is not equivalent to live market evidence.'''


def markdown(name,data):
    import json
    # Full deterministic evidence, including exclusions and uncertainties, not just a PnL headline.
    lines=['# '+name.replace('_',' ').upper(),'','RESEARCH ONLY · SYNTHETIC · NO BASELINE RETUNING','',LIMITATIONS,'']
    if name=='data_quality':
        lines+=['## FACT — Quality coverage','','| Dataset | Total | Valid | Degraded | Invalid | Unknown | Coverage |',
                '|---|---:|---:|---:|---:|---:|---|']
        for key,value in sorted(data.items()):
            r=value['report'];c=r['counts'];lines.append(f"| {key} | {r['total_observations']} | {c['VALID']} | {c['DEGRADED']} | {c['INVALID']} | {c['UNKNOWN']} | {r['coverage']['ratio']} |")
    elif name=='validation':
        lines+=['## FACT — Frozen replay', '',f"Status: {data['status']}; repeated {data['repeat_count']} times. PASS is not a profitability criterion.",'',
                '## ESTIMATE — Conditional synthetic outcomes','','| Cohort | N | Candidates | Permissions | Fills | Completed | Simulated PnL |',
                '|---|---:|---:|---:|---:|---:|---:|']
        for key,value in data['cohorts'].items():
            r=value['summary'];lines.append(f"| {key} | {r['count']} | {r['candidate_count']} | {r['permission_count']} | {r['fill_count']} | {r['completed_count']} | {r['simulated_pnl']} |")
        lines+=['','Fees, fixed execution assumptions, regime splits and block-bootstrap confidence intervals are included in the full evidence below.']
    elif name=='robustness':
        lines+=['## FACT — Full fixed grid','','| Edge threshold | Variant | N | Candidates | Permissions | Fills |',
                '|---:|---|---:|---:|---:|---:|']
        for x in data['sensitivity']['grid']:
            r=x['summary'];lines.append(f"| {x['parameter']} | {x['variant']} | {r['count']} | {r['candidate_count']} | {r['permission_count']} | {r['fill_count']} |")
        lines+=['','## ESTIMATE — Fragility diagnostics','',canonical(data['sensitivity']['stability'])]
    else:
        for category in ('FACT','ESTIMATE','UNCERTAINTY','LIMITATION'):
            lines+=['## '+category,'',canonical(data[category]),'']
    lines+=['','## UNCERTAINTY / LIMITATION','','All results are conditional on the declared synthetic cohort. Missing evidence and insufficient samples remain explicit; no live or true OOS evidence is claimed.',
            '', '## Complete reproducible evidence','','```json',json.dumps(redact(data),ensure_ascii=False,sort_keys=True,indent=2),'```','']
    return '\n'.join(lines)


def write_reports(root,reports):
    paths=[]
    for key,stem in (('data_quality','data-quality'),('validation','validation'),('robustness','robustness'),('summary','summary')):
        safe=redact(reports[key]);text=canonical(safe)
        for ext,content in (('json',text),('md',markdown(key,safe))):
            relative=Path('runtime/v3/m8')/(stem+'.'+ext)
            path=StorageConfig(Path(root),relative).resolved_path();path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(content.encode('utf-8'));paths.append(dict(path=relative.as_posix(),hash=digest(content)))
    return paths
