"""Continuous convex clear neighborhoods; only hard polygon vertices are inputs."""
import time
import numpy as np
from scipy.optimize import minimize
from geometry import is_certified_clear_point, exact_squared_distance
from fractions import Fraction

R_CLEAR=20.
R_CERT=19.999  # Preserve R12's 1 mm safety margin.
TOL=1e-9
def length(x,q,u=None):
    return float(np.linalg.norm(q-x)+(0. if u is None else np.linalg.norm(q-u)))

def segment_point(x,u,centers,radii):
    """Earliest point of [x,u] in every closed disk, without a spatial grid."""
    if u is None:return None
    d=u-x;a=float(d@d);lo,hi=0.,1.
    if a==0:return x.copy() if np.all(np.linalg.norm(centers-x,axis=1)<=radii) else None
    for c,r in zip(centers,radii):
        b=float((x-c)@d);cc=float((x-c)@(x-c)-r*r);disc=b*b-a*cc
        if disc<0:return None
        root=np.sqrt(max(0.,disc));lo=max(lo,(-b-root)/a);hi=min(hi,(-b+root)/a)
        if lo>hi:return None
    return x+lo*d

def choose(poly,x,m,rho,u=None,mode='MEC',optimizer=minimize):
    wall,cpu=time.perf_counter(),time.process_time()
    poly,x,m=np.asarray(poly,float),np.asarray(x,float),np.asarray(m,float)
    u=None if u is None else np.asarray(u,float)
    if mode not in ('MEC','EXACT'):raise ValueError('Unknown neighborhood')
    if not np.isfinite(rho) or rho < 0 or R_CERT-rho < -TOL:raise RuntimeError('HARD_FAIL_NEGATIVE_SAFE_RADIUS')
    if not is_certified_clear_point(poly,m,rho) or not is_certified_clear_point(poly,m,R_CERT):raise RuntimeError('HARD_FAIL_BASELINE_CERTIFICATE')
    r=max(0.,R_CERT-rho);baseline=length(x,m,u)
    centers,radii=(m[None,:],np.array([r])) if mode=='MEC' else (poly,np.full(len(poly),R_CERT))
    fallback=False;reason='';status='';nit=0;candidate=m.copy()
    def safe(q):
        if q.shape!=(2,) or not np.isfinite(q).all() or not is_certified_clear_point(poly,q,R_CERT):return False
        if mode=='MEC' and exact_squared_distance(q,m)>Fraction(r)**2:return False
        return length(x,q,u)<=baseline
    try:
        if mode=='MEC' and r<=TOL:status='ZERO_RADIUS'
        else:
            candidate=segment_point(x,u,centers,radii)
            if candidate is not None:status='SEGMENT_GLOBAL_OPTIMUM'
            elif u is None and mode=='MEC':
                d=float(np.linalg.norm(x-m));candidate=x.copy() if d<=r else m+(x-m)*(r/d);status='ANALYTIC_PROJECTION'
            else:
                # Translation keeps the 2-variable convex problem well-scaled.
                def obj(v):return length(x,m+v,u)
                def jac(v):
                    q=m+v;g=(q-x)/max(np.linalg.norm(q-x),1e-30)
                    return g if u is None else g+(q-u)/max(np.linalg.norm(q-u),1e-30)
                cc=centers-m
                def fun(v):return (radii*radii-np.sum((v-cc)**2,axis=1))/40.
                def cjac(v):return -(v-cc)/20.
                opt=optimizer(obj,np.zeros(2),jac=jac,method='SLSQP',constraints=[dict(type='ineq',fun=fun,jac=cjac)],options=dict(ftol=1e-11,maxiter=200))
                nit=int(opt.nit);status=str(opt.message)
                if not opt.success:raise ValueError('OPTIMIZER_FAILURE:'+status)
                candidate=m+np.asarray(opt.x,float)
            if candidate.shape!=(2,) or not np.isfinite(candidate).all():raise ValueError('NONFINITE_OUTPUT')
            # Reject infeasible optimizer output; tiny roundoff only is contracted.
            if np.any(np.linalg.norm(centers-candidate,axis=1)>radii+1e-7):raise ValueError('INFEASIBLE_OUTPUT')
            for step in (0.,1e-10,1e-8,1e-6):
                q=candidate+step*(m-candidate)
                if safe(q):candidate=q;break
            else:raise ValueError('NUMERICAL_MARGIN_OR_LOCAL_DOMINANCE')
        if not safe(candidate):raise ValueError('FINAL_CERTIFICATE_FAILURE')
    except (ValueError,ArithmeticError,RuntimeError,np.linalg.LinAlgError) as e:
        fallback=True;reason=str(e)
        if mode=='EXACT':candidate,sub=choose(poly,x,m,rho,u,'MEC',optimizer);status='FALLBACK_MEC:'+sub['status']
        else:candidate=m.copy();status='FALLBACK_R12'
    if not safe(candidate):raise RuntimeError('HARD_FAIL_FALLBACK')
    value=length(x,candidate,u)
    # Convex first-order lower bound; exact region lies inside ANY vertex disk.
    g=(candidate-x)/max(np.linalg.norm(candidate-x),1e-30)
    if u is not None:g=g+(candidate-u)/max(np.linalg.norm(candidate-u),1e-30)
    lower=max(float(value+g@(c-candidate)-rad*np.linalg.norm(g)) for c,rad in zip(centers,radii))
    lower=max(lower,0. if u is None else float(np.linalg.norm(x-u)))
    return candidate,dict(status=status,fallback=fallback,fallback_reason=reason,iterations=nit,model=mode,safe_radius=r,physical_safe_radius=R_CLEAR-rho,baseline_local_length=baseline,optimized_local_length=value,local_saving=baseline-value,optimality_gap_bound=max(0.,value-lower),feasibility_margin=R_CLEAR-float(np.linalg.norm(poly-candidate,axis=1).max()),optimization_wall_s=time.perf_counter()-wall,optimization_cpu_s=time.process_time()-cpu)
