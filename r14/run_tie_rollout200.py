"""Public response replay -> tie-aware paired sampled-world R12 continuations."""
import json,gzip,hashlib,time,copy,pickle
from concurrent.futures import ProcessPoolExecutor,as_completed
from collect import ROOT,StudySolver,rb,SRC
import numpy as np
from scipy.stats import t
from staged_world_sampler import FinalizationSampler
from paired_value_estimator import public_state,continuation,tail_mean
from world_sampler_v2 import SamplingUnavailable
OUT=ROOT/'results/tie_rollout200';SOURCE=ROOT/'results/value_oracle';OUT.mkdir(exist_ok=True)
CFG=dict(epsilon_probability=.002,max_candidates_including_R12=8,worlds=16,source_proposals=128,noise_proposals=512,sobol_power=12,confidence_family=.05,confidence_alternatives=7,risk='empirical loss CVaR90 <=0',candidate_overflow='whole state R12; no truncation',sampling_failure='whole state R12; retain partial paired records',scope='200-state calibration; not deployment or holdout confirmation')
def stable_seed(*x):return int.from_bytes(hashlib.sha256(':'.join(map(str,x)).encode()).digest()[:8],'big')
class RecordedEngine:
 ended=False;end_reason=''
 def __init__(self,actions):self.actions=actions;self.index=0
 def apply(self,path,request):
  a=self.actions[self.index];self.index+=1;assert path==a['path'],(self.index,path,a['path'])
  if a['position'] is not None:
   assert request['channel']==a['channel'];assert np.array_equal([request['position']['x'],request['position']['y']],a['position'])
  return copy.deepcopy(a['response'])
class Captured(Exception):pass
class Capture(StudySolver):
 target=0
 def decision(self,nodes):
  action=super().decision(nodes)
  if action[0]=='explore':
   step=getattr(self,'ordinal',0);self.ordinal=step+1
   if step==self.target:self.saved=public_state(self);self.nodes=np.array(nodes);raise Captured()
  return action

def freeze():
 path=OUT/'preregistration.json'
 if path.exists():return
 states=json.loads((SOURCE/'selection.json').read_bytes())['states'];rng=np.random.default_rng(202609120721);selected=[]
 for group in ['early','middle','late','N16_late']:
  pool=[s for s in states if s['sample_group']==group]
  selected.extend(pool[int(i)] for i in rng.choice(len(pool),50,replace=False))
 assert len({(s['id'],s['step']) for s in selected})==200
 (OUT/'selection.json').write_text(json.dumps(selected,indent=2))
 path.write_text(json.dumps(dict(config=CFG,selection_rule='50 each of frozen oracle sample groups; chosen without costs',Q1_history='old gates stay FAIL; new tie-aware exploration explicitly authorized',official_calls=0),indent=2))

def save(path,data):
 tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data));tmp.replace(path)

def worker(s):
 i,j=s['id'],s['step'];path=OUT/f'{i:04d}_{j:02d}.json';started=time.perf_counter()
 if path.exists() and json.loads(path.read_bytes()).get('complete'):return
 with gzip.open(SOURCE/'core/traces'/f'R12_{i:04d}.json.gz','rt') as f:trace=json.load(f)
 # Only archived public action/response fields enter state reconstruction.
 actions=[{k:a[k] for k in ('path','position','channel','response')} for a in trace['actions'] if a['path']!='/exit' and a['response']['virtual_time_s']<=s['time_s']]
 with gzip.open(SOURCE/'snapshots'/f'{i:04d}.json.gz','rt') as f:nodes=np.array(json.load(f)[j]['nodes'])
 seed=stable_seed('tie200',i,j);sampler=FinalizationSampler(actions,nodes,seed,12);P=sampler.unknown.pnew;threshold=np.sort(P)[-min(3,len(P))]-.002;C=sorted(set(np.flatnonzero(P>=threshold).tolist()+[0]))
 result=dict(state=s,seed=seed,candidates=C,p_new=P.tolist(),config=CFG,paired=[],selected=0,complete=False,official_calls=0)
 if len(C)>8:
  result.update(status='CANDIDATE_CAP_R12',complete=True,seconds=time.perf_counter()-started);save(path,result);return
 api=rb.EngineAdapter(RecordedEngine(actions));cfg=json.loads((SRC/'configs/q4_known16_tri25_R12.yaml').read_bytes());solver=Capture(api,True,'P4','cpu',cfg.get('particles',16384),diagnostic=cfg);solver.target=j
 try:solver.run()
 except Captured:pass
 assert hasattr(solver,'saved') and np.array_equal(solver.nodes,nodes) and api.virtual_time==s['time_s'] and api._engine.index==len(actions)
 state=solver.saved;StudySolver.instances.clear()
 for m in range(16):
  try:
   world,meta=sampler.sample(stable_seed(seed,m),128,512)
   base=continuation(state,world,nodes,0);costs={0:base}
   for c in C:
    if c!=0:costs[c]=continuation(state,world,nodes,c)
   result['paired'].append(dict(world=m,costs=costs,delta={c:base-v for c,v in costs.items() if c!=0},sampled_count=len(world.sources)))
   result.update(status='RUNNING',seconds=time.perf_counter()-started);save(path,result)
  except (SamplingUnavailable,AssertionError,ValueError,RuntimeError,TimeoutError) as e:
   result.update(status='UNAVAILABLE_R12',reason=f'{type(e).__name__}:{e}',complete=True,seconds=time.perf_counter()-started);save(path,result);return
 estimates={};passed=[];critical=float(t.ppf(1-.05/7,15))
 for c in C:
  if c==0:continue
  x=np.array([r['delta'][c] for r in result['paired']]);mean=float(x.mean());se=float(x.std(ddof=1)/4);lcb=mean-critical*se;cvar=tail_mean(-x)
  estimates[c]=dict(mean=mean,se=se,lcb=lcb,ucb=mean+critical*se,loss_cvar90=cvar)
  if lcb>0 and cvar<=0:passed.append((lcb,c))
 result.update(status='QUALIFIED_ESTIMATE',estimates=estimates,selected=max(passed)[1] if passed else 0,complete=True,seconds=time.perf_counter()-started);save(path,result)

if __name__=='__main__':
 freeze();jobs=json.loads((OUT/'selection.json').read_bytes())
 with ProcessPoolExecutor(max_workers=8) as pool:
  for n,f in enumerate(as_completed([pool.submit(worker,s) for s in jobs]),1):
   try:f.result()
   except Exception as e:print('WORKER_ERROR',repr(e),flush=True);raise
   print('CALIBRATION_STATES',n,200,flush=True)
