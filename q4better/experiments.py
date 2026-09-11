"""Reproducible full-case experiments, geometry checks, and CPU/CUDA comparison."""
import argparse
import csv
import itertools
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np
from scipy.spatial import ConvexHull
from geometry import *
from simulator import LocalSimulator
from solver import Solver


def one_case(job):
    seed, mixed, policy, stress, negative = job
    api = LocalSimulator(seed,mixed,stress)
    solver = Solver(api,mixed,policy,use_negative=negative)
    try:
        row = solver.run()
        row['error'] = ''
    except Exception as e:
        row = dict(policy=policy,mixed=mixed,cleared=len(api.cleared),virtual_time_s=api.virtual_time,
                   mean_time_per_source_s=api.virtual_time/max(1,len(api.cleared)),error=repr(e))
    row.update(seed=seed,stress=stress,use_negative=negative,total=len(api.sources),clear_rate=len(api.cleared)/len(api.sources),
               distance_m=api.distance,measure_count=api.measures,switch_count=api.switches,clear_attempts=api.clear_attempts,
               evidence='synthetic_local')
    return row,dict(sources=api.sources, log=api.log)


def batch(count=100, workers=4, output='B_solver/results/batch', quick=False):
    out=Path(output); out.mkdir(parents=True,exist_ok=True)
    variants=[(False,'P1',True),(False,'P2',True),(False,'P3',True),(True,'P1',True),(True,'P4',True),(True,'P4',False)]
    jobs=[(seed,mixed,policy,('random','edge','bias','cluster')[seed%4],negative)
          for seed in range(count) for mixed,policy,negative in variants]
    rows, worst=[] , []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for row,details in pool.map(one_case,jobs):
            rows.append(row)
            worst.append((row,details))
            worst.sort(key=lambda v:(1-v[0]['clear_rate'],v[0]['mean_time_per_source_s']),reverse=True)
            worst=worst[:20]
            if len(rows)%25==0:
                print(f'{len(rows)}/{len(jobs)} full cases; failures={sum(r["clear_rate"]<1 for r in rows)}',flush=True)
    fields=sorted(set().union(*(r.keys() for r in rows)))
    with (out/'cases.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    summary=[]
    for mixed,policy,negative in variants:
        group=[r for r in rows if (r['mixed'],r['policy'],r['use_negative'])==(mixed,policy,negative)]
        values=np.array([r['mean_time_per_source_s'] for r in group])
        summary.append(dict(problem=4 if mixed else 3,policy=policy,use_negative=negative,n=len(group),
                            all_clear_cases=sum(r['clear_rate']==1 for r in group),
                            pooled_clear_rate=sum(r['cleared'] for r in group)/sum(r['total'] for r in group),
                            mean=float(values.mean()),median=float(np.median(values)),p90=float(np.quantile(values,.9)),
                            p95=float(np.quantile(values,.95)),max=float(values.max())))
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    (out/'worst20.json').write_text(json.dumps(worst),encoding='utf-8')
    print(json.dumps(summary,indent=2),flush=True)


def verify(output='B_solver/results/geometry_checks.json'):
    rng=np.random.default_rng(2026)
    for _ in range(300):
        p=rng.normal(size=(20,2))*rng.uniform(.01,1800)
        p=p[ConvexHull(p).vertices]
        d,_,_=diameter(p)
        assert abs(d-np.linalg.norm(p[:,None]-p[None,:],axis=2).max())<1e-6
        c,r=mec(p)
        assert np.linalg.norm(p-c,axis=1).max()<=r
        assert r>=d/2-1e-7 and r<=d/np.sqrt(3)+1e-6
        # Independent finite support enumeration verifies actual minimality, not just inclusion.
        alternatives=[]
        for a,b in itertools.combinations(p,2):
            q=(a+b)/2; rr=np.linalg.norm(a-b)/2
            if np.linalg.norm(p-q,axis=1).max()<=rr+1e-7: alternatives.append(rr)
        for a,b,c0 in itertools.combinations(p,3):
            u,v=b-a,c0-a
            if abs(cross(u,v))<1e-10: continue
            q=a+np.linalg.solve(2*np.array([u,v]),np.array([u@u,v@v]))
            rr=np.linalg.norm(q-a)
            if np.linalg.norm(p-q,axis=1).max()<=rr+1e-7: alternatives.append(rr)
        assert abs(r-min(alternatives))<1e-5
    for _ in range(1000):
        target=sample_poly(disk(radius=1700),1,rng)[0]
        poly=disk()
        for _ in range(4):
            s=target+rng.uniform(20,1490)*np.array([np.cos(a:=rng.uniform(0,2*np.pi)),np.sin(a)])
            z=round((np.rad2deg(np.arctan2(*(target-s)[::-1]))+rng.uniform(-1,1))%360,2)%360
            poly=intersect_disk(wedge(poly,s,z),s,1500)
            assert len(poly) and contains(poly,target)[0]
    tri=np.array([[0.,0.],[40.,0.],[20.,20*np.sqrt(3)]])
    observations=[]; poly=disk(radius=1800)
    for a,b in zip(tri,np.roll(tri,-1,axis=0)):
        u=(b-a)/np.linalg.norm(b-a); s=a-1000*u
        z=np.rad2deg(np.arctan2(u[1],u[0]))+1
        observations.append(dict(position=s.tolist(),bearing_deg=z))
        poly=wedge(poly,s,z,error=1.)
    d,a,b=diameter(poly); c,r=mec(poly)
    assert abs(d-40)<1e-5 and abs(r-40/np.sqrt(3))<1e-5
    assert all(np.max(np.linalg.norm(tri-np.array(o['position']),axis=1))<1500 for o in observations)
    result=dict(random_convex_checks=300,truth_containment_checks=4000,
        counterexample=dict(observations=observations,polygon=poly.tolist(),diameter=d,mec_center=c.tolist(),mec_radius=r,
            diameter_circle_center=((a+b)/2).tolist(),diameter_circle_radius=d/2),
        coverage=dict(q3_nodes=coverage().tolist(),q4_nodes=coverage(True).tolist(),
            q3_analytic_upper_m=max(1130/np.sqrt(3),np.sqrt(1800**2+1130**2-np.sqrt(3)*1800*1130)),
            q4_cell_diameter_m=700*np.sqrt(2)))
    # One million spatial samples + exact radial bound + dense boundary verification.
    worst=0.
    for _ in range(10):
        a=rng.uniform(0,2*np.pi,100000); rad=1800*np.sqrt(rng.random(100000))
        p=rad[:,None]*np.c_[np.cos(a),np.sin(a)]
        worst=max(worst,float(np.linalg.norm(p[:,None]-coverage()[None],axis=2).min(axis=1).max()))
    a=np.linspace(0,2*np.pi,36001); p=1800*np.c_[np.cos(a),np.sin(a)]
    boundary=float(np.linalg.norm(p[:,None]-coverage()[None],axis=2).min(axis=1).max())
    assert worst<1000 and boundary<1000
    result['coverage'].update(random_samples=1000000,random_max_m=worst,boundary_max_m=boundary)
    # Original protocol's complete worked example: clear must NOT switch the radio.
    api=LocalSimulator(sources={}); api.action('/enter')
    for path,p,c in [('/measure',[300,400],1),('/measure',[300,400],2),('/clear',[300,0],3),('/measure',[300,0],2)]:
        api.action(path,p,c)
    assert api.virtual_time==199 and api.channel==2
    result['protocol_example_virtual_time_s']=api.virtual_time
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    Path(output).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('counterexample','coverage')}),flush=True)


