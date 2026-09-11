"""Fixed local-only repeat; frozen snapshots, no Client or HTTP service."""
import csv
import gzip
import hashlib
import json
import math
import sys
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parent
SRC=ROOT/'q4better'
SIM=Path('G:/QQ/jammers_linux')
sys.path[:0]=[str(SRC),str(SIM)]
from solver import Solver
from recovered_benchmark import EngineAdapter, digest
from scenario_io import load_scenario, generate_document
from engine import Engine, go_round

def main():
    out=ROOT/'local_repeat_32'
    out.mkdir(exist_ok=False)
    configs={v:json.loads((SRC/f'configs/q4_public_max37_{v}.yaml').read_bytes()) for v in 'ABC'}
    q3cfg=dict(enabled=False,local_order=False,particles=16384,grid_version='grid_v1',clearance_point='mec_center')
    records=[]
    for i,p in enumerate(sorted((ROOT/'q3better/B_solver/results/q3_stop16_pilot_01/scenes').glob('*.json'))):
        records.append(dict(problem=3,id=i,scene=json.loads(p.read_bytes())))
    original=json.loads((SRC/'results/public_max37/frozen/manifest.json').read_bytes())
    for r in original['records'][:32]:
        scene=generate_document(seed_hex=r['seed_hex'],problem=4,format='native')
        assert digest(scene)==r['scene_hash']
        records.append(dict(problem=4,id=r['id'],scene=scene))
    assert len(records)==64
    files=list(SRC.glob('*.py'))+list((SRC/'directional').glob('*.py'))+list(SIM.glob('*.py'))+[Path(__file__)]
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    (out/'PLAN.json').write_text(json.dumps(dict(records=records,configs=configs,q3_config=q3cfg,
        hashes=hashes,device_q3='cpu',device_q4='cuda',planned_runs=160,
        evidence='Repeated existing development scenes; not new holdout',official_calls=0),indent=2),encoding='utf-8')
    rows=[]
    with (out/'cases.csv').open('x',newline='',encoding='utf-8') as f:
        writer=None
        for r in records:
            traces={}
            for v in ('AB' if r['problem']==3 else 'ABC'):
                e=Engine(load_scenario(r['scene']));api=EngineAdapter(e)
                cfg=q3cfg if r['problem']==3 else configs[v]
                s=Solver(api,r['problem']==4,'P3' if r['problem']==3 else 'P4',
                    device='cpu' if r['problem']==3 else 'cuda',diagnostic=cfg)
                if r['problem']==3 and v=='B':s.discovery_route='refresh_after_localize'
                result=s.run()
                assert e.cleared=={j.channel for j in e.scenario.jammers} and not s.tracks
                pos=(0.,0.);ch=1;us=0;cleared=set()
                for a in api.log:
                    reply=a['response'];assert reply['accepted'] is True
                    if a['path'] in ('/measure','/clear'):
                        p=a['position'];us+=go_round(1e12*math.hypot(p[0]-pos[0],p[1]-pos[1])/5000000)
                        if a['path']=='/measure':us+=5000000+1000000*(ch!=a['channel']);ch=a['channel']
                        else:
                            ok=reply['clear_result']=='success';us+=5000000 if ok else 3000000
                            if ok:cleared.add(a['channel'])
                        pos=p
                    assert round(reply['virtual_time_s']*1e6)==us
                assert api.log[-1]['path']=='/exit' and api.log[-1]['response']['exit_reason']=='user_exit'
                result.update(problem=r['problem'],case=r['id'],variant=v,total=len(e.scenario.jammers),audit_passed=True)
                with gzip.open(out/f'q{r["problem"]}_{r["id"]:03d}_{v}.json.gz','wt',encoding='utf-8') as z:
                    json.dump(dict(result=result,actions=api.log),z)
                traces[v]=api.log
                if writer is None:writer=csv.DictWriter(f,fieldnames=result.keys());writer.writeheader()
                writer.writerow(result);f.flush();rows.append(result)
                print(f'{len(rows)}/160 Q{r["problem"]} {r["id"]} {v}: {result["mean_time_per_source_s"]:.3f} s/source full',flush=True)
            if r['problem']==4:
                a,b=traces['A'],traces['B'];end=len(a)-1
                if len(e.scenario.jammers)==16:
                    done=set()
                    for i,x in enumerate(a):
                        if x['path']=='/clear' and x['response'].get('clear_result')=='success':done.add(x['channel'])
                        if len(done)==16:end=i+1;break
                assert b[:-1]==a[:end]
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items())
    summary={}
    for q in (3,4):
        variants='AB' if q==3 else 'ABC';g={v:[x for x in rows if x['problem']==q and x['variant']==v] for v in variants}
        stats={v:dict(n=len(g[v]),mean=float(np.mean([x['mean_time_per_source_s'] for x in g[v]])),
            p95=float(np.quantile([x['mean_time_per_source_s'] for x in g[v]],.95)),fallbacks=sum(x['optical_fallbacks'] for x in g[v])) for v in variants}
        pairs={}
        for ref,v in ([('A','B')] if q==3 else [('A','B'),('B','C'),('A','C')]):
            d=np.array([y['mean_time_per_source_s']-x['mean_time_per_source_s'] for x,y in zip(g[ref],g[v])])
            pairs[v+'-'+ref]=dict(mean_delta=float(d.mean()),wins=int(sum(d < -1e-8)),ties=int(sum(abs(d)<=1e-8)),losses=int(sum(d>1e-8)),max_regression=float(max(d)))
        summary[q]=dict(variants=stats,pairs=pairs)
    (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary),flush=True)

if __name__=='__main__':main()
