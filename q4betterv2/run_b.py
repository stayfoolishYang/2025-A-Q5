"""Offline B: frozen C-TSPN with original certified25 and dynamic rerouting."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'source'));sys.path.insert(0,str(ROOT/'offline_engine'))
from engine import Engine
from scenario_io import load_scenario
from recovered_benchmark import EngineAdapter
from ctspn import CTSolver

def main():
    p=argparse.ArgumentParser();p.add_argument('--scene',type=Path,default=ROOT/'example_scene.json');p.add_argument('--output',type=Path,default=ROOT/'run_output.json');a=p.parse_args()
    raw=json.loads(a.scene.read_bytes());scene=load_scenario(raw);api=EngineAdapter(Engine(scene));cfg=json.loads((ROOT/'config_B.json').read_bytes())
    solver=CTSolver(api,True,'P4','cpu',cfg['particles'],diagnostic=cfg);result=solver.run()
    assert result['cleared']==len(scene.jammers) and solver.api.pending is None
    result.update(total_sources=len(scene.jammers),failed_clears=api.clear_attempts-len(scene.jammers),distance_m=api.distance,ct_events=solver.ct_events,actions=api.log,evidence='LOCAL_DEV / FRAMEWORK_INTEGRATION; not official production validation')
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('actions','ct_events')},ensure_ascii=False))
if __name__=='__main__':main()