def cuda_benchmark(output='B_solver/results/cuda.json'):
    from particles import signal_counts
    import torch
    rng=np.random.default_rng(0)
    n=1000000
    p=np.c_[rng.uniform(-1800,1800,(n,2)),rng.uniform(-np.pi,np.pi,n),rng.uniform(1000,1500,n),rng.integers(0,2,n)]
    s=rng.uniform(-2000,2000,(128,2))
    start=time.perf_counter(); cpu=signal_counts(p,s); cpu_s=time.perf_counter()-start
    start=time.perf_counter(); gpu=signal_counts(p,s,'cuda'); torch.cuda.synchronize(); gpu_s=time.perf_counter()-start
    max_difference=int(np.max(abs(cpu-gpu)))
    # FP32 decisions can differ exactly at thresholds: score is heuristic, not a certificate.
    assert max_difference<=5
    result=dict(particles=n,candidates=len(s),cpu_s=cpu_s,cuda_s=gpu_s,max_count_difference=max_difference,
        gpu=torch.cuda.get_device_name(),torch=torch.__version__,peak_memory_bytes=torch.cuda.max_memory_allocated(),
        numerical_role='heuristic only; certified geometry remains CPU float64')
    Path(output).write_text(json.dumps(result,indent=2),encoding='utf-8'); print(result,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('task',choices=['batch','verify','cuda'])
    parser.add_argument('--count',type=int,default=100); parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--output',default='B_solver/results/batch_v2')
    args=parser.parse_args()
    if args.task=='batch': batch(args.count,args.workers,args.output)
    elif args.task=='verify': verify()
    else: cuda_benchmark()
