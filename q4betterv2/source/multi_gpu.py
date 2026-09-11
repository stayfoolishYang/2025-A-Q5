"""One independent synthetic-case worker per GPU. No official endpoint access."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--gpus',default='0');p.add_argument('--cases',type=int,default=100)
    p.add_argument('--output',default='results/server');p.add_argument('--worker',type=int);p.add_argument('--workers',type=int)
    a=p.parse_args();out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True)
    if a.worker is not None:
        import torch
        from solver import Solver
        from simulator import LocalSimulator
        if not torch.cuda.is_available():raise RuntimeError('CUDA is required for GPU worker')
        torch.set_num_threads(1)
        with (out/f'worker_{a.worker}.jsonl').open('w',encoding='utf-8') as f:
            for seed in range(a.worker,a.cases,a.workers):
                api=LocalSimulator(seed,mixed=True)
                row=Solver(api,True,'P4','cuda').run()
                row.update(seed=seed,total=len(api.sources),clear_rate=len(api.cleared)/len(api.sources),gpu=torch.cuda.get_device_name())
                f.write(json.dumps(row)+'\n');f.flush()
        return
    children=[]
    gpu_ids=a.gpus.split(',')
    for i,gpu in enumerate(gpu_ids):
        env=dict(os.environ,CUDA_VISIBLE_DEVICES=gpu,OMP_NUM_THREADS='1')
        cmd=[sys.executable,str(Path(__file__).resolve()),'--worker',str(i),'--workers',str(len(gpu_ids)),
             '--cases',str(a.cases),'--output',str(out)]
        children.append(subprocess.Popen(cmd,env=env))
    failures=[p.wait() for p in children]
    if any(failures):raise SystemExit(f'GPU worker failures: {failures}')
    print(f'Completed {a.cases} synthetic cases across {len(gpu_ids)} GPU workers')


if __name__=='__main__':main()
