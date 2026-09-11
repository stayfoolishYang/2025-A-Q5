"""Correlated probabilistic-terminal route cost on the frozen discovery belief."""
import numpy as np
from belief_fast import evidence
from geometry import route
from endpoint_cost import scan

class TerminalCost:
    def __init__(self,belief,nodes):
        self.nodes=np.asarray(nodes);self.known=len(belief.seen)
        hits=belief.hitmatrix(nodes)
        codes=(hits.astype(np.uint32)* (np.uint32(1)<<np.arange(len(nodes),dtype=np.uint32))[:,None]).sum(axis=0,dtype=np.uint32)
        self.groups=[];cache={}
        for c in range(1,21):
            if c in belief.seen:continue
            key=frozenset(belief.negative_points[c])
            if key not in cache:
                values,counts=np.unique(codes[belief.masks[c]],return_counts=True)
                cache[key]=(values,counts/len(belief.states))
            self.groups.append(cache[key])
        self.z=evidence([weights.sum() for _,weights in self.groups],self.known)
        if self.z<=0:raise ValueError('finite_particle_support_exhausted')
        self.cache={0:1.}
    def survival(self,mask):
        if mask not in self.cache:
            likelihood=[weights[(codes & mask)==0].sum() for codes,weights in self.groups]
            self.cache[mask]=evidence(likelihood,self.known)/self.z
        return self.cache[mask]
    def cost(self,order,start,channel,cleared):
        cost=0.;mask=0;point=np.asarray(start)
        for i in order:
            scan_s,channel=scan(channel,cleared,1)
            cost+=self.survival(mask)*(np.linalg.norm(self.nodes[i]-point)/5+scan_s)
            mask|=1<<i;point=self.nodes[i]
        return float(cost)

def choose(belief,nodes,start,channel,cleared,mode):
    nodes=np.asarray(nodes);prediction=belief.predict(nodes)
    if not prediction['available']:return 0,dict(fallback=True)
    scan_s,_=scan(channel,cleared,1)
    scores=prediction['expected_new']/(np.linalg.norm(nodes-start,axis=1)/5+scan_s)
    if mode=='MYOPIC':return int(np.argmax(scores)),dict(fallback=False,score=scores.tolist())
    model=TerminalCost(belief,nodes);lookup={tuple(p):i for i,p in enumerate(nodes)}
    orders=[list(range(len(nodes)))];costs=[model.cost(orders[0],start,channel,cleared)]
    # Enumerate every first node, complete each suffix with the frozen R12 route.
    for i in range(len(nodes)):
        suffix=route(np.delete(nodes,i,axis=0),nodes[i]) if len(nodes)>1 else []
        order=[i]+[lookup[tuple(p)] for p in suffix]
        assert sorted(order)==list(range(len(nodes)))
        orders.append(order);costs.append(model.cost(order,start,channel,cleared))
    best=int(np.argmin(costs))
    return orders[best][0],dict(fallback=False,baseline_cost=costs[0],selected_cost=costs[best],
        first_candidates=[order[0] for order in orders],candidate_costs=costs,
        selected_order=orders[best],exhaustion_probability=model.survival((1<<len(nodes))-1))
