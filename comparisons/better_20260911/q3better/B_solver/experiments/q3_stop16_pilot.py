"""Small Q3 paired pilot; reuse stop16 hooks without changing the frozen Q4 code."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import numpy as np

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
from recovered_benchmark import EngineAdapter, digest, save, source_hashes
from phase_audit import TaggedSolver
from geometry import coverage

CONFIG=dict(enabled=False,local_order=False,particles=16384,grid_version='grid_v1',clearance_point='mec_center')


def audit(actions, stop):
    from engine import go_round
    cleared=set();groups=[];position=(0.,0.);channel=1;us=0;complete=None
    for i,a in enumerate(actions):
        r=a['response'];assert r.get('accepted') is True
        if a['path'] in ('/measure','/clear'):
            assert complete is None
            p=tuple(a['position']);c=a['channel']
            us+=go_round(1e12*math.hypot(p[0]-position[0],p[1]-position[1])/5000000)
            if a['path']=='/measure':
                us+=5000000+1000000*int(c!=channel)
                if a['stage']=='discovery':
                    if not groups or groups[-1]['p']!=p:
                        order=[channel]+[x for x in range(1,21) if x!=channel]
                        groups.append(dict(p=p,expected=[x for x in order if x not in cleared],actual=[]))
                    groups[-1]['actual'].append(c)
                channel=c
            else:
                success=r['clear_result']=='success';us+=5000000 if success else 3000000
                if success:
                    assert c not in cleared;cleared.add(c)
                    if stop and len(cleared)==16:complete=i
            position=p
        assert round(r['virtual_time_s']*1e6)==us
    assert actions[0]['path']=='/enter' and actions[-1]['path']=='/exit'
    assert actions[-1]['response']['exit_reason']=='user_exit'
    assert sum(a['path']=='/exit' for a in actions)==1
    nodes=set(map(tuple,coverage(False)));visited=[g['p'] for g in groups]
    assert len(visited)==len(set(visited)) and set(visited)<=nodes
    if complete is None:assert set(visited)==nodes
    else:assert complete==len(actions)-2
    for i,g in enumerate(groups):
        expected=g['expected']
        if complete is not None and i==len(groups)-1 and actions[complete-1]['stage']=='discovery' and actions[complete-1]['response'].get('measure_result')=='near':
            expected=expected[:len(g['actual'])]
        assert g['actual']==expected
    return len(groups)


def run_pair(job):
    out,sim,rec=job;out=Path(out);sys.path.insert(0,sim)
    from engine import Engine
    from scenario_io import load_scenario
    raw=json.loads((out/rec['file']).read_bytes());assert digest(raw)==rec['scene_hash']
    rows=[];logs=[]
    for v in 'AB':
        engine=Engine(load_scenario(raw));api=EngineAdapter(engine)
        solver=TaggedSolver(api,False,'P3',diagnostic=CONFIG)
        # Pilot only: reuse the already tested hook; public Q3 configs stay disabled.
        solver.stop_after_public_max_clear=v=='B'
        start=time.perf_counter();error='';result={};nodes=None
        try:
            result=solver.run();nodes=audit(api.log,v=='B')
            assert not solver.tracks
            assert engine.cleared=={j.channel for j in engine.scenario.jammers}
        except Exception as e:error=repr(e)
        row=dict(id=rec['id'],cohort=rec['cohort'],variant=v,total=rec['total'],cleared=len(engine.cleared),
            virtual_time_s=api.virtual_time,seconds_per_source=api.virtual_time/rec['total'],runtime_s=time.perf_counter()-start,
            full_clear=len(engine.cleared)==rec['total'],error=error,audit_passed=not error,nodes=nodes,
            completion_reason=result.get('completion_reason'),distance_m=api.distance,measures=api.measures,
            switches=api.switches,clear_attempts=api.clear_attempts,fallbacks=solver.fallbacks,
            scene_hash=rec['scene_hash'])
        rows.append(row);logs.append(api.log)
        with gzip.open(out/'traces'/f'{v}_{rec["id"]:03d}.json.gz','wt',encoding='utf-8') as f:
            json.dump(dict(row=row,actions=api.log,targets=list(solver.trace.values()),stages=api.stages),f)
    a,b=logs
    if rec['total']<16:equal=a==b;tail=0.
    else:
        cleared=set();end=None
        for i,x in enumerate(a):
            if x['path']=='/clear' and x['response'].get('accepted') is True and x['response'].get('clear_result')=='success':
                cleared.add(x['channel'])
                if len(cleared)==16:end=i;break
        equal=end is not None and b[:-1]==a[:end+1] and b[-1]['path']=='/exit'
        tail=a[-1]['response']['virtual_time_s']-a[end]['response']['virtual_time_s'] if end is not None else None
    delta=rows[1]['virtual_time_s']-rows[0]['virtual_time_s']
    pair=dict(id=rec['id'],cohort=rec['cohort'],total=rec['total'],saved_total_s=-delta,
              saved_s_per_source=-delta/rec['total'],baseline_tail_s=tail,prefix_passed=equal,
              nonincrease=delta<=0,both_success=all(r['full_clear'] and r['audit_passed'] for r in rows))
    save(out/'rows'/f'{rec["id"]:03d}.json',dict(rows=rows,pair=pair))
    return rows,pair


def main():
    p=argparse.ArgumentParser();p.add_argument('--sim-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--workers',type=int,default=4);a=p.parse_args();sim=a.sim_root.resolve();out=a.output.resolve()
    if out.exists():raise FileExistsError('Use a new pilot directory; never overwrite evidence')
    sys.path.insert(0,str(sim));from scenario_io import generate_document
    records=[];scenes=[];index=0
    while len(records)<40:
        seed=hashlib.sha256(f'2026B-q3-stop16-pilot-v1:{index}'.encode()).hexdigest();index+=1
        raw=generate_document(problem=3,seed_hex=seed,format='native');n=len(raw['jammers'])
        if len(records)>=32 and n!=16:continue
        records.append(dict(id=len(records),cohort='pilot32' if len(records)<32 else 'extra16sources8',total=n,
                            seed_hex=seed,file=f'scenes/{len(records):03d}.json',scene_hash=digest(raw)))
        scenes.append(raw)
    out.mkdir(parents=True);(out/'traces').mkdir();hashes=source_hashes(sim)
    save(out/'manifest.json',dict(records=records,config=CONFIG,variants={'A':'Q3 P3 original stop','B':'same Q3 plus public-max stop hook'},
         source_hashes=hashes,pilot_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
         simulator_root=str(sim),python=sys.version,executable=sys.executable,
         evidence='LOCAL_DEV / FRAMEWORK_INTEGRATION',production_eligible=False,
         scope='Exploratory deterministic pilot, not a new confirmatory holdout; Q3 7 nodes unchanged; no HTTP or official execution'))
    for rec,scene in zip(records,scenes):save(out/rec['file'],scene)
    os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
    rows=[];pairs=[]
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        futures=[pool.submit(run_pair,(str(out),str(sim),r)) for r in records]
        for i,f in enumerate(as_completed(futures),1):
            r,pair=f.result();rows+=r;pairs.append(pair)
            print(f'{i}/40 scene={pair["id"]} N={pair["total"]} saved={pair["saved_total_s"]:.6f}s pass={pair["prefix_passed"] and pair["both_success"]}',flush=True)
    assert source_hashes(sim)==hashes
    for name,data in (('cases.csv',rows),('pairs.csv',pairs)):
        with (out/name).open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(sorted(data,key=lambda r:r['id']))
    report={}
    for cohort in ('pilot32','extra16sources8'):
        group=[x for x in pairs if x['cohort']==cohort];variants={}
        for v in 'AB':
            r=[x for x in rows if x['cohort']==cohort and x['variant']==v];t=[x['seconds_per_source'] for x in r]
            variants[v]=dict(n=len(r),full=sum(x['full_clear'] for x in r),mean_per_source=float(np.mean(t)),
                P95=float(np.percentile(t,95)),P99=float(np.percentile(t,99)),mean_total=float(np.mean([x['virtual_time_s'] for x in r])))
        report[cohort]=dict(variants=variants,mean_saving_s=float(np.mean([x['saved_total_s'] for x in group])),
            mean_saving_per_source=float(np.mean([x['saved_s_per_source'] for x in group])),
            n16=sum(x['total']==16 for x in group),positive_savings=sum(x['saved_total_s']>0 for x in group),
            min_saving_s=min(x['saved_total_s'] for x in group),max_saving_s=max(x['saved_total_s'] for x in group))
    report['all_integrity_passed']=all(p['prefix_passed'] and p['nonincrease'] and p['both_success'] for p in pairs)
    save(out/'summary.json',report);print(json.dumps(report),flush=True)
    assert report['all_integrity_passed']

if __name__=='__main__':main()
