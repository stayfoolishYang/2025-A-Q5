"""Same frozen Q4 cases/configs, separately reported CUDA execution."""
import csv
import hashlib
import json
import shutil
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import full_local_519 as batch

OUT=Path('J:/2026B_runs/better_full519_cuda_20260911')
CPU=Path('J:/2026B_runs/better_full519_20260911')
BaseSolver=batch.Solver

def cuda_solver(*args,**kwargs):
    kwargs['device']='cuda'
    return BaseSolver(*args,**kwargs)

def initialize():
    import torch
    assert torch.cuda.is_available()
    torch.set_num_threads(1)
    batch.OUT=OUT
    batch.Solver=cuda_solver

def main():
    OUT.mkdir(parents=True,exist_ok=False)
    shutil.copytree(CPU/'scenes',OUT/'scenes')
    shutil.copytree(CPU/'configs',OUT/'configs')
    (OUT/'runs').mkdir()
    plan=json.loads((CPU/'PLAN.json').read_bytes())
    plan.update(device='cuda',workers=2,planned=1557,problem=4,
                parent_plan_sha256=hashlib.sha256((CPU/'PLAN.json').read_bytes()).hexdigest(),
                launcher_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (OUT/'PLAN.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    jobs=[(4,r['seed'],v) for r in plan['seeds'] for v in 'ABC']
    with ProcessPoolExecutor(max_workers=2,initializer=initialize) as pool:
        futures=[pool.submit(batch.worker,j) for j in jobs]
        for n,f in enumerate(as_completed(futures),1):
            r=f.result()
            if n%25==0 or r['status']!='FULL_CLEAR':print(n,'/1557',r['seed'],r['variant'],r['status'],flush=True)
    rows=[json.loads(p.read_bytes()) for p in sorted((OUT/'runs').glob('*.json'))]
    with (OUT/'cases.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=sorted(set().union(*(r.keys() for r in rows))));w.writeheader();w.writerows(rows)
    import numpy as np
    groups={v:{r['seed']:r for r in rows if r['variant']==v} for v in 'ABC'}
    summary={}
    for v,g in groups.items():
        good=[r for r in g.values() if r['status']=='FULL_CLEAR'];x=[r['mean_time_per_source_s'] for r in good]
        summary[v]=dict(runs=len(g),full=len(good),mean=float(np.mean(x)),p95=float(np.quantile(x,.95)),maximum=float(max(x)))
    pairs={}
    for ref,v in [('A','B'),('B','C'),('A','C')]:
        ids=[i for i in groups[v] if groups[v][i]['status']==groups[ref][i]['status']=='FULL_CLEAR']
        d=np.array([groups[v][i]['mean_time_per_source_s']-groups[ref][i]['mean_time_per_source_s'] for i in ids])
        pairs[v+'-'+ref]=dict(n=len(ids),mean_delta=float(d.mean()),wins=int(sum(d< -1e-8)),ties=int(sum(abs(d)<=1e-8)),losses=int(sum(d>1e-8)),max_regression=float(max(d)))
    result=dict(variants=summary,pairs=pairs,device='cuda',official_calls=0)
    (OUT/'SUMMARY.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result),flush=True)

if __name__=='__main__':main()
