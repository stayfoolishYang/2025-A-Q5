import itertools,json,math
from collect import ROOT
import numpy as np
from unknown_discovery import UnknownPosterior
class Mixed:
 known=set(range(1,15))
 hist={c:([(np.array([300.*(c%3),200.]),'no_signal',None)] if c%3 else []) for c in range(1,21)}
u=UnknownPosterior(Mixed(),np.array([[0.,0.],[1200.,0.]]),55123)
mass=np.zeros(3);no=np.zeros(2)
for mask in itertools.product([0,1],repeat=6):
 m=sum(mask)
 if m>2:continue
 w=1/math.comb(20,14+m)
 wn=np.full(2,w)
 for i,included in enumerate(mask):
  if included:
   w*=u.L[i];g=u.data[u.channel_group[u.channels[i]]];wn*=u.L[i]-g['joint']
 mass[m]+=w;no+=wn
assert np.allclose(mass/mass.sum(),u.pm,atol=1e-13)
assert np.allclose(1-no/mass.sum(),u.pnew,atol=1e-13)
p=ROOT/'results/unknown_discovery/checks.json';d=json.loads(p.read_bytes());d.update(heterogeneous_history_classes=len(u.groups),brute_force_subsets=64,mixed_count_and_discovery_verified=True);p.write_text(json.dumps(d,indent=2));print('MIXED_HISTORY PASS')
