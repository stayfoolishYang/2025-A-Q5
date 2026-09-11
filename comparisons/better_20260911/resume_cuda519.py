"""Resume missing CUDA cases without overwriting any completed result."""
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import full_local_cuda519 as run

def main():
    out=run.OUT
    plan=json.loads((out/'PLAN.json').read_bytes())
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in plan['hashes'].items())
    for folder in ('scenes','configs'):
        assert all(p.read_bytes()==(run.CPU/folder/p.name).read_bytes() for p in (out/folder).glob('*.json'))
    jobs=[]
    for s in plan['seeds']:
        for v in 'ABC':
            p=out/'runs'/f'q4_{s["seed"]:04d}_{v}.json'
            if p.exists():
                r=json.loads(p.read_bytes());assert (r['problem'],r['seed'],r['variant'])==(4,s['seed'],v)
                continue
            trace=p.with_suffix('.json.gz')
            if trace.exists():trace.rename(trace.with_name(trace.name+'.interrupted-'+datetime.now().strftime('%H%M%S')))
            jobs.append((4,s['seed'],v))
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    (out/f'RESUME_{stamp}.json').write_text(json.dumps(dict(missing=jobs,completed=1557-len(jobs),workers=2,reason='No running Python processes; original termination cause unknown'),indent=2),encoding='utf-8')
    print('Resuming',len(jobs),'missing cases',flush=True)
    with ProcessPoolExecutor(max_workers=2,initializer=run.initialize) as pool:
        futures=[pool.submit(run.batch.worker,j) for j in jobs]
        for n,f in enumerate(as_completed(futures),1):
            r=f.result()
            if n%25==0 or r['status']!='FULL_CLEAR':print(n,'/',len(jobs),r['seed'],r['variant'],r['status'],flush=True)
    rows=[json.loads(p.read_bytes()) for p in sorted((out/'runs').glob('*.json'))]
    assert len(rows)==1557
    with (out/'cases.csv').open('w',newline='',encoding='utf-8') as f:
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
    (out/'SUMMARY.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result),flush=True)

if __name__=='__main__':main()
