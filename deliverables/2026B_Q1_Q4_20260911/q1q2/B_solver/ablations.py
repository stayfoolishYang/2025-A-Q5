"""Controlled local ablations; no official sessions or hidden data in the policy."""
import csv
import json
from pathlib import Path
import numpy as np
from geometry import *
from simulator import LocalSimulator
from solver import Solver


def write_csv(path,rows):
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def run(n=100):
    out=Path('B_solver/results/ablations');out.mkdir(parents=True,exist_ok=True)
    rng=np.random.default_rng(2026); second=[]; discovery=[]; stop=[]; schedule=[]
    for seed in range(n):
        a=rng.uniform(0,2*np.pi); d=rng.uniform(50,1450)
        target=d*np.array([np.cos(a),np.sin(a)])
        sources={1:dict(position=target.tolist(),radius=1500,direction=None)}
        initial=LocalSimulator(seed,sources=sources);initial.action('/enter')
        z=initial.action('/measure',np.zeros(2),1)['svd_deg']
        poly=intersect_disk(wedge(disk(),np.zeros(2),z),np.zeros(2),1500)
        points=candidate_views(poly,np.zeros(2))
        safe=points[np.linalg.norm(poly[None]-points[:,None],axis=2).max(axis=1)<=1000]
        # 90-degree heuristic refers to the provisional midpoint target, not inaccessible truth.
        c,r=mec(poly); v=np.array([-np.sin(np.deg2rad(z)),np.cos(np.deg2rad(z))])
        choices={'random_safe':safe[rng.integers(len(safe))], 'perpendicular_midpoint':c+min(r*.3,200)*v,
                 'NBV':next_view(poly,np.zeros(2))[0]}
        for method,s in choices.items():
            api=LocalSimulator(seed,sources=sources);api.action('/enter');api.action('/measure',np.zeros(2),1)
            response=api.action('/measure',s,1)
            posterior=wedge(poly,s,response['svd_deg']) if response['measure_result']=='direction' else poly
            D=diameter(posterior)[0]; center,R=mec(posterior)
            second.append(dict(seed=seed,method=method,diameter_m=D,mec_radius_m=R,time_s=api.virtual_time))
            if response['measure_result']=='direction':
                u1=np.array([np.cos(np.deg2rad(z)),np.sin(np.deg2rad(z))])
                u2=np.array([np.cos(np.deg2rad(response['svd_deg'])),np.sin(np.deg2rad(response['svd_deg']))])
                matrix=np.c_[u1,-u2]
                if abs(np.linalg.det(matrix))>1e-9:
                    estimate=np.linalg.solve(matrix,s)[0]*u1
                    stop.append(dict(seed=seed,method=method,point_error_m=float(np.linalg.norm(estimate-target)),
                                     point_attempt_success=bool(np.linalg.norm(estimate-target)<=20),
                                     diameter_stop=bool(D<=40),mec_stop=bool(R<=19.999),
                                     mec_center_error_m=float(np.linalg.norm(center-target))))
        for mixed in (False,True):
            api=LocalSimulator(seed,mixed,'edge' if seed%2 else 'random')
            for name,nodes in [('center_only',np.zeros((1,2))),('seven_points',coverage()),('halfplane_grid',coverage(True))]:
                found=0
                for source in api.sources.values():
                    delta=nodes-np.array(source['position'])
                    signal=np.linalg.norm(delta,axis=1)<=source['radius']
                    if source['direction'] is not None:
                        phi=source['direction'];signal &= delta@np.array([np.cos(phi),np.sin(phi)])>=-1e-9
                    found+=int(signal.any())
                discovery.append(dict(seed=seed,problem=4 if mixed else 3,backbone=name,found=found,total=len(api.sources),fraction=found/len(api.sources)))
        for enabled in (False,True):
            api=LocalSimulator(seed,False,('random','edge','bias','cluster')[seed%4])
            row=Solver(api,False,'P3',schedule=enabled).run()
            schedule.append(dict(seed=seed,scheduling=enabled,cleared=row['cleared'],total=len(api.sources),time_per_source_s=row['mean_time_per_source_s']))
        if (seed+1)%25==0:print(f'Controlled ablations: {seed+1}/{n}',flush=True)
    write_csv(out/'second_view.csv',second);write_csv(out/'point_vs_set.csv',stop)
    write_csv(out/'discovery.csv',discovery);write_csv(out/'scheduling.csv',schedule)
    summary={'second_view':{},'scheduling':{},'discovery':{},'stopping':{}}
    for method in choices:
        rows=[r for r in second if r['method']==method]
        summary['second_view'][method]={k:float(np.mean([r[k] for r in rows])) for k in ['diameter_m','time_s']}
        rows=[r for r in stop if r['method']==method]
        summary['stopping'][method]=dict(point_attempt_success_rate=float(np.mean([r['point_attempt_success'] for r in rows])),
            mec_ready=sum(r['mec_stop'] for r in rows),diameter_ready=sum(r['diameter_stop'] for r in rows))
    for enabled in (False,True):
        summary['scheduling'][str(enabled)]=float(np.mean([r['time_per_source_s'] for r in schedule if r['scheduling']==enabled]))
    for problem in (3,4):
        for name in ('center_only','seven_points','halfplane_grid'):
            rows=[r for r in discovery if r['problem']==problem and r['backbone']==name]
            summary['discovery'][f'q{problem}_{name}']=sum(r['found'] for r in rows)/sum(r['total'] for r in rows)
    summary['diameter_counterexample']=dict(side=40,diameter=40,mec_radius=40/np.sqrt(3),diameter_stop_is_unsafe=True)
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':run()
