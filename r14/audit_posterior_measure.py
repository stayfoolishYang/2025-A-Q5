"""Analytic joint-volume checks and fixed-bank public-history posterior stability."""
import json,gzip,math
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path
from collect import ROOT
import numpy as np
from scipy.special import logsumexp
from grid_measure import GridMeasure,summarize
from world_sampler_v2 import WorldSampler
from geometry import sample_poly
from particles import feasible
SOURCE=ROOT/'results/value_oracle';OUT=ROOT/'results/posterior_measure';OUT.mkdir(exist_ok=True)

def analytic():
    results=[]
    for name,A,lo,hi,truth in [('one',[[1]],[-.1],[.1],.1),('independent',[[1,0],[0,1]],[-.1,-.1],[.1,.1],.01),('shared',[[.5,.5,0],[0,.5,.5]],[-.1,-.1],[.1,.1],11/300)]:
        g=GridMeasure.__new__(GridMeasure);g.keys=list(range(len(A[0])));g.A=np.array(A);g.lo=np.array(lo);g.hi=np.array(hi);g.history=[];g.impossible=False;g.order=g.variable_order(g.A)
        for seed in range(4):
            _,w=g.draw(65536,seed);r=summarize(w);v=math.exp(r['log_volume']);se=v*r['relative_se'];assert abs(v-truth)<=max(6*se,1e-12)
            results.append(dict(name=name,seed=seed,truth=truth,estimate=v,**r))
    h=[(np.array([0.,0.]),'direction',0.)];g1=GridMeasure([100,0],h);g2=GridMeasure([100,0],h*3)
    x,w=g1.draw(4096,12);xx,ww=g2.draw(4096,12);assert np.array_equal(x,xx) and np.array_equal(w,ww)
    results.append(dict(name='repeated_observation_invariance',passed=True,volume=math.exp(summarize(w)['log_volume'])))
    (OUT/'analytic.json').write_text(json.dumps(results,indent=2))

def worker(state):
    i,j=state['id'],state['step'];suffix=f'_bank{state["bank_repeat"]}' if 'bank_repeat' in state else '';dest=OUT/f'{i:04d}_{j:02d}{suffix}.json'
    if dest.exists():return
    with gzip.open(SOURCE/'core/traces'/f'R12_{i:04d}.json.gz','rt') as f:trace=json.load(f)
    actions=[a for a in trace['actions'] if a['path']!='/exit' and a['response']['virtual_time_s']<=state['time_s']]
    sampler=WorldSampler(actions)
    # Deliberately audit a history-rich known channel; no oracle continuation read.
    c=max(sampler.known,key=lambda c:sum(r=='direction' for p,r,a in sampler.hist[c]))
    rng=np.random.default_rng(1500000+i*100+j+state.get("bank_repeat",0)*10000000);parts=[];source_count=state.get("source_count",128)
    for _ in range(16):
        xy=sample_poly(sampler.polys[c],4096,rng)
        ps=np.c_[xy,rng.uniform(-np.pi,np.pi,len(xy)),rng.uniform(1000,1500,len(xy)),rng.integers(0,2,len(xy))]
        ps=ps[np.linalg.norm(xy,axis=1)<=1800]
        for obs in sampler.hist[c]:ps=ps[feasible(ps,obs)]
        for p,success in sampler.clear_obs[c]:
            d=np.linalg.norm(ps[:,:2]-p,axis=1);ps=ps[(d<=20) if success else (d>20)]
        parts.extend(ps.tolist())
        if len(parts)>=source_count:break
    ps=np.array(parts[:source_count]);runs=[]
    with gzip.open(SOURCE/'snapshots'/f'{i:04d}.json.gz','rt') as f:nodes=np.array(json.load(f)[j]['nodes'])
    if not len(ps):dest.write_text(json.dumps(dict(state=state,status='NO_GEOMETRIC_PROPOSALS')));return
    measures=[GridMeasure(p[:2],sampler.hist[c]) for p in ps]
    reception=[]
    for p in ps:
        diff=nodes-p[:2];distance=np.linalg.norm(diff,axis=1);front=diff@np.array([math.cos(p[2]),math.sin(p[2])])>=0
        reception.append((distance<=p[3])&((p[4]==0)|front))
    reception=np.array(reception)
    for n in state.get("noise_budgets",[128,256,512]):
        for repeat in range(state.get("noise_repeats",3)):
            stats=[summarize(g.draw(n,1600000+i*100000+j*1000+repeat*128+k)[1]) for k,g in enumerate(measures)]
            logs=np.array([r['log_volume'] for r in stats]);z=logsumexp(logs)
            if not np.isfinite(z):runs.append(dict(n=n,repeat=repeat,status='ZERO_TOTAL_WEIGHT'));continue
            w=np.exp(logs-z);p_hit=w@reception
            runs.append(dict(n=n,repeat=repeat,status='WEIGHTED',source_ess=float(1/(w@w)),source_positive=int(np.isfinite(logs).sum()),noise_ess_median=float(np.median([r['ess'] for r in stats])),p_hit=p_hit.tolist(),top3=np.argsort(-p_hit,kind='stable')[:3].tolist(),directional_mass=float(w@(ps[:,4]==1)),mean_position=(w@ps[:,:2]).tolist(),log_volume=logs.tolist()))
    dest.write_text(json.dumps(dict(state=state,channel=c,history_length=len(sampler.hist[c]),direction_count=sum(r=='direction' for p,r,a in sampler.hist[c]),proposals=ps.tolist(),grid_dimension=[len(g.keys) for g in measures],constraint_rows=[len(g.lo) for g in measures],runs=runs,official_calls=0,continuations=0)))

if __name__=='__main__':
    analytic();states=json.loads((SOURCE/'selection.json').read_bytes())['states'];chosen=[]
    for phase in ['early','middle','late']:
        ss=[s for s in states if s['phase']==phase];chosen.extend(ss[int(k)] for k in np.linspace(0,len(ss)-1,4))
    (OUT/'selection.json').write_text(json.dumps(chosen,indent=2))
    with ProcessPoolExecutor(max_workers=6) as pool:
        for n,f in enumerate(as_completed([pool.submit(worker,s) for s in chosen]),1):f.result();print('MEASURE_STATES',n,len(chosen),flush=True)
