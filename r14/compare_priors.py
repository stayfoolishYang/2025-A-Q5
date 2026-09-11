"""Fresh prediction-only comparison of2000m and1800m priors."""
import json,gzip,hashlib,os,argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
import collect,evaluate
from collect import ROOT,SRC,SIM,bench,rb,phase_audit,Collector,StudySolver,generate_document
from belief_fast import DiscoveryBelief as Prior2000
from belief1800 import DiscoveryBelief as Prior1800
OUT=ROOT/'results/prior_comparison128'
def freeze():
    assert not(OUT/'manifest.json').exists();used=set()
    for base in (Path('J:/2026B_runs'),Path('J:/2026B_experiments')):
        for folder,dirs,files in os.walk(base):
            dirs[:]=[d for d in dirs if d not in ('.git','traces','rows','node_modules','__pycache__')]
            if 'scene' not in Path(folder).name.lower():continue
            for name in files:
                if name.endswith('.json'):
                    raw=json.loads((Path(folder)/name).read_bytes())
                    if 'jammers' in raw:used.add(bench.physical_hash(raw))
    records=[]
    for i in range(128):
        seed=hashlib.sha256(f'2026B-R14-PRIOR-CORRECTION-128-v1-{i}'.encode()).hexdigest()
        raw=generate_document(seed_hex=seed,problem=4,format='native');h=bench.physical_hash(raw)
        assert h not in used;used.add(h);file=f'scenes/{i:04d}.json';rb.save(OUT/file,raw)
        records.append(dict(id=i,file=file,cohort='prior_validation',family='native_unconditioned',scene_hash=rb.digest(raw),physical_hash=h,total=len(raw['jammers'])))
    cfg=json.loads((SRC/'configs/q4_known16_tri25_R12.yaml').read_bytes())
    rb.save(OUT/'manifest.json',dict(records=records,configs=[dict(cfg,name='R12',study_modules=[])],
        source_hashes=bench.fingerprints(SIM),code_hashes={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ['collect.py','evaluate.py','belief_fast.py','belief1800.py','compare_priors.py']},official_calls=0))
    print('FROZEN fresh128 prior comparison',flush=True)
def worker(i):
    m=json.loads((OUT/'manifest.json').read_bytes())
    for n,h in m['code_hashes'].items():assert hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==h
    snap=OUT/'snapshots'/f'{i:04d}.json.gz'
    if not snap.exists():
        Collector.instances.clear();StudySolver.instances.clear();old=phase_audit.TaggedSolver;phase_audit.TaggedSolver=Collector
        try:row=bench.run_case((str(OUT),str(SIM),i,'R12',False))
        finally:phase_audit.TaggedSolver=old
        assert row['run_status']=='FULL_CLEAR' and row['audit_passed']
        snap.parent.mkdir(exist_ok=True)
        with gzip.open(snap,'wt') as f:json.dump(Collector.instances[-1].snapshots,f)
    evaluate.OUT=OUT
    for name,cls in [('2000',Prior2000),('1800',Prior1800)]:
        target=OUT/f'evaluation{name}'/f'{i:04d}.json'
        if not target.exists():
            evaluate.DiscoveryBelief=cls;evaluate.worker(i);target.parent.mkdir(exist_ok=True)
            (OUT/'evaluation'/f'{i:04d}.json').replace(target)
    return i
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['freeze','run']);a=p.parse_args()
    if a.action=='freeze':freeze()
    else:
        with ProcessPoolExecutor(max_workers=8) as pool:
            for n,f in enumerate(as_completed([pool.submit(worker,i) for i in range(128)]),1):
                f.result()
                if n%16==0:print('COMPARED',n,128,flush=True)
