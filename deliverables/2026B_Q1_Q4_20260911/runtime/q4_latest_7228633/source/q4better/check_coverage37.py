"""Integer triangulation certificate plus separately labelled real-engine edge checks."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys
import numpy as np
from geometry import coverage, route


def check(sim_root):
    sys.path.insert(0, str(sim_root))
    from engine import Engine, Jammer, Scenario
    triangles = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            for i in range(3):
                for j in range(3):
                    if i+j > 3: continue
                    local = [((i,j), (i+1,j), (i,j+1))]
                    if i+j <= 2: local.append(((i+1,j+1), (i+1,j), (i,j+1)))
                    triangles += [tuple((sx*700*x, sy*700*y) for x,y in t) for t in local]
    vertices = set(v for t in triangles for v in t)
    edges = Counter(tuple(sorted((t[i], t[(i+1)%3]))) for t in triangles for i in range(3))
    boundary = [e for e, n in edges.items() if n == 1]
    assert vertices == set(map(tuple, coverage(True, version='certified37')))
    assert len(triangles) == len(set(tuple(sorted(t)) for t in triangles)) == 56
    assert len(edges) == 92 and len(boundary) == 16 and set(edges.values()) == {1,2}
    area = 0
    for a,b,c in triangles:
        assert sorted((v[0]-w[0])**2+(v[1]-w[1])**2 for v,w in ((a,b),(b,c),(c,a))) == [490000,490000,980000]
        area += abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))//2
    assert area == 13720000
    for a,b in boundary:
        x,y = (a[0]+b[0])/2, (a[1]+b[1])/2
        assert abs(x)==2100 or abs(y)==2100 or abs(x)+abs(y)==2800
    # Each quadrant consists of disjoint complete unit cells and boundary half-cells.
    # See COVERAGE37.md for the continuous proof; tests below are not its substitute.
    nodes = coverage(True, version='certified37')
    sources = [tuple(p) for p in nodes if np.linalg.norm(p)<=1800]
    sources += [(1800*math.cos(a),1800*math.sin(a)) for a in np.linspace(0,2*math.pi,65)[:-1]]
    sources += [(350.,350.), (700.+1e-10,700.-1e-10), (1800.000001,0.)]
    cases = 0
    for x,y in sources:
        for direction in range(0,360,5):
            e = Engine(Scenario('0123456789abcdef',4,(Jammer(1,x,y,1000.,'directional',direction),)))
            e.apply('/enter', {})
            replies = [e.apply('/measure',dict(position=dict(x=float(p[0]),y=float(p[1])),channel=1)) for p in nodes]
            assert any(r['measure_result']=='direction' for r in replies), (x,y,direction)
            cases += 1
    def observed(x,y,direction=0.):
        e = Engine(Scenario('0123456789abcdef',4,(Jammer(1,0.,0.,1000.,'directional',direction),)))
        e.apply('/enter',{})
        return e.apply('/measure',dict(position=dict(x=x,y=y),channel=1))['measure_result']
    assert observed(0.,0.,180.)=='near'
    assert observed(5.,0.)=='near' and observed(math.nextafter(5.,math.inf),0.)=='direction'
    assert observed(1000.,0.)=='direction' and observed(math.nextafter(1000.,math.inf),0.)=='no_signal'
    assert observed(0.,1000.)=='direction'
    assert observed(700.,0.,90.)=='direction' and observed(700.,0.,90.000001)=='no_signal'
    lengths = {}
    for version in ('legacy45','certified37'):
        path = route(coverage(True,version=version), np.zeros(2))
        lengths[version] = float(np.linalg.norm(np.diff(np.vstack(([0.,0.],path)),axis=0),axis=1).sum())
    return dict(vertices=sorted(vertices),triangles=triangles,edges=len(edges),boundary_edges=boundary,
                area_m2=area,max_triangle_diameter_m=700*math.sqrt(2),
                strict_witness_max_m=700*math.sqrt(2)+6,engine_finite_cases=cases,
                static_route_m=lengths,static_saving_s=(lengths['legacy45']-lengths['certified37'])/5)

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--sim-root',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); result=check(a.sim_root); a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('vertices','triangles','boundary_edges')}))
