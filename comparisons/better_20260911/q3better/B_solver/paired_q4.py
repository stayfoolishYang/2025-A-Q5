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
from solver import Solver
from simulator import LocalSimulator
from geometry import contains
from evaluation import classify_run, evaluate_rows, expected_pairs as plan_pairs, exception_status, json_safe

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
    start = time.perf_counter()
    error, status, api, solver = '', None, None, None
    try:
        api = LocalSimulator(seed, True, stress)
        solver = AuditedSolver(api, True, 'P4', device, config.get('particles',16384), diagnostic=config)
        solver.run()
    except Exception as exc:
        error, status = repr(exc), exception_status(exc)
    traces = list(solver.trace.values()) if solver is not None else []
    sources = getattr(api, 'sources', {})
    total, cleared = len(sources), len(getattr(api, 'cleared', []))
    virtual_time = getattr(api, 'virtual_time', 0.)
    row = dict(seed=seed, stress=stress, variant=config['name'], total=total,
        cleared=cleared, clear_rate=cleared/total if total else None, error=error,
        mean_time_per_source=virtual_time/total if total else None, virtual_time=virtual_time,
        distance=getattr(api, 'distance', 0.),
        fallback_count=getattr(solver, 'fallbacks', 0), grid_points=sum(t['optical_grid_points'] for t in traces),
        clear_attempts=getattr(api, 'clear_attempts', 0), optical_clear_attempts=sum(t['optical_clear_attempts'] for t in traces),
        diagnostic_count=sum(t['diagnostic_count'] for t in traces), detect_count=getattr(api, 'measures', 0),
        switch_count=getattr(api, 'switches', 0), runtime=time.perf_counter()-start,
        scene_hash=hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest(),
        config_hash=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest())
    if status is not None:
        row['run_status'] = status
    row = classify_run(row)
    path = Path(directory)/'traces'/f"{config['name']}_{seed:05d}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        json.dump(json_safe(dict(row=row, source_truth_evaluator_only=sources,
            targets=traces, actions=getattr(api, 'log', []))), f, ensure_ascii=False, allow_nan=False)
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


def summarize(rows, out, expected_pairs=None, baseline_name='P4_current', write_cases=True):
    """Write evaluated artifacts; pass write_cases=False to audit old raw CSVs.

    Raw cases.csv is created exclusively and is never overwritten. Derived
    summaries are replaceable. Acceptance requires an explicit frozen pair plan.
    """
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    if write_cases:
        fields = list(dict.fromkeys(key for row in rows for key in row)) or ['seed', 'variant']
        with (out/'cases.csv').open('x', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    result = evaluate_rows(rows, expected_pairs, baseline_name)
    classified = result['classified_rows']
    fields = list(dict.fromkeys(key for row in classified for key in row)) or ['seed', 'variant', 'run_status']
    with (out/'classified_cases.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(classified)
    for name in ('summary', 'acceptance', 'worst10'):
        (out/f'{name}.json').write_text(json.dumps(json_safe(result[name]), indent=2,
            ensure_ascii=False, allow_nan=False), encoding='utf-8')
    print(json.dumps(result['acceptance'], indent=2, ensure_ascii=False), flush=True)
    return result['summary']


def main():
    p=argparse.ArgumentParser();p.add_argument('--count',type=int,default=20);p.add_argument('--start',type=int,default=0)
    p.add_argument('--workers',type=int,default=4);p.add_argument('--device',default='cpu')
    p.add_argument('--configs',nargs='+',default=['q4_p4_baseline','q4_p4_diag_v1','q4_p4_diag_v2'])
    p.add_argument('--baseline-name',default='P4_current')
    p.add_argument('--output',default=str(BASE/'results/diagnostic/paired20'))
    a=p.parse_args();out=Path(a.output)
    if a.count < 1 or a.workers < 1:
        p.error('--count and --workers must be positive')
    if out.exists() and any(out.iterdir()):
        p.error('output directory must be empty; archived evidence is immutable')
    out.mkdir(parents=True,exist_ok=True)
    configs=[json.loads((BASE/'configs'/f'{name}.yaml').read_text()) for name in a.configs]
    seeds=list(range(a.start,a.start+a.count))
    variants=[config['name'] for config in configs]
    if len(set(variants)) != len(variants):
        p.error('configuration variant names must be unique')
    (out/'manifest.json').write_text(json.dumps(metadata(seeds,configs,a.device),indent=2),encoding='utf-8')
    jobs=[(seed,c,a.device,str(out)) for seed in seeds for c in configs]
    rows=[]
    try:
        with ProcessPoolExecutor(max_workers=a.workers) as pool:
            for row in pool.map(run_case,jobs):
                rows.append(row)
                if len(rows)%5==0:print(f'{len(rows)}/{len(jobs)} cases; errors={sum(bool(r["error"]) for r in rows)}',flush=True)
    finally:
        summarize(rows,out,expected_pairs=plan_pairs(seeds,variants),baseline_name=a.baseline_name)
    if not json.loads((out/'acceptance.json').read_text(encoding='utf-8'))['accept']:
        raise SystemExit(2)


if __name__=='__main__':main()
