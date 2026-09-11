"""Phase A: fresh frozen R12 runs; passive observation-state collection only."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1')
import sys,json,hashlib,gzip,time,argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
ROOT=Path(__file__).resolve().parent
R13=ROOT.parent/'r13'; SRC=R13/'baseline/q4better'; SIM=Path('G:/QQ/jammers_linux')
for p in (SIM,SRC,R13):sys.path.insert(0,str(p))
import known16_tri25_benchmark as bench
import recovered_benchmark as rb
import phase_audit
from study_solver import StudySolver
from scenario_io import generate_document

class Collector(StudySolver):
    instances=[]
    def __init__(self,*a,**kw):
        super().__init__(*a,**kw);self.snapshots=[];Collector.instances.append(self)
    def decision(self,nodes):
        action=super().decision(nodes)
        if action[0]=='explore' and nodes:
            self.snapshots.append(dict(time_s=self.api.virtual_time,position=self.api.position.tolist(),
                nodes=[p.tolist() for p in nodes],channel=self.api.channel,confirmed=sorted(self.confirmed),
                cleared=sorted(self.cleared),history={str(c):[(p.tolist(),r,a) for p,r,a in h] for c,h in self.history.items()}))
        return action

def hashes():
    paths=[ROOT/'collect.py',ROOT/'belief.py',R13/'study_solver.py',R13/'endpoint_cost.py']
    return {str(p.relative_to(ROOT.parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}

def freeze():
    out=ROOT/'results/prediction';assert not(out/'manifest.json').exists()
    # Audit all accessible unpacked scene files; old R13 included explicitly.
    used=set();files=0
    for base in (Path('J:/2026B_runs'),Path('J:/2026B_experiments')):
        for folder,dirs,names in os.walk(base):
            dirs[:]=[d for d in dirs if d not in ('.git','traces','rows','node_modules','__pycache__')]
            if 'scene' not in Path(folder).name.lower():continue
            for name in names:
                if not name.endswith('.json'):continue
                p=Path(folder)/name
                data=json.loads(p.read_bytes())
                if 'jammers' in data:used.add(bench.physical_hash(data));files+=1
    cfg=json.loads((SRC/'configs/q4_known16_tri25_R12.yaml').read_bytes())
    records=[]
    for cohort,count in [('development',128),('holdout',256)]:
        for k in range(count):
            seed=hashlib.sha256(f'2026B-R14-PREDICTION-v1-{cohort}-{k}'.encode()).hexdigest()
            raw=generate_document(seed_hex=seed,problem=4,format='native');h=bench.physical_hash(raw)
            assert h not in used,'Scene collision: do not silently replace'
            used.add(h);idx=len(records);file=f'scenes/{idx:04d}.json';rb.save(out/file,raw)
            records.append(dict(id=idx,cohort=cohort,family="native_unconditioned",file=file,seed_hex=seed,physical_hash=h,
                scene_hash=rb.digest(raw),total=len(raw['jammers'])))
    rb.save(out/'manifest.json',dict(records=records,configs=[dict(cfg,name='R12',study_modules=[])],
        source_hashes=bench.fingerprints(SIM),research_hashes=hashes(),official_calls=0,
        formal_test_count=0,exclusion_scene_files=files,exclusion_scope='accessible unpacked J drive scenes'))
    print('FROZEN',len(records),'excluded scene files',files,flush=True)

def worker(job):
    index=job;out=ROOT/'results/prediction';m=json.loads((out/'manifest.json').read_bytes())
    assert hashes()==m['research_hashes']
    Collector.instances.clear();StudySolver.instances.clear();previous=phase_audit.TaggedSolver;phase_audit.TaggedSolver=Collector
    try:row=bench.run_case((str(out),str(SIM),index,'R12',False))
    finally:phase_audit.TaggedSolver=previous
    s=Collector.instances[-1]
    path=out/'snapshots'/f'{index:04d}.json.gz';path.parent.mkdir(exist_ok=True)
    with gzip.open(path,'wt',encoding='utf-8') as f:json.dump(s.snapshots,f)
    return index,row['run_status'],row['audit_passed'],len(s.snapshots)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['freeze','run']);p.add_argument('--workers',type=int,default=8);a=p.parse_args()
    if a.action=='freeze':freeze()
    else:
        out=ROOT/'results/prediction';m=json.loads((out/'manifest.json').read_bytes())
        jobs=[r['id'] for r in m['records'] if not(out/'snapshots'/f'{r["id"]:04d}.json.gz').exists()]
        with ProcessPoolExecutor(max_workers=a.workers) as pool:
            for i,f in enumerate(as_completed([pool.submit(worker,j) for j in jobs]),1):
                result=f.result()
                if result[1]!='FULL_CLEAR' or not result[2]:raise RuntimeError(result)
                if i%8==0:print(i,len(jobs),result,flush=True)
        print('COMPLETE',flush=True)
