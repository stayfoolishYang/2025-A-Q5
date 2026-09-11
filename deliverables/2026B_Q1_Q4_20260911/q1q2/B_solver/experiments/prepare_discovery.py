"""Freeze one Q4 2x2 discovery experiment before running any candidate."""
import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import platform
import subprocess
import sys

import numpy as np

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from recovered_benchmark import digest, frozen_seeds, save, source_hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sim-root', type=Path, default=Path('G:/QQ/jammers_linux'))
    args = parser.parse_args()
    out, sim = args.output.resolve(), args.sim_root.resolve()
    if out.exists():
        raise FileExistsError('Preserve existing experiments; choose a new output')
    sys.path.insert(0, str(sim))
    from scenario_io import generate_document
    previous = json.loads((BASE/'results/recovered/nccp_20260911_summary/evidence/PLAN.json').read_text(encoding='utf-8'))
    old = {record['seed_hex'] for record in frozen_seeds()}
    old.update(record['seed_hex'] for record in previous['shared_seed_plan']['holdout256'])
    prefix = '2026B-discovery-scheduling-20260911:'
    seeds = [dict(seed=i, seed_hex=hashlib.sha256((prefix+str(i)).encode()).hexdigest(),
                  family='sha256_discovery_design', derivation_index=i) for i in range(160)]
    assert len({s['seed_hex'] for s in seeds}) == 160
    assert not old.intersection(s['seed_hex'] for s in seeds)
    configs = [json.loads((BASE/'configs'/('q4_p4_diag_v1_grid_v1'+suffix+'.yaml')).read_text())
               for suffix in ('', '_refresh', '_unknown', '_refresh_unknown')]
    allowed = {'name', 'discovery_route', 'discovery_channels'}
    baseline = {k:v for k,v in configs[0].items() if k not in allowed}
    assert all({k:v for k,v in c.items() if k not in allowed} == baseline for c in configs)
    assert all(c.get('clearance_point', 'mec_center') == 'mec_center' for c in configs)
    hashes = source_hashes(sim)
    assert all(hashes['engine/'+n] == previous['source_hashes']['engine/'+n]
               for n in ('engine.py', 'scenario_io.py', 'recovered_generator.py'))
    blas = io.StringIO()
    with contextlib.redirect_stdout(blas):
        np.show_config()
    common = dict(schema='recovered-benchmark-v1', configs={'4':configs}, grid_version='grid_v1',
                  source_hashes=hashes, simulator_root=str(sim), python=sys.version,
                  executable=sys.executable, numpy=np.__version__, blas=blas.getvalue(),
                  platform=platform.platform(), evidence='recovered_practice_engine_local',
                  git_commit=subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip(),
                  limits=dict(real_s=1200, virtual_s=360000), formal_tests=0,
                  algorithm_changes='Only remaining-route refresh and/or channel-order permutation; MEC, all 45 nodes and all outstanding channel scans retained.',
                  seed_design='New deterministic designed seeds; not IID or official cases.',
                  prepared_at_utc=datetime.now(timezone.utc).isoformat())
    manifests, scenes = {}, {}
    for cohort, subset in (('development32', seeds[:32]), ('holdout128', seeds[32:])):
        records = [dict(s, seed=i) for i,s in enumerate(subset)]
        documents = {f'q4_{s["seed"]:04d}.json':generate_document(seed_hex=s['seed_hex'],problem=4,format='native') for s in records}
        manifest = dict(common, cohort=cohort, seeds=records, scene_hashes={n:digest(d) for n,d in documents.items()})
        manifest['plan_hash'] = digest({k:manifest[k] for k in ('seeds','configs','source_hashes','scene_hashes')})
        manifests[cohort], scenes[cohort] = manifest, documents
    assert source_hashes(sim) == hashes
    out.mkdir(parents=True)
    plan = dict(schema='q4-discovery-2x2-v1', prefix=prefix, seeds=seeds, configs=configs,
                cohorts={c:dict(n=len(m['seeds']), runs=4*len(m['seeds']), plan_hash=m['plan_hash']) for c,m in manifests.items()},
                source_hashes=hashes, git_commit=common['git_commit'],
                prepare_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                reference_commit='18e1c5cf8e83dc134a9ee4d887abcfce29b24195',
                all_cohorts_frozen_before_candidate_results=True,
                gate='Run development first. No integrity failures before holdout. No parameter search or retuning.',
                formal_runs=0)
    save(out/'PLAN.json', plan)
    for cohort, manifest in manifests.items():
        for name, document in scenes[cohort].items():
            save(out/cohort/'scenes'/name, document)
        save(out/cohort/'manifest.json', manifest)
    save(out/'PREPARED.json', dict(plan_sha256=hashlib.sha256((out/'PLAN.json').read_bytes()).hexdigest(),
        manifests={c:hashlib.sha256((out/c/'manifest.json').read_bytes()).hexdigest() for c in manifests},
        planned_runs=640, formal_runs=0))
    print(json.dumps(dict(output=str(out), planned_runs=640, overlap_with_previous=0)))


if __name__ == '__main__':
    main()
