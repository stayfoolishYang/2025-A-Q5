"""Freeze the segment-only extension on the unchanged 356 existing scene seeds."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from recovered_benchmark import digest, source_hashes


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--sim-root', type=Path, default=Path('G:/QQ/jammers_linux'))
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    sources = source_hashes(a.sim_root)
    git_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    plans = {}
    for cohort in ('development100', 'holdout256'):
        parent = a.root/cohort
        audit = json.loads((parent/'NCCP_AUDIT.json').read_text(encoding='utf-8'))
        assert audit['performance_conclusion_allowed'] is True
        manifest = json.loads((parent/'manifest.json').read_text(encoding='utf-8'))
        configs = {}
        for problem in (3,4):
            original = manifest['configs'][str(problem)][0]
            configs[str(problem)] = [dict(original, name=original['name']+'_segment_entry', clearance_point='segment_entry')]
        new = copy.deepcopy(manifest)
        new.update(experiment_id='segment_entry_extension_20260911', configs=configs,
                   config_hashes={key:{c['name']:digest(c) for c in group} for key,group in configs.items()},
                   source_hashes=sources, git_commit=git_commit,
                   parent_cohort=str(parent),
                   parent_manifest_sha256=hashlib.sha256((parent/'manifest.json').read_bytes()).hexdigest(),
                   prepared_at_utc=datetime.now(timezone.utc).isoformat(),
                   evidence_scope='Segment extension after viewing NCCP results; uses unchanged existing scenes. The 256 set is reused, NOT a fresh independent holdout for this new policy.',
                   baseline_requirement='Historical MEC and NCCP runs stay in their original cohort; exact amendment replay establishes unchanged actions. Only segment rows are newly generated here.',
                   algorithm_changes='Only clearance_point=segment_entry versus original configurations; unchanged coverage, diagnostic scores and seeds.',
                   formal_tests=0)
        new['plan_hash'] = digest({key:new[key] for key in ('seeds','configs','source_hashes','parent_manifest_sha256')})
        output = a.output/cohort
        output.mkdir()
        shutil.copytree(parent/'scenes', output/'scenes')
        (output/'manifest.json').write_text(json.dumps(new,indent=2,ensure_ascii=False),encoding='utf-8')
        plans[cohort] = dict(planned_runs=len(new['seeds'])*2, plan_hash=new['plan_hash'],
                             manifest_sha256=hashlib.sha256((output/'manifest.json').read_bytes()).hexdigest())
    assert source_hashes(a.sim_root)==sources
    (a.output/'PREPARED.json').write_text(json.dumps(dict(cohorts=plans,formal_runs=0),indent=2),encoding='utf-8')
    print(json.dumps(plans,indent=2))


if __name__=='__main__':
    main()
