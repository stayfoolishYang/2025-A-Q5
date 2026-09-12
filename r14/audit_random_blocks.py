"""Pick-freeze final-bank randomness, conditional on a frozen pilot proposal."""
import json,gzip,math,hashlib
from concurrent.futures import ProcessPoolExecutor,as_completed
from collect import ROOT
import numpy as np
from scipy.special import logsumexp
from audit_defensive_proposal import triangles
from world_sampler_v2 import WorldSampler
from particles import feasible
from grid_measure import GridMeasure,summarize
OUT=ROOT/'results/random_block_audit';OUT.mkdir(exist_ok=True)
BLOCKS=['position','heading','radius','type','noise']
def seed(*args):return int.from_bytes(hashlib.sha256(':'.join(map(str,args)).encode()).digest()[:8],'big')
def context(state):
 i,j=state['id'],state['step']
 with gzip.open(ROOT/'results/value_oracle/core/traces'/f'R12_{i:04d}.json.gz','rt') as f:trace=json.load(f)
 s=WorldSampler([a for a in trace['actions'] if a['path']!='/exit' and a['response']['virtual_time_s']<=state['time_s']])
 c=state.get('audit_channel') or max(s.known,key=lambda c:sum(r=='direction' for p,r,a in s.hist[c]))
 with gzip.open(ROOT/'results/value_oracle/snapshots'/f'{i:04d}.json.gz','rt') as f:snap=json.load(f)[j]
 ts,p0=triangles(s.polys[c]);prior_path=ROOT/'results/defensive_proposal'/f'{i:04d}_{j:02d}_0.json';q=np.array(json.loads(prior_path.read_bytes())['triangle_proposal']) if prior_path.exists() and not state.get('audit_channel') else p0.copy()
 return s,c,np.array(snap['nodes']),ts,p0,q,c in snap['cleared']
def worker(job):
 state,pair,variant=job;i,j=state['id'],state['step'];path=OUT/f'{i:04d}_{j:02d}_{pair}_{variant}.json'
 if path.exists():return
 s,c,nodes,ts,p0,q,cleared=context(state)
 streams={b:np.random.default_rng(seed(i,j,pair,b,'B' if variant=='B' or variant==b else 'A')) for b in BLOCKS}
 parts=[];cell=[];noise=[]
 for batch in range(64):
  rng=streams['position'];ix=rng.choice(len(ts),4096,p=q);u=np.sqrt(rng.random(4096));v=rng.random(4096)
  xy=(1-u[:,None])*ts[ix,0]+(u*(1-v))[:,None]*ts[ix,1]+(u*v)[:,None]*ts[ix,2]
  ps=np.c_[xy,streams['heading'].uniform(-np.pi,np.pi,4096),streams['radius'].uniform(1000,1500,4096),streams['type'].integers(0,2,4096)]
  ns=streams['noise'].integers(2**63,size=4096);mask=np.linalg.norm(xy,axis=1)<=1800
  for obs in s.hist[c]:mask &=feasible(ps,obs)
  for p,success in s.clear_obs[c]:
   d=np.linalg.norm(xy-p,axis=1);mask &=(d<=20) if success else (d>20)
  parts.extend(ps[mask].tolist());cell.extend(ix[mask]);noise.extend(ns[mask])
  if len(parts)>=512:break
 if len(parts)<512:raise RuntimeError('Incomplete bank')
 ps=np.array(parts[:512]);ix=np.array(cell[:512]);logs=[]
 for p,ns in zip(ps,noise[:512]):logs.append(summarize(GridMeasure(p[:2],s.hist[c]).draw_pivot(512,int(ns))[1])['log_volume'])
 logw=np.array(logs)+np.log(p0[ix]/q[ix]);z=logsumexp(logw)
 if not np.isfinite(z):raise RuntimeError('Zero bank')
 w=np.exp(logw-z);diff=nodes[None,:,:]-ps[:,None,:2];dist=np.linalg.norm(diff,axis=2)
 radius=ps[:,3,None]-dist;heading=np.einsum('ijk,ik->ij',diff,np.c_[np.cos(ps[:,2]),np.sin(ps[:,2])]);directional=ps[:,4,None]==1
 hit=(radius>=0)&(~directional|(heading>=0));prob=w@hit
 order=np.argsort(-prob,kind='stable');gap=float(prob[order[2]]-prob[order[3]]) if len(order)>3 else None
 path.write_text(json.dumps(dict(state=state,pair=pair,variant=variant,channel=c,cleared=cleared,p_hit=prob.tolist(),radius_boundary_mass=(w@(np.abs(radius)<10)).tolist(),heading_boundary_mass=(w@(directional&(np.abs(heading)<10))).tolist(),heading_relevant_boundary_mass=(w@(directional&(np.abs(heading)<10)&(radius>=0))).tolist(),radius_relevant_boundary_mass=(w@((np.abs(radius)<10)&(~directional|(heading>=0)))).tolist(),ess=float(1/(w@w)),top3=order[:3].tolist(),gap3=gap,official_calls=0,continuations=0)))
if __name__=='__main__':
 states=json.loads((ROOT/'results/posterior_measure/selection.json').read_bytes())
 (OUT/'design.json').write_text(json.dumps(dict(states=12,pairs=3,variants=['A','B']+BLOCKS,sources=512,noise=512,boundary_epsilon_m=10,pilot='fixed bank0 per state',interpretation='random-stream sensitivity, not posterior Sobol indices')))
 with ProcessPoolExecutor(max_workers=6) as pool:
  for n,f in enumerate(as_completed([pool.submit(worker,(s,p,v)) for s in states for p in range(3) for v in ['A','B']+BLOCKS]),1):
   f.result()
   if n%24==0:print('BLOCK_BANKS',n,252,flush=True)
