"""Independent checks against Engine and exhaustive channel-subset integration."""
import itertools, json, sys
from pathlib import Path
import numpy as np
from belief import DiscoveryBelief, detects, evidence
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'r13/local_engine'))
from engine import Engine, Scenario, Jammer

b=DiscoveryBelief(power=12)
p=b.predict([[0,0],[1000,0]])
assert np.allclose(p['existence'], .65)
assert np.allclose(b.survival([[0,0]])[1], 1-p['probability_any'][0])
b.observe(1,[0,0],'no_signal')
a=b.predict([[0,0],[1000,0]])
assert a['probability_channel'][0,0] == 0
assert a['existence'][0] < a['existence'][1]
old=b.masks[1].copy();b.observe(1,[0,0],'no_signal');assert np.array_equal(old,b.masks[1])
# Exact enumeration: 14 confirmed, six unknown, N in 14..16.
L=np.array([.1,.2,.4,.6,.8,.9]); z=0.; marg=np.zeros(6)
for bits in itertools.product((0,1),repeat=6):
    n=14+sum(bits)
    if n>16:continue
    import math
    weight=np.prod([L[i] for i,v in enumerate(bits) if v])/math.comb(20,n)/7
    z+=weight;marg+=weight*np.array(bits)
assert np.isclose(z,evidence(L,14),rtol=1e-12,atol=0)
actual=np.array([L[i]*evidence(np.delete(L,i),15)/z for i in range(6)])
assert np.allclose(actual,marg/z)
# Sensor comparisons include near behind the source and angular/radius boundaries.
checks=0
for state in [np.array([0,0,1000,1,0]), *b.states[:64]]:
    x,y,r,d,phi=state
    nodes=np.array([[x,y],[x-1,y],[x+1,y],[x,y+r],[x,y-r],
                    [x+r+1e-5,y],[x-r,y],[0,0],[1200,1200]])
    predicted=detects(state[None,:],nodes)[:,0]
    engine=Engine(Scenario('00',4,(Jammer(1,x,y,r,'directional' if d else 'omni',np.degrees(phi)),)))
    engine.apply('/enter',{})
    for node,want in zip(nodes,predicted):
        result=engine.apply('/measure',dict(position=dict(x=float(node[0]),y=float(node[1])),channel=1))
        assert result['accepted']
        assert (result['measure_result']!='no_signal')==want,(state,node,result,want)
        checks+=1
s=b.survival([[0,0],[1000,0],[1000,0],[-1000,0]])
assert np.all(np.diff(s)<=1e-12) and s[2]==s[3]
print(json.dumps(dict(sensor_engine_comparisons=checks,existence_enumeration='PASS',
                     repeated_negative_idempotence='PASS',joint_survival='PASS',official_calls=0)))
