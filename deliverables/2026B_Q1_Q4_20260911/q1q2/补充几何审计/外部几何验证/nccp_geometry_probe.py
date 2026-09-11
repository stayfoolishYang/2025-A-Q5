"""Standalone NCCP research probe; NO simulator / network / project imports.

The finite-candidate construction is an exact geometric method in real arithmetic.
The implementation is FP64 and is NOT an exact optimizer.  Returned feasibility
and non-worsening versus the supplied witness are checked with exact rational
arithmetic for the *represented input/output floats*, not for upstream geometry.
The witness must already be certified.  Unresolved cases return that witness.
Run: python nccp_geometry_probe.py --out results.json
Dependencies: numpy, scipy (scipy is only used for a numerical cross-check).
"""
from __future__ import annotations
import argparse
from fractions import Fraction as F
from itertools import combinations
import json
from pathlib import Path
import platform
import time
import numpy as np
from scipy.optimize import minimize
import scipy


def exact_sqdist(a, b):
    return sum((F(float(ai))-F(float(bi)))**2 for ai, bi in zip(a,b))


def certified(vertices, q, r):
    rr=F(str(r))**2
    return all(exact_sqdist(v, q) <= rr for v in vertices)


def prepare(vertices, x, witness, r):
    vs=np.asarray(vertices, dtype=float)
    x=np.asarray(x, dtype=float); w=np.asarray(witness, dtype=float)
    if vs.ndim!=2 or vs.shape[1]!=2 or len(vs)==0:
        raise ValueError('Expected a nonempty (n,2) vertex array.')
    if x.shape!=(2,) or w.shape!=(2,):
        raise ValueError('Positions must have shape (2,).')
    if not (np.isfinite(vs).all() and np.isfinite(x).all() and np.isfinite(w).all() and np.isfinite(r) and r>0):
        raise ValueError('Nonfinite values or invalid radius.')
    if not certified(vs,w,r):
        raise ValueError('Witness not certified; do NOT issue a clear.')
    return vs,x,w


def finish(vs,x,w,r,candidates):
    # Candidate generation may contain tiny arithmetic violations.  Never certify
    # them with a positive tolerance: try interpolation toward the safe witness.
    base_d2=exact_sqdist(x,w)
    candidates=sorted(candidates,key=lambda a:(float(np.dot(a[0]-x,a[0]-x)),a[1],float(a[0][0]),float(a[0][1])))
    best=w.copy(); status='witness_fallback'; best_d2=base_d2
    for q, name in candidates:
        if not np.isfinite(q).all():
            continue
        if float(np.dot(q-x,q-x))>float(base_d2)+1e-7:
            continue
        for alpha in (0.,1e-14,1e-12,1e-10,1e-8,1e-6):
            candidate=q if alpha==0 else (1-alpha)*q+alpha*w
            # Use the coordinates actually serialized to JSON.
            candidate=np.array(json.loads(json.dumps(candidate.tolist(),allow_nan=False)))
            if certified(vs,candidate,r):
                d2=exact_sqdist(candidate,x)
                if d2<best_d2:
                    best=candidate; best_d2=d2
                    status=name if alpha==0 else name+'_inward_repaired'
                break
    return best, status


def segment_entry(vertices,x,witness,r=19.999):
    vs,x,w=prepare(vertices,x,witness,r)
    if certified(vs,x,r): return x.copy(),'already_feasible'
    d=w-x; a=float(np.dot(d,d))
    if a==0: return w.copy(),'witness_fallback'
    t=0.
    for v in vs:
        z=x-v; b=2*float(np.dot(d,z)); c=float(np.dot(z,z)-r*r)
        disc=b*b-4*a*c
        if disc<0: return w.copy(),'witness_fallback'
        # First root of the quadratic along x+t(w-x). Witness at t=1 is feasible.
        root=(-b-np.sqrt(disc))/(2*a)
        t=max(t,root)
    if not 0<=t<=1: return w.copy(),'witness_fallback'
    q=x+t*d
    return finish(vs,x,w,r,[(q,'segment_entry')])


