"""R12 suffix-budget-constrained belief reranking; no whole-game bound claimed."""
import numpy as np
from geometry import route

def length(nodes,start):
    points=np.vstack((start,nodes))
    return float(np.linalg.norm(np.diff(points,axis=0),axis=1).sum())

def choose(belief,nodes,start,budget_s=0.,margin=.05):
    if budget_s<0:raise ValueError('Negative budget')
    nodes=np.asarray(nodes);p=belief.predict(nodes)
    if not p['available']:return 0,dict(fallback=True)
    base=length(nodes,start);prob=p['probability_any'];options=[(0,base)]
    for i in range(1,len(nodes)):
        suffix=route(np.delete(nodes,i,axis=0),nodes[i])
        candidate=np.vstack((nodes[i],suffix));distance=length(candidate,start)
        assert sorted(map(tuple,candidate))==sorted(map(tuple,nodes))
        if distance<=base+5*budget_s+1e-8:options.append((i,distance))
    best=max(options,key=lambda item:prob[item[0]])
    if prob[best[0]]-prob[0]<=margin:best=options[0]
    i,d=best
    assert d<=base+5*budget_s+1e-8
    return i,dict(fallback=False,index=i,baseline_m=base,candidate_m=d,
        planned_detour_s=(d-base)/5,probability_gain=float(prob[i]-prob[0]),eligible_count=len(options),
        budget_s=budget_s,margin=margin)
