"""Importance sampling of persistent-grid likelihood, without MCMC.

Target: independent Uniform[-1,1] grid variables conditioned on exact reports.
For a fixed source, each row is a slab lo <= A eta <= hi. Variables are sampled
uniformly from intervals constrained by every row completed at that step.
p_prior/q is the product of interval widths/2, including shared variables once.
The volume estimate (mean weight, including zero weights) is unbiased before
floating-point effects; normalized posterior sampling is a finite IS approximation.
"""
import math
import numpy as np
from conditional_noise import weights
from engine import quantize_bearing

class GridMeasure:
    def __init__(self,position,history):
        self.position=np.asarray(position);self.history=history;rows={};self.impossible=False
        for point,result,angle in history:
            if result!='direction':continue
            dx,dy=self.position-point;base=math.degrees(math.atan2(dy,dx))%360
            target=int(round(angle*100))+36000*int(round((base-angle)/360))
            low=math.ceil((base-1)*100);high=math.floor((base+1)*100)
            if not low<=target<=high:self.impossible=True;break
            lo=-1. if target==low else max(-1.,(target-.5)/100-base)
            hi=1. if target==high else min(1.,(target+.5)/100-base)
            row=tuple(sorted((k,v) for k,v in weights(point).items() if v!=0))
            if row in rows:lo=max(lo,rows[row][0]);hi=min(hi,rows[row][1])
            rows[row]=(lo,hi)
            if lo>=hi:self.impossible=True
        self.keys=sorted({k for row in rows for k,v in row})
        self.A=np.zeros((len(rows),len(self.keys)));self.lo=[];self.hi=[]
        for i,(row,(lo,hi)) in enumerate(rows.items()):
            for k,v in row:self.A[i,self.keys.index(k)]=v
            self.lo.append(lo);self.hi.append(hi)
        self.lo=np.array(self.lo);self.hi=np.array(self.hi)
        self.order=self.variable_order(self.A)

    @staticmethod
    def variable_order(A):
        # Peel private variables last, so each sparse row can constrain its pivot.
        pending=set(range(len(A)));remaining=set(range(A.shape[1]));last=[]
        while pending:
            choices=[]
            for j in remaining:
                rr=[i for i in pending if A[i,j]!=0]
                if len(rr)==1:choices.append((abs(A[rr[0],j]),j,rr[0]))
            if not choices:break
            _,j,i=max(choices);last.append(j);remaining.remove(j);pending.remove(i)
        return sorted(remaining)+list(reversed(last))

    def draw(self,n,seed):
        rng=np.random.default_rng(seed);d=len(self.keys);X=np.zeros((n,d));logw=np.zeros(n)
        if self.impossible:return X,np.full(n,-np.inf)
        A=self.A[:,self.order];completion=np.max(np.where(A!=0,np.arange(d),-1),axis=1) if len(A) else []
        Y=np.zeros_like(X)
        for j in range(d):
            lower=np.full(n,-1.);upper=np.full(n,1.)
            for i in np.flatnonzero(completion==j):
                rest=Y[:,:j]@A[i,:j];coef=A[i,j]
                aa=(self.lo[i]-rest)/coef;bb=(self.hi[i]-rest)/coef
                lower=np.maximum(lower,np.minimum(aa,bb));upper=np.minimum(upper,np.maximum(aa,bb))
            width=np.maximum(0.,upper-lower)
            with np.errstate(divide='ignore'):logw+=np.log(width/2)
            Y[:,j]=lower+rng.random(n)*width
        X[:,self.order]=Y
        # Exact final replay; endpoints have zero target measure.
        for point,result,angle in self.history:
            if result!='direction':continue
            dx,dy=self.position-point;base=math.degrees(math.atan2(dy,dx))%360
            w=weights(point);coef=np.array([w.get(k,0.) for k in self.keys]);errors=X@coef
            valid=np.array([quantize_bearing(base,float(e))==angle for e in errors])
            logw[~valid]=-np.inf
        return X,logw

    def draw_pivot(self,n,seed):
        """Change variables to independent measured errors plus free grid values.

        eta_pivot = B^-1(z - A_free eta_free). The Jacobian is 1/|det B|.
        Uniform z in report slabs handles correlated narrow constraints jointly.
        Remaining constraints and the grid box are checked, not approximated.
        """
        rng=np.random.default_rng(seed);d=len(self.keys);X=np.zeros((n,d))
        if self.impossible:return X,np.full(n,-np.inf)
        if not len(self.A):return rng.uniform(-1,1,(n,d)),np.zeros(n)
        def independent_columns(M):
            residual=M.astype(float).copy();selected=[]
            threshold=np.linalg.norm(M)*max(M.shape)*np.finfo(float).eps
            for _ in range(min(M.shape)):
                norms=np.linalg.norm(residual,axis=0);j=int(np.argmax(norms))
                if norms[j]<=threshold:break
                selected.append(j);v=residual[:,j]/norms[j]
                for _ in range(2):residual-=np.outer(v,v@residual)
            return selected
        rows=independent_columns(self.A.T);rank=len(rows)
        C=self.A[rows];pivots=independent_columns(C)
        if len(pivots)!=rank:raise ValueError('Ill-conditioned importance basis')
        free=[j for j in range(d) if j not in pivots];B=C[:,pivots]
        sign,logdet=np.linalg.slogdet(B)
        if not sign:raise ValueError('Singular importance proposal')
        widths=self.hi[rows]-self.lo[rows]
        if np.any(widths<=0):return X,np.full(n,-np.inf)
        X[:,free]=rng.uniform(-1,1,(n,len(free)))
        Z=self.lo[rows]+rng.random((n,rank))*widths
        X[:,pivots]=np.linalg.solve(B,(Z-X[:,free]@C[:,free].T).T).T
        logconstant=float(np.log(widths/2).sum()-logdet)
        logw=np.full(n,logconstant)
        values=X@self.A.T
        valid=(np.abs(X)<=1).all(axis=1)&(values>=self.lo).all(axis=1)&(values<=self.hi).all(axis=1)
        for point,result,angle in self.history:
            if result!='direction':continue
            dx,dy=self.position-point;base=math.degrees(math.atan2(dy,dx))%360
            w=weights(point);errors=X@np.array([w.get(k,0.) for k in self.keys])
            valid &= np.array([quantize_bearing(base,float(e))==angle for e in errors])
        logw[~valid]=-np.inf
        return X,logw

def summarize(logw):
    from scipy.special import logsumexp
    if not np.isfinite(logw).any():return dict(log_volume=-math.inf,ess=0.,positive=0,relative_se=None)
    z=logsumexp(logw);w=np.exp(logw-z);n=len(w)
    ess=float(1/(w@w))
    return dict(log_volume=float(z-math.log(n)),ess=ess,positive=int(np.isfinite(logw).sum()),relative_se=float(math.sqrt(max(0.,n/ess-1)/(n-1))) if n>1 else None)

