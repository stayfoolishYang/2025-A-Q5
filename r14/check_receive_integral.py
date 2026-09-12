import json,gzip
import numpy as np
from collect import ROOT
from audit_random_blocks import context
from receive_integral import integrate
from particles import feasible
states=json.loads((ROOT/'results/posterior_measure/selection.json').read_bytes());rows=[]
for index,state in enumerate(states):
 s,c,nodes,*_=context(state);old=json.loads((ROOT/'results/posterior_measure'/f'{state["id"]:04d}_{state["step"]:02d}.json').read_bytes());p=np.array(old['proposals'][0][:2]);N=262144;rng=np.random.default_rng(819000+index)
 ps=np.c_[np.tile(p,(N,1)),rng.uniform(-np.pi,np.pi,N),rng.uniform(1000,1500,N),rng.integers(0,2,N)]
 mask=np.ones(N,dtype=bool)
 # Geometric branches only: angle likelihood is separately integrated over noise.
 for pos,result,angle in s.hist[c]:
  diff=pos-p;d=np.linalg.norm(diff);front=(ps[:,4]==0)|((np.cos(ps[:,2])*diff[0]+np.sin(ps[:,2])*diff[1])>=0)
  recv=(ps[:,3]>=d)&front
  mask &= (~recv if result=='no_signal' else recv&(d<=5 if result=='near' else d>5))
 for pos,success in s.clear_obs[c]:mask &= (np.linalg.norm(pos-p)<=20)==success
 mask &=np.linalg.norm(p)<=1800
 den,num=integrate(p,s.hist[c],s.clear_obs[c],nodes)
 truth=[den];mc=[mask.mean()]
 for q,v in zip(nodes,num):
  diff=q-p;recv=(ps[:,3]>=np.linalg.norm(diff))&((ps[:,4]==0)|((np.cos(ps[:,2])*diff[0]+np.sin(ps[:,2])*diff[1])>=0))
  truth.append(v);mc.append((mask&recv).mean())
 truth=np.array(truth);mc=np.array(mc);tol=6*np.sqrt(truth*(1-truth)/N)+1/N
 assert np.all(abs(mc-truth)<=tol)
 rows.append(dict(id=state['id'],step=state['step'],max_abs_error=float(abs(mc-truth).max()),passed=True,samples=N))
(ROOT/'results/receive_rb/prior_integration_crosscheck.json').write_text(json.dumps(rows,indent=2));print('PRIOR_CROSSCHECK',len(rows),'PASS')
