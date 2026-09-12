"""Exact integration of type, orientation and radius under declared priors.
Independent priors: type 1/2, phi uniform circle, R uniform [1000,1500].
Historical conditioning is joint: no-signal can constrain radius OR heading.
"""
import math
import numpy as np
TAU=2*math.pi

def overlap(a,b,angle):
    return sum(max(0.,min(b,angle+math.pi/2+k*TAU)-max(a,angle-math.pi/2+k*TAU)) for k in [-1,0,1])

def integrate(position,history,clear_obs,nodes,components=False):
    def empty():return (0.,np.zeros(len(nodes)),[]) if components else (0.,np.zeros(len(nodes)))
    p=np.asarray(position);nodes=np.asarray(nodes);dist=np.linalg.norm(nodes-p,axis=1);angles=np.arctan2((nodes-p)[:,1],(nodes-p)[:,0])%TAU
    records=[];cuts=[0.,TAU]
    for point,result,_ in history:
        v=np.asarray(point)-p;d=float(np.linalg.norm(v));theta=math.atan2(v[1],v[0])%TAU
        if result=='direction' and d<=5:return empty()
        if result=='near' and d>5:return empty()
        records.append((d,theta,result))
        if d>0:cuts.extend([(theta-math.pi/2)%TAU,(theta+math.pi/2)%TAU])
    for point,success in clear_obs:
        if (np.linalg.norm(np.asarray(point)-p)<=20)!=success:return empty()
    if np.linalg.norm(p)>1800:return empty()
    cuts=sorted(set(cuts));den=0.;num=np.zeros(len(nodes));pieces=[]
    for directional in [False,True]:
        intervals=list(zip(cuts[:-1],cuts[1:])) if directional else [(0.,TAU)]
        for a,b in intervals:
            phi=(a+b)/2;lo=1000.;hi=1500.;valid=True
            for d,theta,result in records:
                front=not directional or d==0 or math.cos(phi-theta)>=0
                if result!='no_signal':
                    if not front:valid=False;break
                    lo=max(lo,d)
                elif front:hi=min(hi,d)
            if not valid or hi<=lo:continue
            scale=.5*(b-a)/TAU/500
            den+=scale*(hi-lo)
            pieces.append((directional,a,b,lo,hi,scale*(hi-lo)))
            fractions=np.array([overlap(a,b,t)/(b-a) if dd>0 else 1. for t,dd in zip(angles,dist)]) if directional else np.ones(len(nodes))
            num+=scale*np.maximum(0.,hi-np.maximum(lo,dist))*fractions
    return (den,num,pieces) if components else (den,num)
