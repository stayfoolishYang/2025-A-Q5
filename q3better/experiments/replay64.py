"""Replay the archived 64 A/D pairs without generating or selecting new scenes."""
import csv
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'B_solver'
SIM = Path(sys.argv[2]) if len(sys.argv)>2 else Path('D:/桌面/2026国赛/b模拟器/Jammers-Offline-Windows')
sys.path[:0] = [str(ROOT),str(BASE),str(BASE/'experiments'),str(SIM)]
from engine import Engine
from scenario_io import load_scenario
from recovered_benchmark import EngineAdapter, source_hashes
from phase_audit import TaggedSolver
from q3_stop16_pilot import CONFIG, audit
from active_failure import ActiveFailureSolver
import directional.fallback_cost as fallback


def trace(path):
    with gzip.open(path,'rt',encoding='utf-8') as f: return json.load(f)


def run(out):
    out.mkdir(parents=True,exist_ok=False)
    def save(name,obj):
        (out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    published=json.loads((ROOT/'package_manifest.json').read_bytes())
    for name,sha in published['files'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha
    source=ROOT/'results/active_failure_64_01'
    frozen=json.loads((source/'manifest.json').read_bytes())
    hashes=source_hashes(SIM)
    assert hashes==frozen['source_hashes'], 'Engine or snapshot differs from archived execution'
    (out/'scenes').mkdir()
    cases=[]
    for rec in frozen['records']:
        path=source/rec['file']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==rec['file_sha256']
        (out/rec['file']).write_bytes(path.read_bytes())
        name=rec['case']
        cases.append((name,rec['cohort'],path,{v:source/f'{name}_{v}.json.gz' for v in 'AD'}))
    save('manifest.json',dict(source_manifest_sha256=hashlib.sha256((source/'manifest.json').read_bytes()).hexdigest(),
         source_hashes=hashes,records=frozen['records'],execution_backend='LOCAL_DEV',
         execution_purpose='FRAMEWORK_INTEGRATION',production_eligible=False,
         note='Exact replay of previously used 64 scenes; not another fresh confirmation set'))
    rows=[];pairs=[];original=fallback.ordered_grid
    for name,cohort,path,history in cases:
        raw=json.loads(path.read_bytes());save(name+'_scene.json',raw);current={}
        for variant in 'AD':
            engine=Engine(load_scenario(raw));api=EngineAdapter(engine)
            cls=ActiveFailureSolver if variant=='D' else TaggedSolver
            solver=cls(api,False,'P3',diagnostic=dict(CONFIG,local_order=variant=='D'))
            if variant=='D': solver.discovery_route='refresh_after_localize'
            events=[]
            def checked_grid(poly,position,local=True,grid_version='grid_v0'):
                points=original(poly,position,local,grid_version)
                assert sorted(map(tuple,points))==sorted(map(tuple,original(poly,position,False,grid_version)))
                channel=next(c for c,t in solver.tracks.items() if t['poly'] is poly)
                n=misses=0
                for action in api.log:
                    if action['path']!='/measure' or action['channel']!=channel:continue
                    response=action['response']['measure_result']
                    if response=='direction': n+=1;misses=0
                    elif response=='no_signal' and action['stage']=='active_localization':misses+=1
                if variant=='D':
                    assert solver.tracks[channel]['negatives']==misses
                    assert n>=8 or misses>=3, 'Premature fallback remains'
                events.append(dict(channel=channel,directions=n,active_misses=misses,points=len(points)))
                return points
            fallback.ordered_grid=checked_grid
            start=time.perf_counter();error='';result={}
            try:
                result=solver.run();audit(api.log,False)
                assert not solver.tracks and engine.cleared==set(engine.sources)
                if variant in history:assert api.log==trace(history[variant])['actions'],'Historical action mismatch'
            except Exception as exc:error=repr(exc)
            finally:fallback.ordered_grid=original
            row=dict(case=name,cohort=cohort,variant=variant,sources=len(engine.sources),cleared=len(engine.cleared),
                seconds=api.virtual_time,seconds_per_source=api.virtual_time/len(engine.sources),
                fallbacks=solver.fallbacks,optical_seconds=api.stages['optical_fallback']['total_s'],
                measures=api.measures,clear_attempts=api.clear_attempts,wall_seconds=time.perf_counter()-start,
                passed=not error,error=error)
            rows.append(row);current[variant]=row
            with gzip.open(out/f'{name}_{variant}.json.gz','wt',encoding='utf-8') as f:
                json.dump(dict(row=row,result=result,actions=api.log,grid_events=events,targets=list(solver.trace.values())),f)
            save('partial_rows.json',rows)
            if error:raise RuntimeError(f'{name}/{variant}: {error}')
        a,d=(current[v]['seconds'] for v in 'AD')
        pair=dict(case=name,cohort=cohort,sources=current['A']['sources'],A_s=a,D_s=d,
                  D_saved_vs_A_s=a-d,D_saved_per_source_s=(a-d)/current['A']['sources'])
        pairs.append(pair);print(json.dumps(pair),flush=True)
    assert source_hashes(SIM)==hashes
    for name,data in (('cases.csv',rows),('pairs.csv',pairs)):
        with (out/name).open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
    save('verification.json',dict(runs=len(rows),all_full_clear_and_audited=True,historical_A_D_matches=128,
                                published_source_unchanged=True,grid_sets_preserved=True,D_fallback_counters_checked=True))


if __name__=='__main__':
    run(Path(sys.argv[1]).resolve())
