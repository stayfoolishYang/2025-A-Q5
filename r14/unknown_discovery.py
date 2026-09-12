"""Unknown-source discovery under declared independent parameter priors."""
import math
import numpy as np
from scipy.stats import qmc
from receive_integral import integrate
from weighted_world_sampler import WeightedWorldSampler,SamplingUnavailable

def geometry_integrals(points,history,nodes):
    points=np.asarray(points);nodes=np.asarray(nodes);n=len(points);tau=2*np.pi
    qdiff=nodes[None,:,:]-points[:,None,:];qd=np.linalg.norm(qdiff,axis=2);qa=np.arctan2(qdiff[:,:,1],qdiff[:,:,0])%tau
    h=np.array(list(dict.fromkeys(tuple(p) for p in history))).reshape(-1,2)
    if len(h):
        diff=h[None,:,:]-points[:,None,:];d=np.linalg.norm(diff,axis=2);angles=np.arctan2(diff[:,:,1],diff[:,:,0])%tau
        upper=np.minimum(1500,d.min(axis=1));cuts=np.sort(np.c_[np.zeros(n),np.full(n,tau),(angles-np.pi/2)%tau,(angles+np.pi/2)%tau],axis=1)
    else:
        d=np.empty((n,0));angles=d.copy();upper=np.full(n,1500.);cuts=np.tile([0.,tau],(n,1))
    den=.5*np.maximum(0,upper-1000)/500;num=.5*np.maximum(0,upper[:,None]-np.maximum(1000,qd))/500
    for j in range(cuts.shape[1]-1):
        a=cuts[:,j];b=cuts[:,j+1];mid=(a+b)/2
        hi=np.minimum(1500,np.min(np.where((np.cos(mid[:,None]-angles)>=0)|(d==0),d,np.inf),axis=1,initial=np.inf))
        den+=.5*(b-a)/tau*np.maximum(0,hi-1000)/500
        overlap=np.zeros_like(qd)
        for k in [-1,0,1]:overlap+=np.maximum(0,np.minimum(b[:,None],qa+np.pi/2+k*tau)-np.maximum(a[:,None],qa-np.pi/2+k*tau))
        overlap=np.where(qd==0,(b-a)[:,None],overlap)
        num+=.5*overlap/tau*np.maximum(0,hi[:,None]-np.maximum(1000,qd))/500
    return den,num

def coefficients(values):
    a=np.zeros(len(values)+1);a[0]=1
    for i,v in enumerate(values):a[1:i+2]+=v*a[:i+1].copy()
    return a

class UnknownPosterior:
    def __init__(self,sampler,nodes,seed,power=12):
        self.channels=[c for c in range(1,21) if c not in sampler.known];self.k=len(sampler.known);self.groups={};self.channel_group={}
        for c in self.channels:
            if any(r!='no_signal' for p,r,a in sampler.hist[c]):raise ValueError('Unknown channel has positive history')
            key=tuple(tuple(p) for p,r,a in sampler.hist[c]);self.groups.setdefault(key,[]).append(c);self.channel_group[c]=key
        self.data={};L=[];joint=[]
        for j,(h,cs) in enumerate(self.groups.items()):
            u=qmc.Sobol(2,scramble=True,seed=(int(seed)+j)%2**32).random_base2(power);r=1800*np.sqrt(u[:,0]);theta=2*np.pi*u[:,1];points=np.c_[r*np.cos(theta),r*np.sin(theta)]
            den,num=geometry_integrals(points,h,nodes);self.data[h]=dict(points=points,weights=den,L=float(den.mean()),joint=num.mean(axis=0))
        for c in self.channels:
            g=self.data[self.channel_group[c]];L.append(g['L']);joint.append(g['joint'])
        self.L=np.array(L);self.m=np.arange(max(0,10-self.k),17-self.k)
        comb=np.array([math.comb(20,self.k+int(m)) for m in self.m]);coef=coefficients(self.L);mass=coef[self.m]/comb;self.Z=float(mass.sum())
        if self.Z<=0:raise SamplingUnavailable('Zero count posterior evidence')
        self.pm=mass/self.Z
        self.pnew=np.zeros(len(nodes))
        for q in range(len(nodes)):
            nohit=np.maximum(0,self.L-np.array([v[q] for v in joint]));self.pnew[q]=1-float((coefficients(nohit)[self.m]/comb).sum())/self.Z
        self.pnew=np.clip(self.pnew,0,1)
    def subset(self,rng):
        count=int(rng.choice(self.m,p=self.pm));n=len(self.L);dp=np.zeros((n+1,n+1));dp[n,0]=1
        for i in range(n-1,-1,-1):dp[i]=dp[i+1];dp[i,1:]+=self.L[i]*dp[i+1,:-1]
        selected=[]
        for i,c in enumerate(self.channels):
            if count and rng.random()<self.L[i]*dp[i+1,count-1]/dp[i,count]:selected.append(c);count-=1
        assert count==0
        return selected

class DiscoveryWorldSampler(WeightedWorldSampler):
    def __init__(self,actions,nodes,seed,power=12):
        super().__init__(actions);self.unknown=UnknownPosterior(self,nodes,seed,power)
    def unknown_subset(self,rng):
        selected=self.unknown.subset(rng);states=[]
        for c in selected:
            h=self.unknown.channel_group[c];g=self.unknown.data[h];p=g['points'][rng.choice(len(g['points']),p=g['weights']/g['weights'].sum())]
            history=[(np.array(pos),'no_signal',None) for pos in h];den,_,parts=integrate(p,history,[],np.empty((0,2)),True)
            if den<=0:raise SamplingUnavailable('Unknown conditional mass zero')
            kind,a,b,lo,hi,_=parts[rng.choice(len(parts),p=np.array([v[-1] for v in parts])/den)]
            states.append([p[0],p[1],rng.uniform(lo,hi),int(kind),rng.uniform(a,b)])
        self.belief.states=np.array(states).reshape(-1,5)
        for i,c in enumerate(selected):self.belief.masks[c]=np.arange(len(selected))==i
        return selected
