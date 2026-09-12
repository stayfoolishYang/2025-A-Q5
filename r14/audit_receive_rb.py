import json,math,gzip
from concurrent.futures import ProcessPoolExecutor,as_completed
from collect import ROOT
import numpy as np
from scipy.special import logsumexp
from audit_random_blocks import context,seed
from receive_integral import integrate
from grid_measure import GridMeasure,summarize
OUT=ROOT/'results/receive_rb';OUT.mkdir(exist_ok=True)
def checks():
 p=[0,0];cases=[([],[[500,0],[1250,0],[0,0]],1.,[.75,.375,1.]),([(np.array([100.,0]),'direction',180.)],[[500,0],[-500,0]],.75,[.75,.5]),([(np.array([1200.,0]),'no_signal',None)],[[-500,0]],.55,[.45])]
 rows=[]
 for h,q,den,nums in cases:
  d,n=integrate(p,h,[],q);assert np.allclose(d,den,atol=1e-12) and np.allclose(n,nums,atol=1e-12);rows.append(dict(den=d,num=n.tolist()))
 (OUT/'analytic.json').write_text(json.dumps(rows,indent=2))
def worker(job):
 s0,bank=job;i,j=s0['id'],s0['step'];path=OUT/f'{i:04d}_{j:02d}_{bank}.json'
 if path.exists():return
 try:s,c,nodes,ts,p0,q,cleared=context(s0)
 except ValueError as e:
  if str(e)!='max() arg is an empty sequence':raise
  path.write_text(json.dumps(dict(state=s0,bank=bank,status='UNSUPPORTED_NO_KNOWN_SOURCE',official_calls=0,continuations=0)));return
 # Keep each bank's original frozen adaptive proposal; no pilot re-fit.
 oldpath=ROOT/'results/defensive_proposal'/f'{i:04d}_{j:02d}_{bank}.json'
 if oldpath.exists() and not s0.get('audit_channel'):q=np.array(json.loads(oldpath.read_bytes())['triangle_proposal'])
 else:
  from audit_defensive_proposal import proposals,likelihood
  pilotrng=np.random.default_rng(seed('RB64pilot',i,j,bank));pilot,pid=proposals(s,c,ts,p0,512,pilotrng);logs,_=likelihood(pilot,s,c,64,pilotrng)
  q=.3*p0+.7*np.bincount(pid,weights=np.exp(logs-logsumexp(logs)),minlength=len(ts)) if np.isfinite(logs).any() else p0.copy()
 rng=np.random.default_rng(seed('RB',i,j,bank));ix=rng.choice(len(ts),512,p=q);u=np.sqrt(rng.random(512));v=rng.random(512)
 ps=(1-u[:,None])*ts[ix,0]+(u*(1-v))[:,None]*ts[ix,1]+(u*v)[:,None]*ts[ix,2]
 logw=[];rb=[];ind=[];geoms=[]
 for p,k in zip(ps,ix):
  mass,num,pieces=integrate(p,s.hist[c],s.clear_obs[c],nodes,True);geoms.append(mass)
  if mass<=0:logw.append(-math.inf);rb.append(np.zeros(len(nodes)));ind.append(np.zeros(len(nodes)));continue
  ll=summarize(GridMeasure(p,s.hist[c]).draw_pivot(512,int(rng.integers(2**63)))[1])['log_volume']
  logw.append(ll+math.log(mass)+math.log(p0[k]/q[k]));rb.append(num/mass)
  piece=pieces[rng.choice(len(pieces),p=np.array([r[-1] for r in pieces])/mass)]
  directional,a,b,lo,hi,_=piece;phi=rng.uniform(a,b);radius=rng.uniform(lo,hi);diff=nodes-p
  ind.append((np.linalg.norm(diff,axis=1)<=radius)&((not directional)|(diff@np.array([math.cos(phi),math.sin(phi)])>=0)))
 z=logsumexp(logw)
 if not np.isfinite(z):raise RuntimeError('Zero RB bank')
 w=np.exp(np.array(logw)-z);prob=w@np.array(rb);indicator=w@np.array(ind);order=np.argsort(-prob,kind='stable')
 path.write_text(json.dumps(dict(state=s0,bank=bank,channel=c,cleared=cleared,p_hit=prob.tolist(),indicator=indicator.tolist(),ess=float(1/(w@w)),max_weight=float(w.max()),zero_geometry=sum(g==0 for g in geoms),top3=order[:3].tolist(),gap3=float(prob[order[2]]-prob[order[3]]) if len(order)>3 else None,official_calls=0,continuations=0)))
if __name__=='__main__':
 checks();states=json.loads((ROOT/'results/posterior_measure/selection.json').read_bytes())
 with ProcessPoolExecutor(max_workers=6) as pool:
  for n,f in enumerate(as_completed([pool.submit(worker,(s,b)) for s in states for b in range(3)]),1):f.result();print('RB_BANKS',n,36,flush=True)
