"""One GPU per independent paired worker. Never connects to official simulator."""
import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from evaluation import expected_pairs, json_safe


def collect_worker_results(workers, out, planned_pairs, baseline_name='P4_current', worker_errors=None):
    """Preserve available evidence and write a rejecting audit on any worker fault."""
    rows, manifests, errors = [], [], list(worker_errors or [])
    for worker in workers:
        worker = Path(worker)
        try:
            manifests.append(json.loads((worker/'manifest.json').read_text(encoding='utf-8')))
        except (OSError, ValueError) as exc:
            errors.append(f'{worker.name}: manifest unavailable: {exc}')
        try:
            with (worker/'cases.csv').open(encoding='utf-8-sig', newline='') as f:
                # Keep CSV evidence unchanged; the common evaluator validates
                # numeric strings and excludes malformed rows explicitly.
                rows.extend(csv.DictReader(f))
        except (OSError, ValueError, csv.Error) as exc:
            errors.append(f'{worker.name}: cases unavailable: {exc}')
    (out/'worker_manifests.json').write_text(json.dumps(manifests,indent=2),encoding='utf-8')
    from paired_q4 import summarize
    summarize(rows, out, expected_pairs=planned_pairs, baseline_name=baseline_name)
    path = out/'acceptance.json'
    acceptance = json.loads(path.read_text(encoding='utf-8'))
    acceptance['worker_errors'] = errors
    if errors:
        acceptance.update(accept=False, experiment_valid=False, all_runs_completed=False,
                          all_runs_full_clear=False, speed_comparison_valid=False)
        acceptance['failure_reasons'].append('worker_execution_or_evidence_error')
        for performance in acceptance['performance'].values():
            performance.update(valid=False, outcome='not_evaluable')
    path.write_text(json.dumps(json_safe(acceptance), indent=2, allow_nan=False), encoding='utf-8')
    return acceptance


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--gpus',default='0');p.add_argument('--count',type=int,default=1000)
    p.add_argument('--start',type=int,default=0);p.add_argument('--output',default='B_solver/results/diagnostic/server')
    p.add_argument('--configs',nargs='+',default=['q4_p4_baseline','q4_p4_diag_v1','q4_p4_diag_v2'])
    p.add_argument('--baseline-name',default='P4_current')
    a=p.parse_args();out=Path(a.output).resolve()
    ids=[gpu.strip() for gpu in a.gpus.split(',')]
    if a.count < 1 or any(not gpu for gpu in ids) or len(ids) != len(set(ids)):
        p.error('positive count and unique nonempty GPU identifiers are required')
    if out.exists() and any(out.iterdir()):
        p.error('output directory must be empty; archived evidence is immutable')
    out.mkdir(parents=True,exist_ok=True)
    base=Path(__file__).resolve().parent
    configs=[json.loads((base/'configs'/f'{name}.yaml').read_text(encoding='utf-8')) for name in a.configs]
    variants=[config['name'] for config in configs]
    if len(variants) != len(set(variants)):
        p.error('configuration variant names must be unique')
    planned=expected_pairs(range(a.start,a.start+a.count),variants)
    children=[]; workers=[]; errors=[]
    for i,gpu in enumerate(ids):
        first=a.start+a.count*i//len(ids);end=a.start+a.count*(i+1)//len(ids)
        if first==end:continue
        worker=out/f'worker_{i}'
        workers.append(worker)
        log=(out/f'worker_{i}.stdout.log').open('x',encoding='utf-8')
        env=dict(os.environ,CUDA_VISIBLE_DEVICES=gpu,OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
        cmd=[sys.executable,str(Path(__file__).with_name('paired_q4.py')),'--count',str(end-first),
             '--start',str(first),'--workers','1','--device','cuda','--output',str(worker),
             '--baseline-name',a.baseline_name,'--configs',*a.configs]
        try:
            proc=subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT)
        except OSError as exc:
            log.close()
            errors.append(f'{worker.name}: failed to start: {exc}')
        else:
            children.append((proc,log,worker))
    codes=[]
    for proc,log,_ in children:
        codes.append(proc.wait());log.close()
    errors.extend(f'{worker.name}: process exited {code}' for (_,_,worker),code in zip(children,codes) if code)
    acceptance=collect_worker_results(workers,out,planned,a.baseline_name,errors)
    if not acceptance['accept']:
        raise SystemExit(2)


if __name__=='__main__':main()
