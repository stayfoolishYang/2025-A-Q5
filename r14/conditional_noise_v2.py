"""Persistent smooth noise conditioned on observed rounded bearings.

Planning approximation: independent bounded grid prior instead of the simulator's
hash-generated grid. Does not consume the evaluation scene or its noise seed.
"""
import math
import numpy as np
from scipy.optimize import linprog

def weights(point):
    gx,gy=np.asarray(point)/150.;ix,iy=math.floor(gx),math.floor(gy)
    fx,fy=gx-ix,gy-iy;sx,sy=fx*fx*(3-2*fx),fy*fy*(3-2*fy)
    return {(ix,iy):(1-sx)*(1-sy),(ix+1,iy):sx*(1-sy),
            (ix,iy+1):(1-sx)*sy,(ix+1,iy+1):sx*sy}

class ConditionalNoise:
    def __init__(self,source_position,history,seed):
        self.rng=np.random.default_rng(seed);self.grid={};constraints=[]
        for point,result,angle in history:
            if result!='direction':continue
            delta=np.asarray(source_position)-point
            base=math.degrees(math.atan2(delta[1],delta[0]))%360
            # Invert the frozen round-then-clamp report, including 0/360 wrap.
            target=int(round(angle*100))+36000*int(round((base-angle)/360))
            lower_report=math.ceil((base-1)*100)
            upper_report=math.floor((base+1)*100)
            if not lower_report<=target<=upper_report:
                raise ValueError('Report outside physical quantizer support')
            lo=-1. if target==lower_report else max(-1.,(target-.5)/100-base+1e-9)
            hi=1. if target==upper_report else min(1.,(target+.5)/100-base-1e-9)
            if lo>hi:raise ValueError('Source incompatible with bearing interval')
            constraints.append((weights(point),lo,hi))
        keys=sorted({k for w,_,_ in constraints for k in w});n=len(keys)
        if not n:return
        idx={k:i for i,k in enumerate(keys)};rows=[];bounds=[]
        for w,lo,hi in constraints:
            row=np.zeros(n)
            for k,v in w.items():row[idx[k]]=v
            rows.extend([row,-row]);bounds.extend([hi,-lo])
        A=np.asarray(rows);rhs=np.asarray(bounds)
        # Chebyshev centre gives a nondegenerate start for hit-and-run.
        norms=np.linalg.norm(A,axis=1)
        mat=np.column_stack((A,norms))
        box=np.vstack((np.eye(n),-np.eye(n)))
        mat=np.vstack((mat,np.column_stack((box,np.ones(2*n)))))
        rhs=np.r_[rhs,np.ones(2*n)]
        solved=linprog(np.r_[np.zeros(n),-1.],A_ub=mat,b_ub=rhs,
                       bounds=[(None,None)]*n+[(0,None)],method='highs')
        if not solved.success:raise ValueError('No compatible persistent grid')
        x=solved.x[:n];A=mat[:,:n]
        # Fixed work, not a convergence claim. Conditional spatial likelihood
        # volumes are not integrated: expose this approximation in rollout audit.
        for _ in range(128):
            direction=self.rng.normal(size=n);direction/=np.linalg.norm(direction)
            slope=A@direction;slack=rhs-A@x
            upper=np.min(slack[slope>1e-14]/slope[slope>1e-14],initial=np.inf)
            lower=np.max(slack[slope < -1e-14]/slope[slope < -1e-14],initial=-np.inf)
            if lower<=upper:x+=self.rng.uniform(lower,upper)*direction
        if np.max(A@x-rhs)>1e-7:raise ValueError('Conditional grid numerical violation')
        self.grid=dict(zip(keys,x))
        # Exact report equality remains the acceptance rule; never widen tolerance.
        from engine import quantize_bearing
        for point,result,angle in history:
            if result=='direction':
                dx,dy=np.asarray(source_position)-point
                base=math.degrees(math.atan2(dy,dx))%360
                if quantize_bearing(base,self.value(point))!=angle:
                    raise ValueError('Exact quantizer replay failed')
    def value(self,point):
        w=weights(point)
        for k in sorted(w):
            if k not in self.grid:self.grid[k]=self.rng.uniform(-1,1)
        return sum(self.grid[k]*v for k,v in w.items())
