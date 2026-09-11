"""Run one explicitly UI-verified official practice case with frozen candidates."""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--problem',type=int,choices=(3,4),required=True)
    p.add_argument('--case',required=True)
    a=p.parse_args()
    out=ROOT/'official_candidate_practice'
    gate=out/f'q{a.problem}_{a.case}_before.txt'
    text=gate.read_text(encoding='utf-8')
    assert a.case in text and '等待机器狗进入' in text
    assert f'问题{a.problem}\n演练' in text
    dest=out/f'q{a.problem}_{a.case}.json'
    assert not dest.exists() and not dest.with_suffix('.jsonl').exists()
    src=ROOT/('q3better/B_solver' if a.problem==3 else 'q4better')
    sys.path.insert(0,str(src))
    from solver import Solver
    from simulator import Client
    if a.problem==3:
        cfg=dict(enabled=False,local_order=False,particles=16384,grid_version='grid_v1',clearance_point='mec_center')
    else:
        cfg=json.loads((src/'configs/q4_public_max37_C.yaml').read_text(encoding='utf-8'))
    api=Client('202627002054',dest.with_suffix('.jsonl'))
    s=Solver(api,a.problem==4,'P3' if a.problem==3 else 'P4',
             device='cpu' if a.problem==3 else 'cuda',diagnostic=cfg)
    if a.problem==3:s.discovery_route='refresh_after_localize'
    result=s.run()
    result.update(evidence='official_practice',case=a.case,problem=a.problem,config=cfg,
                  discovery_route=s.discovery_route,device=s.device)
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
