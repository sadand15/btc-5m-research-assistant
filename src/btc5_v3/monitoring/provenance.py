import subprocess


def viewer_repository(root):
    try:
        def git(*args):
            return subprocess.check_output(['git',*args],cwd=root,text=True,stderr=subprocess.DEVNULL,timeout=5).strip()
        return dict(git_sha=git('rev-parse','HEAD'),branch=git('branch','--show-current') or 'UNKNOWN',
                    working_tree='DIRTY' if git('status','--porcelain') else 'CLEAN')
    except (OSError,subprocess.SubprocessError):
        return dict(git_sha='UNKNOWN',branch='UNKNOWN',working_tree='UNKNOWN')


def provenance(run, experiment, originals, schema, as_of, viewer):
    def values(path):
        result=set()
        for original in originals:
            value=original
            for key in path: value=value.get(key,{}) if isinstance(value,dict) else {}
            if isinstance(value,str): result.add(value)
        return sorted(result) or ['UNKNOWN']
    return dict(source_git_sha=run.get('code_git','UNKNOWN'),source_branch='UNKNOWN',schema_version=schema,
        m1_versions=values(('snapshot','validator_version')),m2_versions=values(('edge','edge_version')),
        m3_versions=values(('decision','decision_version')),m4_versions=['UNKNOWN'],m4_5_versions=['UNKNOWN'],
        m5_versions=['UNKNOWN'],m6_version=run.get('version','UNKNOWN'),
        m7_version='monitoring-v1',risk_config_hash=run.get('config_hash','UNKNOWN'),
        experiment_id=run.get('experiment_id','UNKNOWN'),source_dataset=experiment.get('data_version','UNKNOWN'),
        evidence_mode='SYNTHETIC',view_mode='AS-OF REPLAY',generated_at=as_of,
        generated_at_semantics='EXPLICIT_LOGICAL_AS_OF_NOT_WALL_CLOCK',viewer_repository=viewer,
        calibration_versions=values(('prediction','calibration_version')),
        m4_analysis='NOT RECORDED IN M6 ARCHIVE',m4_5_analysis='NOT RECORDED IN M6 ARCHIVE')
