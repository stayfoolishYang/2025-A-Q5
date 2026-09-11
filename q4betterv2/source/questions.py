"""Q1 generic input solver and Q2 reproducible candidate-region example."""
import argparse
import csv
import json
from pathlib import Path
import numpy as np
from scipy.optimize import linprog
from geometry import clip, disk, wedge, intersect_disk, diameter, mec, next_view


def solve_q1(observations, error=1., arena_radius=None):
    normals, bounds = [], []
    for obs in observations:
        p=np.asarray(obs['position'],dtype=float); angle=float(obs['bearing_deg'])
        if p.shape!=(2,) or not np.isfinite(p).all() or not np.isfinite(angle):
            raise ValueError('Q1 observations must have finite position and bearing')
        low,high=np.deg2rad([angle-error,angle+error])
        for n in (np.array([np.sin(low),-np.cos(low)]),np.array([-np.sin(high),np.cos(high)])):
            normals.append(n); bounds.append(n@p)
    if arena_radius is not None:
        p=disk(radius=arena_radius)
    else:
        if not normals:
            return dict(status='unbounded',diameter=None)
        extrema=[]
        for direction in ([1,0],[-1,0],[0,1],[0,-1]):
            res=linprog(direction,A_ub=normals,b_ub=bounds,bounds=[(None,None)]*2,method='highs')
            if res.status==2: return dict(status='empty',diameter=None)
            if res.status==3: return dict(status='unbounded',diameter=None)
            if not res.success: raise RuntimeError(res.message)
            extrema.append(res.x)
        lo=np.min(extrema,axis=0)-1e-7; hi=np.max(extrema,axis=0)+1e-7
        p=np.array([[lo[0],lo[1]],[hi[0],lo[1]],[hi[0],hi[1]],[lo[0],hi[1]]])
    for n,b in zip(normals,bounds): p=clip(p,n,b)
    if not len(p): return dict(status='empty',diameter=None)
    d,a,b=diameter(p); c,r=mec(p)
    return dict(status='bounded',polygon=p.tolist(),diameter=d,diameter_endpoints=[a.tolist(),b.tolist()],
                mec_center=c.tolist(),mec_radius=r,diameter_circle_covers=bool(r<=d/2+1e-6),
                arena_outer_approximation=arena_radius is not None)


def q2_example(out):
    s0=np.zeros(2); bearing=30.
    poly=intersect_disk(wedge(disk(),s0,bearing),s0,1500)
    a=np.deg2rad(bearing); basis=np.array([[np.cos(a),-np.sin(a)],[np.sin(a),np.cos(a)]])
    pts=np.array([(x,y) for x in np.arange(0,1501,50) for y in np.arange(-600,601,40)])@basis.T
    _,records=next_view(poly,s0,candidates=pts,safe_only=True)
    fields=['x','y','worst_sampled_diameter_m','action_time_s','safe']
    with (out/'q2_candidates.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.writer(f);writer.writerow(fields)
        writer.writerows([(*p,w,t,safe) for _,p,w,t,safe in records])
    solutions=[]
    for lam in (0.,.2,1.,5.):
        row=min(records,key=lambda r:r[2]+lam*r[3])
        solutions.append(dict(lambda_m_per_s=lam,point=row[1].tolist(),worst_sampled_diameter_m=row[2],time_s=row[3]))
    result=dict(example_only=True,first_position=s0.tolist(),first_bearing_deg=bearing,
                polygon=poly.tolist(),candidate_count=len(records),solutions=solutions,
                limitation='Discrete sampled minimax, not a proven continuous global optimum')
    (out/'q2.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--observations');parser.add_argument('--arena-radius',type=float)
    args=parser.parse_args();out=Path('B_solver/results');out.mkdir(parents=True,exist_ok=True)
    if args.observations:
        result=solve_q1(json.loads(Path(args.observations).read_text(encoding='utf-8')),arena_radius=args.arena_radius)
        (out/'q1.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(result)
    else:
        checks=json.loads((out/'geometry_checks.json').read_text())
        result=solve_q1(checks['counterexample']['observations'])
        assert abs(result['mec_radius']-40/np.sqrt(3))<1e-4
        assert solve_q1([dict(position=[0,0],bearing_deg=30)])['status']=='unbounded'
        (out/'q1.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(q2_example(out)['solutions']))
