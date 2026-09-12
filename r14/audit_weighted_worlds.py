import json,gzip,copy
from concurrent.futures import ProcessPoolExecutor,as_completed
from collect import ROOT
from weighted_world_sampler import WeightedWorldSampler,SamplingUnavailable
SOURCE=ROOT/'results/value_oracle';OUT=ROOT/'results/posterior_worlds_pivot';OUT.mkdir(exist_ok=True)
def worker(job):
    s,repeat=job;i,j=s['id'],s['step'];p=OUT/f'{i:04d}_{j:02d}_{repeat}.json'
    if p.exists():return
    with gzip.open(SOURCE/'core/traces'/f'R12_{i:04d}.json.gz','rt') as f:trace=json.load(f)
    actions=[a for a in trace['actions'] if a['path']!='/exit' and a['response']['virtual_time_s']<=s['time_s']]
    sampler=WeightedWorldSampler(actions)
    seed=int.from_bytes(__import__('hashlib').sha256(f'Q1:{i}:{j}:{repeat}'.encode()).digest()[:8],'big')
    try:
        world,meta=sampler.sample(seed,128,512)
        other=copy.deepcopy(world)
        for c in world.fields:
            p1,p2=[1999,2122],[-2111,-1809]
            a=world.fields[c].value(p1);b=world.fields[c].value(p2)
            bb=other.fields[c].value(p2);aa=other.fields[c].value(p1)
            assert a==aa and b==bb
        result=dict(status='EXACT_REPLAY',**meta)
    except SamplingUnavailable as e:result=dict(status='UNAVAILABLE',reason=str(e))
    p.write_text(json.dumps(dict(state=s,repeat=repeat,seed=seed,result=result,official_calls=0,continuations=0)))
if __name__=='__main__':
    states=json.loads((ROOT/'results/posterior_measure/selection.json').read_bytes())
    with ProcessPoolExecutor(max_workers=6) as pool:
        for n,f in enumerate(as_completed([pool.submit(worker,(s,r)) for s in states for r in range(3)]),1):f.result();print('WEIGHTED_WORLDS',n,36,flush=True)
