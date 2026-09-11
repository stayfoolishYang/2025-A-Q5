"""Fixed-candidate Q2 geometry experiment; never instantiates a simulator."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from functools import lru_cache
import gzip
import hashlib
import heapq
import csv
import json
import math
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

import numpy as np

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from geometry import ERROR_DEG, diameter, intersect_disk, mec, wedge


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def pair_diameter(poly):
    if not len(poly):
        return 0.
    delta = poly[:, None] - poly[None, :]
    return float(np.sqrt(np.sum(delta*delta, axis=2).max()))


def response(source, station, error, quantize):
    """Omnidirectional source with 1500 m receive radius; no API/action call."""
    delta = np.asarray(source)-station
    distance = math.hypot(*delta)
    if distance > 1500:
        return 'no_signal', None
    if distance <= 5:
        return 'near', None
    return 'direction', quantize(math.degrees(math.atan2(delta[1], delta[0])), error)


def continuous_envelope(evaluate, tolerance=.01, max_splits=20000, initial_bins=72):
    """Numerical enclosure for the fixed outer-polygon wedge surrogate ONLY."""
    if initial_bins < 3 or ERROR_DEG+180/initial_bins >= 90:
        raise ValueError('Expanded wedge half-width must be below 90 degrees')
    lower, best_z, nested_residual = 0., 0., 0.
    heap, checkpoints = [], []

    def cell(left, right):
        nonlocal lower, best_z
        mid = (left+right)/2
        value = evaluate(mid, ERROR_DEG)
        if value > lower:
            lower, best_z = value, mid
        upper = evaluate(mid, ERROR_DEG+(right-left)/2)
        if value > upper+1e-6:
            raise ArithmeticError('Expanded wedge lost a center posterior')
        return (-upper, left, right)

    for i in range(initial_bins):
        heapq.heappush(heap, cell(i*360/initial_bins, (i+1)*360/initial_bins))
    splits = 0
    while True:
        upper = -heap[0][0]
        gap = upper-lower
        for threshold in (1., .1, .01):
            if gap <= threshold and not any(c['threshold_m']==threshold for c in checkpoints):
                checkpoints.append(dict(threshold_m=threshold, lower_m=lower, upper_m=upper, splits=splits))
        if gap <= tolerance or splits >= max_splits:
            break
        neg_upper, left, right = heapq.heappop(heap)
        mid = (left+right)/2
        for a, b in ((left, mid), (mid, right)):
            child = cell(a, b)
            residual = -child[0]+neg_upper
            nested_residual = max(nested_residual, residual)
            if residual > 1e-6:
                raise ArithmeticError('Numerical child upper bound exceeds parent')
            heapq.heappush(heap, child)
        splits += 1
    return dict(lower_m=lower, upper_m=upper, gap_m=gap, converged=gap<=tolerance,
                argmax_sampled_report_deg=best_z, splits=splits, checkpoints=checkpoints,
                nesting_residual_m=nested_residual,
                leaves=sorted([[a,b,-u] for u,a,b in heap]))


def source_grid(angles, radii):
    return np.array([[r*math.cos(a),r*math.sin(a)]
                     for a in np.deg2rad(np.linspace(29+1e-10,31-1e-10,angles))
                     for r in np.linspace(5.01,1500-1e-9,radii)])


def initial_compatible(point, quantize):
    radius = math.hypot(*point)
    angle = math.degrees(math.atan2(point[1],point[0]))
    return 5 < radius <= 1500 and abs(angle-30) <= 1+1e-12 and quantize(angle,30-angle)==30.


def evaluate_candidate(task):
    index, row, poly, sim_root = task
    sys.path.insert(0, sim_root)
    from engine import quantize_bearing
    started = time.perf_counter()
    station = np.array([float(row['x']),float(row['y'])])
    counter, max_residual, calipers_residual = 0, 0., 0.
    edges = np.roll(poly,-1,axis=0)-poly
    lengths = np.linalg.norm(edges,axis=1)

    @lru_cache(maxsize=None)
    def evaluate(z, error=ERROR_DEG):
        nonlocal counter, max_residual
        post = wedge(poly,station,z,error)
        counter += 1
        if len(post):
            delta = post[:,None]-poly[None]
            cross = edges[None,:,0]*delta[:,:,1]-edges[None,:,1]*delta[:,:,0]
            residual = max(0.,float((-cross/lengths).max()))
            lo,hi=np.deg2rad([z-error,z+error])
            normals=np.array([[math.sin(lo),-math.cos(lo)],[-math.sin(hi),math.cos(hi)]])
            residual=max(residual,float(((post-station)@normals.T).max()))
            max_residual=max(max_residual,residual)
            if residual > 1e-6:
                raise ArithmeticError('Posterior clipping residual exceeds audit tolerance')
        return pair_diameter(post)

    representatives=np.vstack((poly,poly.mean(axis=0)))
    old, old_z=0.,0.
    for point in representatives:
        z=math.degrees(math.atan2(*(point-station)[::-1]))
        for error in (-ERROR_DEG,0.,ERROR_DEG):
            value=evaluate(z+error)
            post=wedge(poly,station,z+error)
            calipers_residual=max(calipers_residual,abs(value-diameter(post)[0]) if len(post) else 0.)
            if value>old:
                old,old_z=value,z+error
    assert abs(old-float(row['worst_sampled_diameter_m']))<1e-7
    action_time=math.hypot(*station)/5+5
    assert abs(action_time-float(row['action_time_s']))<1e-9
    assert max(np.linalg.norm(poly-station,axis=1))<=1000
    envelope=continuous_envelope(evaluate)
    assert envelope['upper_m']+1e-6>=old

    near_post=intersect_disk(poly,station,5.)
    near_upper=min(10.,pair_diameter(near_post))

    def sample(points, errors):
        worst, witness=0.,None
        counts=dict(direction=0,near=0,no_signal=0)
        reports=set()
        for point in points:
            assert initial_compatible(point,quantize_bearing)
            for error in errors:
                kind,z=response(point,station,float(error),quantize_bearing)
                counts[kind]+=1
                if kind=='no_signal':
                    raise AssertionError('Safe fixed candidate returned no signal')
                if kind=='near':
                    value=near_upper
                else:
                    reports.add(z)
                    value=evaluate(z)
                if value>worst or witness is None:
                    worst=value
                    witness=dict(source=point.tolist(),error_deg=float(error),response=kind,report_deg=z)
        return dict(source_points=len(points),scenario_count=len(points)*len(errors),counts=counts,
                    distinct_reports=len(reports),max_outer_diameter_m=worst,witness=witness)

    coarse=sample(source_grid(9,17),np.linspace(-1,1,5))
    fine=sample(source_grid(17,33),np.linspace(-1,1,9))
    assert fine['max_outer_diameter_m']+1e-6>=coarse['max_outer_diameter_m']
    boundary=[station]
    boundary.extend(station+r*np.array([math.cos(a),math.sin(a)])
                    for r in (4.999,5.,5.001) for a in np.arange(8)*math.pi/4)
    boundary=[p for p in boundary if initial_compatible(p,quantize_bearing)]
    near_cases=sample(boundary,np.array([0.]))
    z=envelope['argmax_sampled_report_deg']
    post=wedge(poly,station,z)
    center,radius=mec(post)
    return dict(index=index,x=float(station[0]),y=float(station[1]),action_time_s=action_time,
                baseline_diameter_m=old,baseline_score_m=old+.2*action_time,
                baseline_argmax_report_deg=old_z,baseline_representative_scenarios=15,
                envelope=envelope,coarse=coarse,fine=fine,near_boundary=near_cases,
                near_outer_upper_m=near_upper,near_outer_intersection_nonempty=bool(len(near_post)),
                all_branch_outer_upper_m=max(envelope['upper_m'],near_upper),
                sampled_argmax_polygon=post.tolist(),sampled_argmax_mec_center=center.tolist(),
                sampled_argmax_mec_radius_m=radius,calipers_max_difference_m=calipers_residual,
                cached_wedge_evaluations=counter,wedge_evaluations=counter+16,
                near_disk_intersections=1,posterior_evaluations=counter+17,
                clip_max_residual_m=max_residual,
                runtime_s=time.perf_counter()-started)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--sim-root',type=Path,default=Path('G:/QQ/jammers_linux'))
    args=parser.parse_args()
    out=args.output.resolve()
    if out.exists():
        raise FileExistsError('Use a new output directory; original results are immutable')
    data=json.loads((BASE/'results/q2.json').read_bytes())
    rows=list(csv.DictReader((BASE/'results/q2_candidates.csv').open(encoding='utf-8-sig')))
    assert len(rows)==213 and len(data['polygon'])==4
    assert data['first_position']==[0.,0.] and data['first_bearing_deg']==30.
    out.mkdir(parents=True)
    (out/'frozen').mkdir();(out/'candidates').mkdir()
    paths=[BASE/'geometry.py',BASE/'questions.py',Path(__file__),
           BASE/'Q2_SCORE_EXPERIMENT_PLAN.md',BASE/'Q2_OPTIMIZATION_READINESS_AUDIT.md',
           BASE/'Q2_READONLY_SCORE_AUDIT.json',BASE/'results/q2.json',BASE/'results/q2_candidates.csv',
           BASE/'tests/test_q2_score_audit.py',args.sim_root/'engine.py']
    files=[]
    for p in paths:
        target=out/'frozen'/p.name
        shutil.copy2(p,target)
        assert target.read_bytes()==p.read_bytes(), 'Source changed while copying: '+str(p)
        files.append(dict(source=str(p.resolve()),frozen=target.relative_to(out).as_posix(),
                          sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
    save(out/'PLAN.json',dict(schema='q2-fixed-candidate-score-v1',created_utc=datetime.now(timezone.utc).isoformat(),
         git_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),files=files,
         candidate_count=213,lambda_m_per_s=.2,primary='second-observation outer-region diameter',
         envelope=dict(tolerance_m=.01,max_splits=20000,initial_bins=72),
         coarse=dict(angles=9,radii=17,errors=5),fine=dict(angles=17,radii=33,errors=9),
         error_deg=ERROR_DEG,python=sys.version,numpy=np.__version__,platform=platform.platform(),
         workers=args.workers,solver_runs=0,simulator_runs=0,official_calls=0))
    assert json.loads((out/'frozen/q2.json').read_bytes())==data
    assert list(csv.DictReader((out/'frozen/q2_candidates.csv').open(encoding='utf-8-sig')))==rows
    poly=np.array(data['polygon'])
    started=time.perf_counter()
    tasks=[(i,row,poly,str(args.sim_root.resolve())) for i,row in enumerate(rows)]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(evaluate_candidate,t):t[0] for t in tasks}
        completed=[]
        for future in as_completed(futures):
            result=future.result();i=result['index']
            with gzip.open(out/'candidates'/f'{i:03d}.json.gz','wt',encoding='utf-8') as f:
                json.dump(result,f,ensure_ascii=False,allow_nan=False)
            completed.append(result)
            if len(completed)%20==0 or len(completed)==213:
                print(f'Completed {len(completed)}/213 candidates',flush=True)
    for item in files:
        assert hashlib.sha256(Path(item['source']).read_bytes()).hexdigest()==item['sha256']
    save(out/'COMPLETED.json',dict(candidates=len(completed),runtime_s=time.perf_counter()-started,
         all_envelopes_converged=all(r['envelope']['converged'] for r in completed),
         posterior_evaluations=sum(r['posterior_evaluations'] for r in completed),
         cached_wedge_evaluations=sum(r['cached_wedge_evaluations'] for r in completed),
         wedge_evaluations=sum(r['wedge_evaluations'] for r in completed),near_disk_intersections=213,
         common_scenarios=sum(r['coarse']['scenario_count']+r['fine']['scenario_count'] for r in completed),
         boundary_scenarios=sum(r['near_boundary']['scenario_count'] for r in completed),
         original_inputs_unchanged=True,solver_runs=0,simulator_runs=0,official_calls=0))
    print(str(out/'COMPLETED.json'),flush=True)


if __name__=='__main__':
    main()
