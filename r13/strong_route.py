"""A1: improve the actual R12 incumbent without changing its node multiset."""
import numpy as np
from route_reference import distances, strong, length

def optimize(incumbent, start):
    points=np.asarray(incumbent).reshape(-1,2)
    if len(points)<2:return list(points)
    d=distances(start,points); before=length(np.arange(1,len(points)+1),d)
    order,cost=strong(d)
    assert sorted(order.tolist())==list(range(1,len(points)+1))
    result=points[order-1]
    assert cost<=before+1e-8
    return list(result) if cost<before-1e-8 else list(points)
