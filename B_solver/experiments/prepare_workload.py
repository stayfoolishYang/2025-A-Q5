"""Freeze D0/D1/D2 on new seeds and two explicitly reused counterexamples."""
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
import zipfile

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
        raise FileExistsError('Choose a new experiment directory')
    sys.path.insert(0, str(sim))
    from scenario_io import generate_document
    previous = json.loads((BASE/'results/recovered/discovery_20260911_summary/evidence/PLAN.json').read_bytes())
    nccp = json.loads((BASE/'results/recovered/nccp_20260911_summary/evidence/PLAN.json').read_bytes())
    old = {r['seed_hex'] for r in frozen_seeds()+previous['seeds']+nccp['shared_seed_plan']['holdout256']}
    prefix = '2026B-workload-refresh-20260911:'
    seeds = [dict(seed=i,seed_hex=hashlib.sha256((prefix+str(i)).encode()).hexdigest(),
                  family='sha256_workload_design',derivation_index=i) for i in range(160)]
    assert len({s['seed_hex'] for s in seeds})==160 and not old.intersection(s['seed_hex'] for s in seeds)
    known = [dict(seed=i,seed_hex=previous['seeds'][s+32]['seed_hex'],family='known_discovery_counterexample',
                  source_seed=s,source_cohort='discovery_20260911/holdout128',source_derivation_index=s+32,
                  source_seed_hex=previous['seeds'][s+32]['seed_hex']) for i,s in enumerate((42,107))]
    configs = [json.loads((BASE/'configs'/('q4_p4_diag_v1_grid_v1'+suffix+'.yaml')).read_bytes())
               for suffix in ('','_refresh','_workload')]
    strip = lambda c:{k:v for k,v in c.items() if k not in ('name','discovery_route','discovery_channels')}
    assert all(strip(c)==strip(configs[0]) and c.get('clearance_point','mec_center')=='mec_center'
               and c.get('discovery_channels','legacy')=='legacy' for c in configs)
    assert [c.get('discovery_route','legacy') for c in configs]==['legacy','refresh_after_localize','workload_after_localize']
    hashes=source_hashes(sim)
    assert all(hashes[k]==v for k,v in previous['source_hashes'].items() if k.startswith('engine/'))
    blas=io.StringIO()
    with contextlib.redirect_stdout(blas):
        np.show_config()
    head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    common=dict(schema='recovered-benchmark-v1',configs={'4':configs},grid_version='grid_v1',source_hashes=hashes,
        simulator_root=str(sim),python=sys.version,executable=sys.executable,numpy=np.__version__,blas=blas.getvalue(),
        platform=platform.platform(),evidence='recovered_practice_engine_local',git_commit=head,
        limits=dict(real_s=1200,virtual_s=360000),formal_tests=0,
        algorithm_changes='D2 changes only the score of D1 same two remaining-route candidates; no obligation pruning.',
        prepared_at_utc=datetime.now(timezone.utc).isoformat())
    manifests,scenes={},{}
    for cohort,subset in (('development32',seeds[:32]),('holdout128',seeds[32:]),('known_counterexamples2',known)):
        records=[dict(s,seed=i) for i,s in enumerate(subset)]
        documents={f'q4_{r["seed"]:04d}.json':generate_document(seed_hex=r['seed_hex'],problem=4,format='native') for r in records}
        manifest=dict(common,cohort=cohort,seeds=records,scene_hashes={n:digest(d) for n,d in documents.items()},
                      seed_design='Previously used counterexamples' if cohort.startswith('known') else 'New deterministic design; non-IID, non-official')
        manifest['plan_hash']=digest({k:manifest[k] for k in ('seeds','configs','source_hashes','scene_hashes')})
        manifests[cohort],scenes[cohort]=manifest,documents
    assert source_hashes(sim)==hashes
    out.mkdir(parents=True)
    plan=dict(schema='workload-3way-v1',prefix=prefix,seeds=seeds,known_seeds=known,configs=configs,
        cohorts={c:dict(n=len(m['seeds']),runs=3*len(m['seeds']),plan_hash=m['plan_hash']) for c,m in manifests.items()},
        source_hashes=hashes,git_commit=head,reference_commit='9bee5c4c9c4a3f0f3e612142a045ad9d8f5cd5f8',
        prepare_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        all_cohorts_frozen_before_candidate_results=True,
        gate='Development and known counterexample integrity first, no parameter tuning; then all holdout cases.',
        adoption=dict(minimum_mean_reduction_fraction=.01,P95_must_not_increase=True,P99_must_not_increase=True,
                      all_integrity_checks_must_pass=True,last_discovery_is_auxiliary=True),formal_runs=0)
    save(out/'PLAN.json',plan)
    for cohort,manifest in manifests.items():
        for name,document in scenes[cohort].items():
            save(out/cohort/'scenes'/name,document)
        save(out/cohort/'manifest.json',manifest)
    save(out/'PREPARED.json',dict(plan_sha256=hashlib.sha256((out/'PLAN.json').read_bytes()).hexdigest(),
         manifests={c:hashlib.sha256((out/c/'manifest.json').read_bytes()).hexdigest() for c in manifests},
         planned_runs=486,new_runs=480,known_runs=6,formal_runs=0))
    with zipfile.ZipFile(out/f'frozen_source_{head[:7]}.zip','x',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,expected in hashes.items():
            prefix,relative=name.split('/',1)
            data=((BASE if prefix=='solver' else sim)/relative).read_bytes()
            assert hashlib.sha256(data).hexdigest()==expected
            archive.writestr(name,data)
        archive.writestr('PLAN.json',(out/'PLAN.json').read_bytes())
    print(json.dumps(dict(output=str(out),planned_runs=486,new_runs=480,known_runs=6,overlap_new_with_previous=0)))


if __name__=='__main__':
    main()
