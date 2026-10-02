"""Bounded composition of quality, baseline validation and development diagnostics."""
from dataclasses import asdict
from decimal import Decimal,localcontext
import re
from btc5_v3.encoding import digest,canonical,timestamp
from btc5_v3.edge.numeric import CONTEXT
from btc5_v3.m8.models import Baseline,time_split,normalized
from btc5_v3.data_quality.checks import quality_report,QUALITY_HASH
from btc5_v3.validation.replay import replay,validate
from btc5_v3.validation.metrics import grouped,metrics
from btc5_v3.robustness.sensitivity import sensitivity
from btc5_v3.robustness.ablation import ablation
from btc5_v3.robustness.bootstrap import bootstrap
from btc5_v3.robustness.dependence import dependence,drift,DIMENSIONS,label
from btc5_v3.monitoring.diagnostics import redact


def provenance(dataset,baseline,code_git,branch,cutoff,analysis,seed=None):
    return dict(git_sha=code_git,branch=branch,dataset_id=dataset.manifest.dataset_id,
                dataset_hash=dataset.manifest.payload_hash,manifest_hash=dataset.manifest.hash,
                dataset_role=dataset.manifest.role,dataset_time_range=[dataset.manifest.time_start,dataset.manifest.time_end],
                evidence_mode=dataset.manifest.evidence_mode,quality_contract_hash=QUALITY_HASH,
                baseline_source_git=baseline.source_git,baseline_config_hash=baseline.hash,
                risk_config_hash=baseline.risk.hash,execution_config_hash=baseline.execution.hash,
                analysis_type=analysis,analysis_parameters=dict(version='m8-research-v1',cutoff=cutoff),
                random_seed=seed,generated_at=cutoff,generated_at_semantics='LOGICAL_AS_OF_UTC_MS')


def uncertainty(rows,seed):
    return {m:bootstrap(rows,m,seed=seed) for m in ('mean_edge','fill_rate','reject_rate','brier','mean_return')}


def run_research(development,validation,*,cutoff,code_git,branch='UNKNOWN',seed=42):
    if not isinstance(code_git,str) or not re.fullmatch('[0-9a-f]{40}',code_git):raise ValueError('actual analysis Git identity required')
    if not timestamp(cutoff):raise ValueError('invalid cutoff')
    time_split(development,validation)
    with localcontext(CONTEXT):
        baseline=Baseline();source_hash=baseline.hash
        dq={d.manifest.dataset_id:dict(provenance=provenance(d,baseline,code_git,branch,cutoff,'DATA_QUALITY'),
                                      report=quality_report(d,cutoff)) for d in (development,validation)}
        val=validate(validation,cutoff=cutoff,code_git=code_git)
        val['provenance']=provenance(validation,baseline,code_git,branch,cutoff,'VALIDATION',seed)
        dev=replay(development,baseline,cutoff=cutoff,code_git=code_git)
        dev_all=replay(development,baseline,cutoff=cutoff,code_git=code_git,cohort='ALL_ELIGIBLE')
        for result in val['cohorts'].values():
            result['regimes']={dim:grouped(result['rows'],baseline,dim) for dim in DIMENSIONS}
            result['uncertainty']=uncertainty(result['rows'],seed)
        valrows=val['cohorts']['QUALITY_PASSED']['rows']
        robust=dict(provenance=provenance(development,baseline,code_git,branch,cutoff,'ROBUSTNESS',seed),
             sensitivity=sensitivity(development,cutoff=cutoff,code_git=code_git),
             ablation=ablation(development,cutoff=cutoff,code_git=code_git),
             uncertainty=uncertainty(dev['rows'],seed),feature_dependence=dependence(dev['rows']),
             calibration_drift=drift(dev['rows'],valrows,baseline,seed=seed),
             validation_comparison_provenance=provenance(validation,baseline,code_git,branch,cutoff,'FIXED_CALIBRATION_COMPARISON',seed),
             quality_impact=dict(all_eligible=dev_all['summary'],quality_passed=dev['summary']))
        matrix=[]
        sources=[(development,'QUALITY_PASSED','BASELINE',dev['rows']),
                 (development,'ALL_ELIGIBLE','BASELINE',dev_all['rows'])]
        sources += [(validation,k,'BASELINE',v['rows']) for k,v in val['cohorts'].items()]
        sources += [(development,'QUALITY_PASSED',x['variant'],x['rows']) for x in robust['sensitivity']['grid'] if x['variant']!='BASELINE']
        sources += [(development,'QUALITY_PASSED','WITHOUT_ABSOLUTE_SPREAD_GATE',robust['ablation']['variant']['rows'])]
        for ds,cohort,variant,rows in sources:
            for dim in ('spread','liquidity','tte','probability','side'):
                for key in sorted({label(r,dim) for r in rows}):
                    sub=[r for r in rows if label(r,dim)==key]
                    matrix.append(dict(dataset_id=ds.manifest.dataset_id,dataset_hash=ds.manifest.payload_hash,
                       role=ds.manifest.role,quality_cohort=cohort,variant=variant,regime_dimension=dim,regime=key,
                       metrics=metrics(sub,baseline),uncertainty=bootstrap(sub,'mean_edge',seed=seed)))
        assert baseline.hash==source_hash
        summary=dict(provenance=[provenance(d,baseline,code_git,branch,cutoff,'M8_SUMMARY',seed) for d in (development,validation)],
              FACT=dict(validation_status=val['status'],replay_repeat_count=2,baseline_unchanged=True,
                        quality_counts={k:v['report']['counts'] for k,v in dq.items()}),
              ESTIMATE=dict(calibration_drift=robust['calibration_drift']['overall'],
                            sensitivity_shape=robust['sensitivity']['stability']),
              UNCERTAINTY=robust['uncertainty'],LIMITATION=['SYNTHETIC_ONLY_NO_TRUE_OOS_EVIDENCE','NO_LIVE_EXECUTION',
                'NO_PROFITABILITY_CLAIM','NO_PARAMETER_SELECTION','FIXED_CLUSTER_BOOTSTRAP_ASSUMPTIONS',
                'QUALITY_FILTER_CHANGES_PORTFOLIO_COHORT','NO_CAUSAL_FEATURE_IMPORTANCE'],
              evidence_conclusion='NO_ROBUST_EVIDENCE_OF_LIVE_EDGE',research_matrix=matrix,
              baseline_config=baseline.configuration())
        return normalized(redact(dict(data_quality=dq,validation=val,robustness=robust,summary=summary)))
