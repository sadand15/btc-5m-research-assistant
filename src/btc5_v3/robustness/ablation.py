"""One explicit supported offline gate ablation. Baseline stays immutable."""
from dataclasses import replace
from decimal import Decimal as D
from btc5_v3.m8.models import Baseline
from btc5_v3.validation.replay import replay


def ablation(dataset,*,cutoff,code_git):
    if dataset.manifest.role!='DEVELOPMENT':raise ValueError('ablation requires development role')
    baseline=Baseline();variant=replace(baseline,max_spread=D(1),variant='WITHOUT_ABSOLUTE_SPREAD_GATE')
    a=replay(dataset,baseline,cutoff=cutoff,code_git=code_git)
    b=replay(dataset,variant,cutoff=cutoff,code_git=code_git,research_variant=True)
    keys=('candidate_count','permission_count','fill_count','risk_trigger_count')
    return dict(component='M3_ABSOLUTE_SPREAD_RESTRICTION',baseline_hash=baseline.hash,variant_hash=variant.hash,
                baseline=a,variant=b,delta={k:b['summary'][k]-a['summary'][k] for k in keys},
                calibration_delta=None if a['summary']['calibration']['brier_payout'] is None else D(b['summary']['calibration']['brier_payout'])-D(a['summary']['calibration']['brier_payout']),
                uncertainty='DESCRIPTIVE_PAIRED_COHORT; NO_CAUSAL_COMPONENT_IMPORTANCE',
                interpretation='Variant showed different results in this research analysis. No promotion.')
