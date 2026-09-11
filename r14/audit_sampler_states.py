"""Compatibility audit across all2000 frozen oracle states; no oracle costs read."""
import json,gzip,copy
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
from collect import ROOT
from world_sampler import WorldSampler,SamplingUnavailable
SOURCE=ROOT/'results/value_oracle';OUT=ROOT/'results/sampler_qualification'
def worker(state):
    i,j=state['id'],state['step'];dest=OUT/f'{i:04d}_{j:02d}.json'
    if dest.exists():return json.loads(dest.read_bytes())
    with gzip.open(SOURCE/'core/traces'/f'R12_{i:04d}.json.gz','rt') as f:trace=json.load(f)
    actions=[a for a in trace['actions'] if a['path']!='/exit' and a['response']['virtual_time_s']<=state['time_s']]
    rows=[]
    try:
        sampler=WorldSampler(actions)
        for k in range(2):
            try:
                world,meta=sampler.sample(1400900+2*i*25+2*j+k)
                a=copy.deepcopy(world);b=copy.deepcopy(world)
                for c in world.fields:
                    p,q=[1999.,2122.],[-2111.,-1809.]
                    ap=a.fields[c].value(p);aq=a.fields[c].value(q);bq=b.fields[c].value(q);bp=b.fields[c].value(p)
                    assert ap==bp and aq==bq
                rows.append(dict(status='compatible',**meta))
            except SamplingUnavailable as e:rows.append(dict(status='unavailable',reason=str(e)))
    except SamplingUnavailable as e:rows.append(dict(status='unavailable',reason=str(e)))
    result=dict(id=i,step=j,worlds=rows,official_calls=0);OUT.mkdir(exist_ok=True);dest.write_text(json.dumps(result));return result
if __name__=='__main__':
    states=json.loads((SOURCE/'selection.json').read_bytes())['states']
    with ProcessPoolExecutor(max_workers=8) as pool:
        for n,f in enumerate(as_completed([pool.submit(worker,s) for s in states]),1):
            r=f.result()
            if n%100==0:print('SAMPLER_STATES',n,2000,flush=True)
