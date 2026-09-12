import json,gzip,hashlib,copy
from concurrent.futures import ProcessPoolExecutor,as_completed
from collect import ROOT
import numpy as np
from staged_world_sampler import FinalizationSampler as DiscoveryWorldSampler
from world_sampler_v2 import SamplingUnavailable
OUT=ROOT/'results/q1_finalization';OUT.mkdir(exist_ok=True)
def worker(job):
 state,bank=job;i,j=state['id'],state['step'];path=OUT/f'{i:04d}_{j:02d}_{bank}.json'
 if path.exists():return
 seed=int.from_bytes(hashlib.sha256(f'Q1final-v2:{i}:{j}:{bank}'.encode()).digest()[:8],'big')
 with gzip.open(ROOT/'results/value_oracle/core/traces'/f'R12_{i:04d}.json.gz','rt') as f:trace=json.load(f)
 actions=[a for a in trace['actions'] if a['path']!='/exit' and a['response']['virtual_time_s']<=state['time_s']]
 with gzip.open(ROOT/'results/value_oracle/snapshots'/f'{i:04d}.json.gz','rt') as f:nodes=np.array(json.load(f)[j]['nodes'])
 try:
  s=DiscoveryWorldSampler(actions,nodes,seed,12);u=s.unknown;order=np.argsort(-u.pnew,kind='stable')
  result=dict(status='FUNCTIONAL_READY',known=len(s.known),classes=len(u.groups),p_new=u.pnew.tolist(),M=u.m.tolist(),pm=u.pm.tolist(),top3=order[:3].tolist(),top4=order[:4].tolist(),candidates=sorted(set(order[:4].tolist()+[0])),gap3=float(u.pnew[order[2]]-u.pnew[order[3]]) if len(order)>3 else None,groups=[dict(channels=cs,history_length=len(h),L=u.data[h]['L']) for h,cs in u.groups.items()])
  try:
   world,meta=s.sample(seed,128,512);result['world_replay']='PASS';result['sampled_count']=len(world.sources);result['sampler_meta']=meta
   # Historical replay is inside sample; query-order independence remains required.
   other=copy.deepcopy(world)
   for c in world.fields:
    p,q=[1999.,2122.],[-2111.,-1809.];a=world.fields[c].value(p);b=world.fields[c].value(q);bb=other.fields[c].value(q);aa=other.fields[c].value(p);assert a==aa and b==bb
  except SamplingUnavailable as e:result['world_replay']='FAIL';result['world_reason']=str(e)
 except SamplingUnavailable as e:result=dict(status='UNAVAILABLE',reason=str(e),world_replay='FAIL')
 path.write_text(json.dumps(dict(state=state,bank=bank,seed=seed,result=result,official_calls=0,continuations=0)))
if __name__=='__main__':
 states=json.loads((ROOT/'results/rb64/selection.json').read_bytes())
 (OUT/'preregistration.json').write_text(json.dumps(dict(version='Q1final-v2',states=64,banks=3,new_seed_namespace='Q1final-v2',sobol_points=4096,probability_fraction_within_002=.95,max_probability_range=.05,max_count_tv=.02,candidates='top4 union R12 index0',candidate_gate='Every state: union of 3 banks top3 must be contained in every bank candidates',world_gate='192/192 constructed and exact replay',proposal_stages=[65536,131072,262144],target_valid=128,noise_per_position=512,on_cap='unavailable, no relaxed conditions',old_result='Q1-U-v1 remains FAIL'),indent=2))
 with ProcessPoolExecutor(max_workers=6) as pool:
  for n,f in enumerate(as_completed([pool.submit(worker,(s,b)) for s in states for b in range(3)]),1):
   f.result()
   if n%24==0:print('Q1U_BANKS',n,192,flush=True)
