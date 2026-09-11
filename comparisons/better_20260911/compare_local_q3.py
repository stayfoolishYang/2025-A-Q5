"""Paired existing scenarios, local frozen P3; no HTTP or default changes."""
import csv
import gzip
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCAL = ROOT.parents[1] / 'B_solver'
ENGINE = Path('G:/QQ/jammers_linux')
sys.path[:0] = [str(LOCAL), str(ENGINE)]
from solver import Solver
from recovered_benchmark import EngineAdapter
from engine import Engine
from scenario_io import load_scenario

def main():
    out = ROOT / 'local_q3_pairs'
    out.mkdir(exist_ok=False)
    scenes = sorted((ROOT/'q3better/B_solver/results/q3_stop16_pilot_01/scenes').glob('*.json'))
    assert len(scenes) == 32
    manifest = dict(local_files={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in LOCAL.glob('*.py')}, engine_files={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in ENGINE.glob('*.py')}, scenes={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in scenes}, config='P3 default grid_v0; candidate only sets refresh_after_localize', formal_tests=0)
    (out/'PLAN.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    rows=[]
    for scene in scenes:
        for variant in ('A','B'):
            e=Engine(load_scenario(json.loads(scene.read_bytes())))
            api=EngineAdapter(e)
            s=Solver(api,False,'P3')
            if variant=='B': s.discovery_route='refresh_after_localize'
            result=s.run()
            assert e.cleared=={j.channel for j in e.scenario.jammers}
            assert api.log[-1]['path']=='/exit'
            assert all(a['response'].get('accepted') is True for a in api.log)
            result.update(case=scene.stem,variant=variant,total=len(e.scenario.jammers))
            rows.append(result)
            with gzip.open(out/f'{scene.stem}_{variant}.json.gz','wt',encoding='utf-8') as f:
                json.dump(dict(result=result,actions=api.log),f)
        print(scene.stem,rows[-2]['mean_time_per_source_s'],rows[-1]['mean_time_per_source_s'],flush=True)
    with (out/'cases.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)

if __name__=='__main__': main()