def nccp(vertices,x,witness,r=19.999):
    vs,x,w=prepare(vertices,x,witness,r)
    if certified(vs,x,r): return x.copy(),'already_feasible'
    unique=np.unique(vs,axis=0)
    candidates=[(w.copy(),'witness')]
    seg,_=segment_entry(vs,x,w,r)
    candidates.append((seg,'segment_candidate'))
    # Tolerance is for retaining construction candidates only, never certification.
    construction_tol=1e-9
    for v in unique:
        d=x-v; norm=float(np.linalg.norm(d))
        if norm>r:
            q=v+(r/norm)*d
            if np.max(np.linalg.norm(vs-q,axis=1))<=r+construction_tol:
                candidates.append((q,'one_active_disk'))
    for a,b in combinations(unique,2):
        d=b-a; length=float(np.linalg.norm(d))
        if length==0 or length>2*r: continue
        half=length/2; h2=(r-half)*(r+half)
        if h2<0: continue
        midpoint=(a+b)/2; normal=np.array([-d[1],d[0]])/length
        for sign in (-1.,1.):
            q=midpoint+sign*np.sqrt(h2)*normal
            if np.max(np.linalg.norm(vs-q,axis=1))<=r+construction_tol:
                candidates.append((q,'two_active_disks'))
    return finish(vs,x,w,r,candidates)


def reference(vs,x,w,r):
    # Normalize to improve SLSQP conditioning.  A numerical cross-check, not proof.
    v=(vs-w)/r; z=(x-w)/r
    fun=lambda q:.5*np.dot(q-z,q-z)
    jac=lambda q:q-z
    cons={'type':'ineq','fun':lambda q:1-np.sum((q-v)**2,axis=1),
          'jac':lambda q:-2*(q-v)}
    out=minimize(fun,np.zeros(2),jac=jac,constraints=cons,method='SLSQP',
                 options={'ftol':1e-12,'maxiter':300})
    q=w+r*out.x
    return {'success':bool(out.success),'message':str(out.message),
            'distance_m':float(np.linalg.norm(q-x)),
            'max_violation_m':float(np.max(np.linalg.norm(vs-q,axis=1))-r)}


