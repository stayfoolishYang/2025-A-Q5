"""Resume missing jobs only; retain completed results and frozen inputs."""
import argparse
import csv
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import full_local_519 as batch
import full_local_cuda519 as gpu
import numpy as np

def main():
    p=argparse.ArgumentParser();p.add_argument('--device',choices=['cpu','cuda'],required=True);a=p.parse_args()
    root=gpu.OUT if a.device=='cuda' else batch.OUT
    plan=json.loads((root/'PLAN.json').read_bytes())
    for path,h in plan['hashes'].items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==h,path
    jobs=[]
    for r in plan['seeds']:
        for q in ((4,) if a.device=='cuda' else (3,4)):
            for v in ('AB' if q==3 else 'ABC'):
                dest=root/'runs'/f'q{q}_{r["seed"]:04d}_{v}.json'
                if dest.exists():
                    row=json.loads(dest.read_bytes())
                    assert (row['problem'],row['seed'],row['variant'])==(q,r['seed'],v)
                    assert dest.with_suffix('.json.gz').exists()
                else:jobs.append((q,r['seed'],v))
    print(f'Resuming {len(jobs)} missing {a.device} jobs; existing rows retained',flush=True)
    with ProcessPoolExecutor(max_workers=2 if a.device=='cuda' else 4,initializer=gpu.initialize if a.device=='cuda' else None) as pool:
        fs=[pool.submit(batch.worker,j) for j in jobs]
        for n,f in enumerate(as_completed(fs),1):
            row=f.result()
            if n%25==0 or row['status']!='FULL_CLEAR':print(n,len(jobs),row['status'],flush=True)
    rows=[json.loads(f.read_bytes()) for f in sorted((root/'runs').glob('*.json'))]
    assert len(rows)==plan['planned']
    with (root/'cases.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=sorted(set().union(*(r.keys() for r in rows))));w.writeheader();w.writerows(rows)
    summary={}
    for q in sorted(set(r['problem'] for r in rows)):
        groups={v:{r['seed']:r for r in rows if r['problem']==q and r['variant']==v} for v in ('AB' if q==3 else 'ABC')}
        stats={};pairs={}
        for v,g in groups.items():
            good=[r for r in g.values() if r['status']=='FULL_CLEAR'];x=[r['mean_time_per_source_s'] for r in good]
            stats[v]=dict(runs=len(g),full=len(good),mean=float(np.mean(x)),median=float(np.median(x)),p95=float(np.quantile(x,.95)),maximum=float(max(x)),fallbacks=sum(r['optical_fallbacks'] for r in good))
        for ref,v in ([('A','B')] if q==3 else [('A','B'),('B','C'),('A','C')]):
            ids=[i for i in groups[v] if groups[v][i]['status']==groups[ref][i]['status']=='FULL_CLEAR']
            d=np.array([groups[v][i]['mean_time_per_source_s']-groups[ref][i]['mean_time_per_source_s'] for i in ids])
            pairs[v+'-'+ref]=dict(n=len(ids),mean_delta=float(d.mean()),wins=int(sum(d < -1e-8)),ties=int(sum(abs(d)<=1e-8)),losses=int(sum(d>1e-8)),max_regression=float(max(d)))
        summary[q]=dict(variants=stats,pairs=pairs)
    (root/'SUMMARY.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary),flush=True)

if __name__=='__main__':main()
