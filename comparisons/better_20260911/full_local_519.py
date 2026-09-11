"""All canonical 519 seeds, four CPU processes, local engine only."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import csv
import gzip
import hashlib
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parent
SRC=ROOT/'q4better'
SIM=Path('G:/QQ/jammers_linux')
OUT=Path('J:/2026B_runs/better_full519_20260911')
sys.path[:0]=[str(SRC),str(SIM)]
from solver import Solver
from recovered_benchmark import EngineAdapter, frozen_seeds
from engine import Engine, go_round
from scenario_io import generate_document, load_scenario

def worker(job):
    q,seed,v=job
    dest=OUT/'runs'/f'q{q}_{seed:04d}_{v}.json'
    scene=json.loads((OUT/'scenes'/f'q{q}_{seed:04d}.json').read_bytes())
    cfg=json.loads((OUT/'configs'/f'q{q}_{v}.json').read_bytes())
    start=time.perf_counter(); api=None
    try:
        e=Engine(load_scenario(scene));api=EngineAdapter(e)
        s=Solver(api,q==4,'P4' if q==4 else 'P3',device='cpu',diagnostic=cfg)
        if q==3 and v=='B':s.discovery_route='refresh_after_localize'
        result=s.run()
        assert e.cleared=={j.channel for j in e.scenario.jammers} and not s.tracks
        us=0;pos=(0.,0.);ch=1;done=set();stop_index=None
        for i,a in enumerate(api.log):
            r=a['response'];assert r['accepted'] is True
            if a['path'] in ('/measure','/clear'):
                assert stop_index is None
                p=a['position'];us+=go_round(1e12*math.hypot(p[0]-pos[0],p[1]-pos[1])/5000000)
                if a['path']=='/measure':us+=5000000+1000000*(ch!=a['channel']);ch=a['channel']
                else:
                    ok=r['clear_result']=='success';us+=5000000 if ok else 3000000
                    if ok:done.add(a['channel'])
                    if cfg.get('stop_after_public_max_clear') and len(done)==16:stop_index=i
                pos=p
            assert round(r['virtual_time_s']*1e6)==us
        assert api.log[-1]['path']=='/exit' and api.log[-1]['response']['exit_reason']=='user_exit'
        result.update(status='FULL_CLEAR',audit=True)
    except Exception as ex:
        result=dict(status='FAILED',audit=False,error=repr(ex))
    result.update(problem=q,seed=seed,variant=v,total=len(scene['jammers']),wall_s=time.perf_counter()-start)
    if api is not None:
        with gzip.open(dest.with_suffix('.json.gz'),'wt',encoding='utf-8') as f:json.dump(api.log,f)
    dest.write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result

def report():
    rows=[json.loads(p.read_bytes()) for p in sorted((OUT/'runs').glob('*.json'))]
    with (OUT/'cases.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=sorted(set().union(*(r.keys() for r in rows))));w.writeheader();w.writerows(rows)
    summary={}
    for q in (3,4):
        variants='AB' if q==3 else 'ABC'
        g={v:{r['seed']:r for r in rows if r['problem']==q and r['variant']==v} for v in variants}
        stats={}
        for v in variants:
            good=[r for r in g[v].values() if r['status']=='FULL_CLEAR'];x=[r['mean_time_per_source_s'] for r in good]
            stats[v]=dict(runs=len(g[v]),full=len(good),mean=float(np.mean(x)),median=float(np.median(x)),p95=float(np.quantile(x,.95)),maximum=float(max(x)),fallbacks=sum(r['optical_fallbacks'] for r in good))
        pairs={}
        for ref,v in ([('A','B')] if q==3 else [('A','B'),('B','C'),('A','C')]):
            ids=[i for i in g[v].keys()&g[ref].keys() if g[v][i]['status']==g[ref][i]['status']=='FULL_CLEAR']
            d=np.array([g[v][i]['mean_time_per_source_s']-g[ref][i]['mean_time_per_source_s'] for i in ids])
            pairs[v+'-'+ref]=dict(n=len(ids),mean_delta=float(d.mean()),wins=int(sum(d < -1e-8)),ties=int(sum(abs(d)<=1e-8)),losses=int(sum(d>1e-8)),max_regression=float(max(d)),worst_seed=ids[int(np.argmax(d))])
        summary[q]=dict(variants=stats,pairs=pairs)
    (OUT/'SUMMARY.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary),flush=True)

def main():
    OUT.mkdir(parents=True,exist_ok=False)
    for name in ('scenes','configs','runs'):(OUT/name).mkdir()
    seeds=frozen_seeds();assert len(seeds)==519
    for q in (3,4):
        for r in seeds:
            scene=generate_document(seed_hex=r['seed_hex'],problem=q,format='native')
            (OUT/'scenes'/f'q{q}_{r["seed"]:04d}.json').write_text(json.dumps(scene),encoding='utf-8')
        for v in ('AB' if q==3 else 'ABC'):
            cfg=(dict(enabled=False,local_order=False,particles=16384,grid_version='grid_v1',clearance_point='mec_center') if q==3 else json.loads((SRC/f'configs/q4_public_max37_{v}.yaml').read_bytes()))
            (OUT/'configs'/f'q{q}_{v}.json').write_text(json.dumps(cfg),encoding='utf-8')
    paths=list(SRC.glob('*.py'))+list((SRC/'directional').glob('*.py'))+list(SIM.glob('*.py'))+[Path(__file__)]
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    (OUT/'PLAN.json').write_text(json.dumps(dict(seeds=seeds,hashes=hashes,workers=4,device='cpu',planned=2595,official_calls=0,scope='All canonical 519 seeds; existing regression set, not new holdout'),indent=2),encoding='utf-8')
    jobs=[(q,r['seed'],v) for r in seeds for q in (3,4) for v in ('AB' if q==3 else 'ABC')]
    with ProcessPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(worker,j) for j in jobs]
        for n,f in enumerate(as_completed(futures),1):
            r=f.result()
            if n%25==0 or r['status']!='FULL_CLEAR':print(n,'/2595',r['problem'],r['seed'],r['variant'],r['status'],flush=True)
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items())
    report()

if __name__=='__main__':main()
