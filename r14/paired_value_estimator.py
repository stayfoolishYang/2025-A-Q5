"""Offline estimator qualification: only public solver state and sampled worlds.
No oracle costs, true source data or actual-engine reference accepted.
"""
import copy,math
from types import SimpleNamespace
import numpy as np
from scipy.stats import t
from solver import Solver
from oracle_replay import run_branch
from world_sampler import WorldSampler,SamplingUnavailable

def public_state(solver):
    fields=set(Solver(None,True,'P4','cpu',solver.particles,diagnostic=solver.diagnostic).__dict__)-{'api'}
    return dict(solver=copy.deepcopy({k:solver.__dict__[k] for k in fields}),
        position=solver.api.position.copy(),channel=solver.api.channel,virtual_time=solver.api.virtual_time,stage=solver.api.stage)

def continuation(state,world,nodes,index):
    # Reuse the verified continuation machinery; its engine input is exclusively
    # the newly sampled world, never the evaluation simulator.
    proxy=SimpleNamespace(**state['solver'])
    proxy.api=SimpleNamespace(_engine=world,position=state['position'],channel=state['channel'],virtual_time=state['virtual_time'],stage=state['stage'])
    return run_branch(proxy,nodes,index)['cost']

def tail_mean(values,alpha=.9):
    x=np.sort(values)[::-1];mass=len(x)*(1-alpha);k=int(mass)
    return float((x[:k].sum()+(mass-k)*x[k])/mass)

def estimate(state,actions,nodes,seed,max_worlds=64):
    sampler=WorldSampler(actions);pred=sampler.belief.predict(nodes)
    if not pred['available']:return dict(available=False,reason='prediction unavailable',selected=0)
    top=np.argsort(-pred['probability_any'],kind='stable')[:3]
    candidates=[int(i) for i in top if i!=0];active=set(candidates);samples={i:[] for i in candidates};looks=[]
    # Bonferroni across three candidates and four planned looks; a model-based
    # t approximation, not a distribution-free sequential or safety guarantee.
    for m in range(max_worlds):
        try:world,meta=sampler.sample(seed+m)
        except SamplingUnavailable as e:return dict(available=False,reason=str(e),selected=0,worlds=m)
        try:
            base=continuation(state,world,nodes,0)
            for i in sorted(active):samples[i].append(base-continuation(state,world,nodes,i))
        except (RuntimeError,AssertionError,ValueError) as e:
            return dict(available=False,reason=f'continuation:{type(e).__name__}:{e}',selected=0,worlds=m)
        if m+1 in (8,16,32,64):
            current={}
            for i in sorted(active):
                x=np.array(samples[i]);mean=float(x.mean());se=float(x.std(ddof=1)/np.sqrt(len(x)));k=float(t.ppf(1-.05/12,len(x)-1))
                current[i]=dict(mean=mean,se=se,lcb=mean-k*se,ucb=mean+k*se,loss_cvar90=tail_mean(-x))
            looks.append(dict(worlds=m+1,candidates=current))
            active={i for i in active if current[i]['ucb']>0}
            if not active:break
    accepted=[]
    if looks and looks[-1]['worlds']==max_worlds:
        accepted=[(v['lcb'],i) for i,v in looks[-1]['candidates'].items() if v['lcb']>0 and v['loss_cvar90']<=0]
    selected=max(accepted)[1] if accepted else 0
    return dict(available=True,selected=selected,candidates=candidates,paired_advantages=samples,looks=looks,worlds=m+1,
        approximation='history-compatible finite support; independent-grid conditional noise; uncalibrated proposal density')
