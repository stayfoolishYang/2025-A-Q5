"""Fresh, paired, direct-engine Phase B runs; no official transport."""
import json,hashlib,gzip,argparse,os
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
from collect import ROOT,SIM,SRC,bench,rb,phase_audit,StudySolver,generate_document
from routing_solver import RoutingSolver
OUT=ROOT/'results/routing_development'
ARMS=['R12','MYOPIC','TERMINAL']
def hashes():
    files=['run_routing.py','routing_solver.py','terminal_route.py','belief_fast.py','collect.py']
    return {n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in files}
def freeze():
    assert json.loads((ROOT/'analysis/PREDICTION_GATE.json').read_bytes())['phase_A_pass']
    assert not(OUT/'manifest.json').exists()
    used=set()
    for base in (Path('J:/2026B_runs'),Path('J:/2026B_experiments')):
        for folder,dirs,files in os.walk(base):
            dirs[:]=[d for d in dirs if d not in ('.git','traces','rows','node_modules','__pycache__')]
            if 'scene' not in Path(folder).name.lower():continue
            for n in files:
                if n.endswith('.json'):
                    raw=json.loads((Path(folder)/n).read_bytes())
                    if 'jammers' in raw:used.add(bench.physical_hash(raw))
    records=[]
    for i in range(128):
        seed=hashlib.sha256(f'2026B-R14-ROUTING-v1-{i}'.encode()).hexdigest()
        raw=generate_document(seed_hex=seed,problem=4,format='native');h=bench.physical_hash(raw)
        assert h not in used;used.add(h);file=f'scenes/{i:04d}.json';rb.save(OUT/file,raw)
        records.append(dict(id=i,file=file,cohort='development',family='native_unconditioned',
            seed_hex=seed,physical_hash=h,scene_hash=rb.digest(raw),total=len(raw['jammers'])))
    cfg=json.loads((SRC/'configs/q4_known16_tri25_R12.yaml').read_bytes())
    rb.save(OUT/'manifest.json',dict(records=records,configs=[dict(cfg,name=a,study_modules=[],belief_routing=a) for a in ARMS],
        source_hashes=bench.fingerprints(SIM),research_hashes=hashes(),official_calls=0,formal_test_count=0))
    print('FROZEN 128 x 3',flush=True)
def worker(job):
    index,arm=job;m=json.loads((OUT/'manifest.json').read_bytes());assert hashes()==m['research_hashes']
    StudySolver.instances.clear();RoutingSolver.instances.clear();old=phase_audit.TaggedSolver;phase_audit.TaggedSolver=RoutingSolver
    try:row=bench.run_case((str(OUT),str(SIM),index,arm,False))
    finally:phase_audit.TaggedSolver=old
    solver=RoutingSolver.instances[-1]
    path=OUT/'routing_events'/f'{arm}_{index:04d}.json.gz';path.parent.mkdir(exist_ok=True)
    with gzip.open(path,'wt',encoding='utf-8') as f:json.dump(solver.routing_events,f)
    return index,arm,row['run_status'],row['audit_passed'],row['mean_time_per_source']
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['freeze','run']);a=p.parse_args()
    if a.action=='freeze':freeze()
    else:
        jobs=[(i,a) for i in range(128) for a in ARMS if not(OUT/'routing_events'/f'{a}_{i:04d}.json.gz').exists()]
        with ProcessPoolExecutor(max_workers=8) as pool:
            for i,f in enumerate(as_completed([pool.submit(worker,j) for j in jobs]),1):
                r=f.result()
                if r[2]!='FULL_CLEAR' or not r[3]:raise RuntimeError(r)
                if i%8==0:print(i,len(jobs),r,flush=True)
        print('COMPLETE',flush=True)
