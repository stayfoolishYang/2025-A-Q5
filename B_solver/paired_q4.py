"""Paired evaluator. Hidden truth is accessed here, never by online Solver."""
import argparse
import csv
import hashlib
import json
import os
import platform
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np
from solver import Solver
from simulator import LocalSimulator
from geometry import contains

BASE = Path(__file__).resolve().parent


class AuditedSolver(Solver):
    def measure(self, c, p):
        super().measure(c, p)
        if c in self.tracks:
            # Evaluator-only oracle asserts containment without returning truth to policy.
            assert contains(self.tracks[c]['poly'], self.api.sources[c]['position'], tolerance=1e-5)[0]


def run_case(job):
    seed, config, device, directory = job
    stress = ('random','edge','bias','cluster')[seed % 4]
    api = LocalSimulator(seed, True, stress)
    solver = AuditedSolver(api, True, 'P4', device, config.get('particles',16384), diagnostic=config)
    start = time.perf_counter()
    error = ''
    try:
        solver.run()
    except Exception as exc:
        error = repr(exc)
    traces = list(solver.trace.values())
    row = dict(seed=seed, stress=stress, variant=config['name'], total=len(api.sources),
        cleared=len(api.cleared), clear_rate=len(api.cleared)/len(api.sources), error=error,
        mean_time_per_source=api.virtual_time/len(api.sources), distance=api.distance,
        fallback_count=solver.fallbacks, grid_points=sum(t['optical_grid_points'] for t in traces),
        clear_attempts=api.clear_attempts, optical_clear_attempts=sum(t['optical_clear_attempts'] for t in traces),
        diagnostic_count=sum(t['diagnostic_count'] for t in traces), detect_count=api.measures,
        switch_count=api.switches, runtime=time.perf_counter()-start,
        config_hash=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest())
    path = Path(directory)/'traces'/f"{config['name']}_{seed:05d}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(row=row, source_truth_evaluator_only=api.sources,
        targets=traces, actions=api.log), ensure_ascii=False), encoding='utf-8')
    return row


def metadata(seeds, configs, device):
    import torch
    return dict(git_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        git_dirty=bool(subprocess.check_output(['git','status','--porcelain','--','B_solver'],text=True).strip()),
        source_hashes={str(p.relative_to(BASE)):hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in BASE.rglob('*.py') if '__pycache__' not in str(p)},
        seeds=seeds, configs=configs, hardware=platform.platform(), processor=platform.processor(),
        torch=torch.__version__, cuda=torch.version.cuda, device=device,
        gpu=torch.cuda.get_device_name() if torch.cuda.is_available() else None,
        evidence='synthetic_local', cuda_visible_devices=os.environ.get('CUDA_VISIBLE_DEVICES'))


def summarize(rows, out):
    with (out/'cases.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    summaries={}
    for name in sorted({r['variant'] for r in rows}):
        a=[r for r in rows if r['variant']==name]
        t=np.array([r['mean_time_per_source'] for r in a])
        summaries[name]=dict(n=len(a),all_clear=sum(r['clear_rate']==1 and not r['error'] for r in a),
            clear_rate=sum(r['cleared'] for r in a)/sum(r['total'] for r in a),
            mean=float(t.mean()),median=float(np.median(t)),
            **{f'P{q}':float(np.percentile(t,q)) for q in (90,95,99)},max=float(t.max()),
            mean_distance=float(np.mean([r['distance'] for r in a])),
            P95_distance=float(np.percentile([r['distance'] for r in a],95)),
            fallback_rate=float(np.mean([r['fallback_count']>0 for r in a])),
            fallback_count=sum(r['fallback_count'] for r in a),
            mean_fallback_grid_points=float(np.mean([r['grid_points'] for r in a])),
            **{key:sum(r[key] for r in a) for key in ('clear_attempts','optical_clear_attempts','diagnostic_count','detect_count','switch_count')})
    baseline={r['seed']:r for r in rows if r['variant']=='P4_current'}
    for name, summary in summaries.items():
        a=[r for r in rows if r['variant']==name and r['seed'] in baseline]
        if a:
            delta=np.array([r['mean_time_per_source']-baseline[r['seed']]['mean_time_per_source'] for r in a])
            summary['paired_mean_delta']=float(delta.mean())
            summary['paired_wins']=int((delta < -1e-6).sum())
            summary['paired_losses']=int((delta > 1e-6).sum())
    (out/'summary.json').write_text(json.dumps(summaries,indent=2),encoding='utf-8')
    worst=sorted(rows,key=lambda r:(r['clear_rate']<1, r['mean_time_per_source']),reverse=True)[:10]
    (out/'worst10.json').write_text(json.dumps(worst,indent=2),encoding='utf-8')
    print(json.dumps(summaries,indent=2),flush=True)
    return summaries


def main():
    p=argparse.ArgumentParser();p.add_argument('--count',type=int,default=20);p.add_argument('--start',type=int,default=0)
    p.add_argument('--workers',type=int,default=4);p.add_argument('--device',default='cpu')
    p.add_argument('--configs',nargs='+',default=['q4_p4_baseline','q4_p4_diag_v1','q4_p4_diag_v2'])
    p.add_argument('--output',default=str(BASE/'results/diagnostic/paired20'))
    a=p.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    configs=[json.loads((BASE/'configs'/f'{name}.yaml').read_text()) for name in a.configs]
    seeds=list(range(a.start,a.start+a.count))
    (out/'manifest.json').write_text(json.dumps(metadata(seeds,configs,a.device),indent=2),encoding='utf-8')
    jobs=[(seed,c,a.device,str(out)) for seed in seeds for c in configs]
    rows=[]
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        for row in pool.map(run_case,jobs):
            rows.append(row)
            if len(rows)%5==0:print(f'{len(rows)}/{len(jobs)} cases; errors={sum(bool(r["error"]) for r in rows)}',flush=True)
    summarize(rows,out)


if __name__=='__main__':main()