def run():
    r=19.999; rng=np.random.default_rng(240911)
    samples=[]
    # Synthetic polygon states with known MEC centre from diametric supports.
    for k in range(120):
        centre=rng.uniform(-1800,1800,2)
        angle=rng.uniform(-np.pi,np.pi)
        u=np.array([np.cos(angle),np.sin(angle)])
        R=r*rng.uniform(.05,.995)
        extra=rng.normal(size=(int(rng.integers(1,12)),2))
        extra=extra/np.linalg.norm(extra,axis=1)[:,None]
        extra*=rng.uniform(0,.98*R,len(extra))[:,None]
        vs=np.vstack([centre+R*u,centre-R*u,centre+extra])
        x=centre+rng.uniform(-80,80,2)
        t0=time.perf_counter(); q,status=nccp(vs,x,centre,r)
        elapsed=time.perf_counter()-t0
        seg,sstatus=segment_entry(vs,x,centre,r)
        base=float(np.linalg.norm(x-centre)); dist=float(np.linalg.norm(x-q))
        delta=(base-dist)/5
        bound=float(np.sqrt(max(0,r*r-R*R))/5)
        item={'id':k,'m':len(vs),'R_m':float(R),'status':status,
              'certified_exact_for_binary_inputs':certified(vs,q,r),
              'local_nonworsening_exact':exact_sqdist(x,q)<=exact_sqdist(x,centre),
              'savings_s':delta,'refined_upper_bound_s':bound,
              'bound_holds_with_1e-8s_numeric_margin':delta<=bound+1e-8,
              'segment_distance_m':float(np.linalg.norm(x-seg)),
              'nccp_distance_m':dist,'probe_compute_s':elapsed}
        if k<30: item['independent_slsqp']=reference(vs,x,centre,r)
        samples.append(item)
    fixtures=[
        ('single_point',[[0,0]],[100,0],[0,0]),
        ('duplicate_points',[[0,0],[0,0],[0,0]],[100,0],[0,0]),
        ('already_safe',[[-10,0],[10,0],[0,5]],[0,1],[0,0]),
        ('near_tangent',[[-(r-1e-7),0],[r-1e-7,0]],[0,50],[0,0]),
        ('collinear',[[-10,0],[0,0],[10,0]],[40,20],[0,0]),
    ]
    checks=[]
    for name,vs,x,w in fixtures:
        q,status=nccp(vs,x,w,r)
        checks.append({'name':name,'point':q.tolist(),'status':status,
                       'certified':certified(vs,q,r),
                       'nonworsening':exact_sqdist(x,q)<=exact_sqdist(x,w)})
    # Exact tangent with integer radius so the singleton is exactly representable.
    q,status=nccp([[-20,0],[20,0]],[0,50],[0,0],20.)
    checks.append({'name':'exact_tangent_r20','point':q.tolist(),'status':status,
                   'certified':certified([[-20,0],[20,0]],q,20.),'nonworsening':exact_sqdist(q,[0,0])==0})
    invalid=[]
    for name,vs,w in [('empty',[],[0,0]),('infeasible_witness',[[-21,0],[21,0]],[0,0]),('nan',[[float('nan'),0]],[0,0])]:
        try:
            nccp(vs,[40,20],w,r); invalid.append({'name':name,'rejected':False})
        except ValueError:
            invalid.append({'name':name,'rejected':True})
    # Counterexample: local leg shorter but even a fixed two-leg route gets longer.
    vs=r*np.array([[-.5,0],[.5,0],[0,.25]])
    x=r*np.array([39.5,30.0]); m=np.zeros(2)
    exact_formula_q=r*np.array([.3,.6]); y=-exact_formula_q
    q,status=nccp(vs,x,m,r)
    seg,_=segment_entry(vs,x,m,r)
    route=lambda c:float(np.linalg.norm(x-c)+np.linalg.norm(c-y))
    counter={'radius_m':r,'vertices':vs.tolist(),'x':x.tolist(),'mec_center':m.tolist(),
             'nccp_formula':[.3*r,.6*r],'nccp_verified':q.tolist(),'next_waypoint':y.tolist(),
             'local_mec_distance_m':float(np.linalg.norm(x-m)),
             'local_nccp_distance_m':float(np.linalg.norm(x-q)),
             'two_leg_mec_distance_m':route(m),'two_leg_nccp_distance_m':route(q),
             'two_leg_segment_distance_m':route(seg),
             'two_leg_nccp_regression_s':(route(q)-route(m))/5,
             'current_bearing_angles_deg':(np.degrees(np.arctan2((vs-x)[:,1],(vs-x)[:,0]))%360).tolist(),
             'distances_from_current_position_m':np.linalg.norm(vs-x,axis=1).tolist(),
             'meaning':'Geometric construction compatible with one current bounded bearing and 1000m reception; NOT a simulator run.'}
    refs=[a for a in samples if 'independent_slsqp' in a]
    validrefs=[a for a in refs if a['independent_slsqp']['success'] and a['independent_slsqp']['max_violation_m']<=1e-7]
    summary={'scope':'Standalone synthetic geometry only; no B solver modification; no simulator calls.',
             'synthetic_polygon_cases':len(samples),'analytical_or_degenerate_fixtures':len(checks),
             'invalid_inputs_rejected':sum(i['rejected'] for i in invalid),
             'exact_feasibility_passed':sum(i['certified_exact_for_binary_inputs'] for i in samples),
             'exact_local_nonworsening_passed':sum(i['local_nonworsening_exact'] for i in samples),
             'refined_bound_numeric_checks_passed':sum(i['bound_holds_with_1e-8s_numeric_margin'] for i in samples),
             'numerical_slsqp_comparisons':len(refs),'numerically_valid_slsqp_results':len(validrefs),
             'max_reference_distance_difference_m':max(abs(a['nccp_distance_m']-a['independent_slsqp']['distance_m']) for a in validrefs),
             'median_probe_compute_ms':float(np.median([a['probe_compute_s'] for a in samples])*1000),
             'max_probe_compute_ms':float(max(a['probe_compute_s'] for a in samples)*1000),
             'limits':'Exact rational checks certify only represented vertices/output points. Candidate optimization, upstream outer approximation, HTTP handling, and end-to-end performance are NOT formally certified.'}
    return {'summary':summary,'environment':{'python':platform.python_version(),'numpy':np.__version__,'scipy':scipy.__version__},
            'counterexample':counter,'fixtures':checks,'invalid_inputs':invalid,'samples':samples,
            'savings_bound_examples':[{'R_m':R,'bound_s':float(np.sqrt(max(0,r*r-R*R))/5)} for R in [0,10,19,19.9,r]]}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',default='results.json');args=p.parse_args()
    report=run(); Path(args.out).write_text(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    print(json.dumps(report['summary'],indent=2,ensure_ascii=False));print(json.dumps(report['counterexample'],indent=2,ensure_ascii=False))
