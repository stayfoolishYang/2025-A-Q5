"""Defensive triangle proposal pilot; frozen target and 512 final noise draws."""
import json,gzip,math,hashlib,time
from concurrent.futures import ProcessPoolExecutor,as_completed
from collect import ROOT
import numpy as np
from scipy.special import logsumexp
from world_sampler_v2 import WorldSampler
from particles import feasible
from grid_measure import GridMeasure,summarize
OUT=ROOT/'results/defensive_proposal';OUT.mkdir(exist_ok=True)
BASELINE=False
CONFIG=dict(alpha=.3,pilot_sources=512,pilot_noise=64,final_sources=512,final_noise=512,subdivisions=2,banks=3,qualification='12-state development only; no Q2',target='unchanged independent grid')

def triangles(poly):
    ts=np.array([[poly[0],poly[k],poly[k+1]] for k in range(1,len(poly)-1)])
    for _ in range(CONFIG['subdivisions']):
        result=[]
        for a,b,c in ts:
            ab=(a+b)/2;bc=(b+c)/2;ca=(c+a)/2
            result.extend([[a,ab,ca],[ab,b,bc],[ca,bc,c],[ab,bc,ca]])
        ts=np.array(result)
    areas=np.abs(np.cross(ts[:,1]-ts[:,0],ts[:,2]-ts[:,0]))/2
    ts=ts[areas>1e-14];areas=areas[areas>1e-14];return ts,areas/areas.sum()

def proposals(s,c,ts,prob,count,rng):
    xs=[];ids=[]
    for _ in range(64):
        ix=rng.choice(len(ts),4096,p=prob);u=np.sqrt(rng.random(4096));v=rng.random(4096)
        xy=(1-u[:,None])*ts[ix,0]+(u*(1-v))[:,None]*ts[ix,1]+(u*v)[:,None]*ts[ix,2]
        ps=np.c_[xy,rng.uniform(-np.pi,np.pi,4096),rng.uniform(1000,1500,4096),rng.integers(0,2,4096)]
        mask=np.linalg.norm(xy,axis=1)<=1800
        for obs in s.hist[c]:mask &=feasible(ps,obs)
        for p,success in s.clear_obs[c]:
            d=np.linalg.norm(xy-p,axis=1);mask &=(d<=20) if success else (d>20)
        xs.extend(ps[mask].tolist());ids.extend(ix[mask].tolist())
        if len(xs)>=count:return np.array(xs[:count]),np.array(ids[:count])
    raise RuntimeError('Source proposal bank incomplete')

def likelihood(ps,s,c,n,rng):
    stats=[summarize(GridMeasure(p[:2],s.hist[c]).draw_pivot(n,int(rng.integers(2**63)))[1]) for p in ps]
    return np.array([x['log_volume'] for x in stats]),stats

def worker(job):
    state,bank=job;i,j=state['id'],state['step'];dest=OUT/f'{i:04d}_{j:02d}_{bank}.json'
    if dest.exists():return
    started=time.perf_counter();seed=int.from_bytes(hashlib.sha256(f'defensive:{i}:{j}:{bank}'.encode()).digest()[:8],'big');rng=np.random.default_rng(seed)
    with gzip.open(ROOT/'results/value_oracle/core/traces'/f'R12_{i:04d}.json.gz','rt') as f:trace=json.load(f)
    s=WorldSampler([a for a in trace['actions'] if a['path']!='/exit' and a['response']['virtual_time_s']<=state['time_s']])
    c=max(s.known,key=lambda c:sum(r=='direction' for p,r,a in s.hist[c]));ts,p0=triangles(s.polys[c])
    pilot,pid=proposals(s,c,ts,p0,512,rng);plog,_=likelihood(pilot,s,c,64,rng)
    if np.isfinite(plog).any():
        mass=np.bincount(pid,weights=np.exp(plog-logsumexp(plog)),minlength=len(ts));q=.3*p0+.7*mass
    else:q=p0.copy()
    if BASELINE:q=p0.copy()
    final,fid=proposals(s,c,ts,q,512,rng);logs,stats=likelihood(final,s,c,512,rng)
    logw=logs+np.log(p0[fid])-np.log(q[fid]);z=logsumexp(logw)
    result=dict(state=state,bank=bank,channel=c,seed=seed,config=CONFIG,seconds=time.perf_counter()-started,pilot_nonzero=int(np.isfinite(plog).sum()),official_calls=0,continuations=0)
    if not np.isfinite(z):result.update(status='ZERO_WEIGHT')
    else:
        w=np.exp(logw-z)
        with gzip.open(ROOT/'results/value_oracle/snapshots'/f'{i:04d}.json.gz','rt') as f:nodes=np.array(json.load(f)[j]['nodes'])
        hit=[]
        for p in final:
            diff=nodes-p[:2];hit.append((np.linalg.norm(diff,axis=1)<=p[3])&((p[4]==0)|(diff@np.array([math.cos(p[2]),math.sin(p[2])])>=0)))
        prob=w@np.array(hit)
        result.update(status='WEIGHTED',ess=float(1/(w@w)),max_weight=float(w.max()),p_hit=prob.tolist(),top3=np.argsort(-prob,kind='stable')[:3].tolist(),noise_ess_median=float(np.median([x['ess'] for x in stats])),triangle_prior=p0.tolist(),triangle_proposal=q.tolist(),proposal_ratio=(q[fid]/p0[fid]).tolist(),log_weights=logw.tolist())
    dest.write_text(json.dumps(result))
if __name__=='__main__':
    (OUT/'preregistered_config.json').write_text(json.dumps(CONFIG,indent=2))
    states=json.loads((ROOT/'results/posterior_measure/selection.json').read_bytes())
    with ProcessPoolExecutor(max_workers=6) as pool:
        for n,f in enumerate(as_completed([pool.submit(worker,(s,b)) for s in states for b in range(3)]),1):f.result();print('DEFENSIVE_BANKS',n,36,flush=True)
