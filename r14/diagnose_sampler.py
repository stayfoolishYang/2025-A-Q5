"""Replay frozen failed worlds without modifying proposal RNG or acceptance rules."""
import json,gzip,math,collections
from dataclasses import asdict
from concurrent.futures import ProcessPoolExecutor,as_completed
from collect import ROOT
import world_sampler as ws
from engine import quantize_bearing,go_round
SOURCE=ROOT/'results/value_oracle'; OUT=ROOT/'results/sampler_diagnostics'
OriginalEngine=ws.SampledEngine
class CaptureEngine(OriginalEngine):
    latest=None
    def __init__(self,sources,fields):
        super().__init__(sources,fields);CaptureEngine.latest=self

def worker(job):
    state,k=job;i,j=state['id'],state['step'];dest=OUT/f'{i:04d}_{j:02d}_{k}.json'
    if dest.exists():return
    with gzip.open(SOURCE/'core/traces'/f'R12_{i:04d}.json.gz','rt') as f:trace=json.load(f)
    actions=ws.public_actions([a for a in trace['actions'] if a['path']!='/exit' and a['response']['virtual_time_s']<=state['time_s']])
    ws.SampledEngine=CaptureEngine;CaptureEngine.latest=None
    sampler=ws.WorldSampler(actions);seed=1400900+50*i+2*j+k
    try:sampler.sample(seed);reason='unexpected_compatible'
    except ws.SamplingUnavailable as e:reason=str(e)
    world=CaptureEngine.latest;failures=[]
    if world is not None:
        engine=OriginalEngine(list(world.sources.values()),world.fields)
        for h,a in enumerate(actions):
            p=a['position'];c=a['channel'];request={} if p is None else dict(position=dict(zip(['x','y'],p)),channel=c)
            r=engine.apply(a['path'],request);expected=a['response']
            bad=[key for key,value in expected.items() if r.get(key)!=value]
            if not bad:continue
            source=world.sources.get(c)
            row=dict(state_id=f'{i:04d}_{j:02d}',world_id=seed,channel=c,history_index=h,dog_position=p,historical_response=expected,replayed_response=r,mismatched_keys=bad)
            if source and p:
                base=math.degrees(math.atan2(source.y-p[1],source.x-p[0]))%360
                err=world.fields[c].value(p);angle=expected.get('svd_deg');raw=go_round((base+err)*100)%36000/100
                target_error=None if angle is None else (angle-base+180)%360-180
                lo=None if angle is None else max(-1.,target_error-.005+1e-9)
                hi=None if angle is None else min(1.,target_error+.005-1e-9)
                violation=None if angle is None else max(lo-err,err-hi,0.)
                row.update(source_position=[source.x,source.y],source_type=source.kind,source_heading=source.direction_deg,source_radius=source.receive_radius_m,true_geometric_bearing=base,angular_error=err,rounding_result=raw,historical_reported_angle=angle,replayed_reported_angle=r.get('svd_deg'),interval_low=lo,interval_high=hi,constraint_violation=violation,distance=math.hypot(source.x-p[0],source.y-p[1]),clamp_changed_report=(raw!=quantize_bearing(base,err)))
                if bad==['svd_deg']:
                    if raw==angle and quantize_bearing(base,err)!=angle:cls='ANGLE_ROUNDING_MISMATCH';mechanism='physical_clamp_after_rounding'
                    elif violation and violation>0:cls='NUMERIC_REPLAY_MISMATCH';mechanism='conditional_grid_outside_rounding_constraint'
                    else:cls='ANGLE_ROUNDING_MISMATCH';mechanism='requires_further_diagnosis'
                else:cls='RESPONSE_TYPE_MISMATCH';mechanism='requires_further_diagnosis'
            else:cls='RESPONSE_TYPE_MISMATCH';mechanism='source_absent'
            row.update(failure_class=cls,mechanism=mechanism);failures.append(row)
        latent=dict(sources=[asdict(s) for s in world.sources.values()],fields={str(c):dict(seed=f.seed,grid=[[x,y,float(v)] for (x,y),v in f.grid.items()]) for c,f in world.fields.items()})
    else:latent=None
    result=dict(state=state,seed=seed,reason=reason,history_actions=len(actions),known_count=len(sampler.known),failures=failures,latent_world=latent,official_calls=0)
    dest.write_text(json.dumps(result),encoding='utf-8')
if __name__=='__main__':
    OUT.mkdir(exist_ok=True);states=json.loads((SOURCE/'selection.json').read_bytes())['states'];jobs=[];counts=collections.Counter()
    for s in states:
        result=json.loads((ROOT/'results/sampler_qualification'/f'{s["id"]:04d}_{s["step"]:02d}.json').read_bytes())
        for k,w in enumerate(result['worlds']):
            counts[w['status']]+=1
            if w['status']!='compatible':jobs.append((s,k));counts[w['reason']]+=1
    (OUT/'original_counts.json').write_text(json.dumps(dict(counts),indent=2));print(dict(counts),flush=True)
    with ProcessPoolExecutor(max_workers=8) as pool:
        for n,f in enumerate(as_completed([pool.submit(worker,j) for j in jobs]),1):
            f.result()
            if n%25==0:print('DIAGNOSED',n,len(jobs),flush=True)
