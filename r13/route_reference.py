"""Frozen deterministic open-route references. Float64 numerical optimization."""
import numpy as np
from numba import njit

@njit(cache=True)
def length(order,d):
    value=0.;last=0
    for j in order:value+=d[last,j];last=j
    return value

@njit(cache=True)
def improve(order,d):
    p=order.copy();n=len(p)
    while True:
        changed=False
        for i in range(n-1):
            for j in range(i+1,n):
                a=0 if i==0 else p[i-1]
                old=d[a,p[i]];new=d[a,p[j]]
                if j+1<n:old+=d[p[j],p[j+1]];new+=d[p[i],p[j+1]]
                if new<old-1e-8:
                    p[i:j+1]=p[i:j+1][::-1];changed=True
        best=length(p,d)
        for i in range(n):
            for j in range(n):
                if i==j:continue
                q=p.copy();item=q[i]
                if i<j:
                    for k in range(i,j):q[k]=q[k+1]
                else:
                    for k in range(i,j,-1):q[k]=q[k-1]
                q[j]=item;value=length(q,d)
                if value<best-1e-8:p=q;best=value;changed=True
        if not changed:return p

@njit(cache=True)
def strong(d):
    n=len(d)-1;best=np.arange(1,n+1);value=length(best,d)
    for first in range(1,n+1):
        used=np.zeros(n+1,np.bool_);used[0]=True;used[first]=True
        p=np.empty(n,np.int64);p[0]=first
        for k in range(1,n):
            chosen=-1;dist=np.inf
            for j in range(1,n+1):
                if not used[j] and d[p[k-1],j]<dist:chosen=j;dist=d[p[k-1],j]
            p[k]=chosen;used[chosen]=True
        p=improve(p,d);v=length(p,d)
        if v<value-1e-8:best=p;value=v
    return best,value

@njit(cache=True)
def exact(d):
    n=len(d)-1
    if n==0:return 0.
    dp=np.full((1<<n,n),np.inf)
    for j in range(n):dp[1<<j,j]=d[0,j+1]
    for mask in range(1,1<<n):
        for j in range(n):
            if not mask&(1<<j):continue
            previous=mask^(1<<j)
            if previous==0:continue
            best=np.inf
            for k in range(n):
                if previous&(1<<k):best=min(best,dp[previous,k]+d[k+1,j+1])
            dp[mask,j]=best
    return np.min(dp[-1])

def distances(start,points):
    p=np.vstack((start,np.asarray(points).reshape(-1,2)))
    return np.linalg.norm(p[:,None,:]-p[None,:,:],axis=2)

def verify():
    from itertools import permutations
    rng=np.random.default_rng(20260912)
    for n in range(1,8):
        d=distances([0.,0.],rng.normal(size=(n,2)))
        brute=min(length(np.array(p),d) for p in permutations(range(1,n+1)))
        assert abs(exact(d)-brute)<1e-10
        path,cost=strong(d);assert sorted(path)==list(range(1,n+1))
        assert cost>=brute-1e-10 and cost<=length(np.arange(1,n+1),d)+1e-10
    print('Exact DP agrees with exhaustive permutations for n=1..7; reference visits every node once.')

if __name__=='__main__':verify()
