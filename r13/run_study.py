"""Direct offline Engine batches, immutable per-case rows, no HTTP entry point."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1')
from pathlib import Path
import sys,json,gzip,hashlib,time,argparse,zipfile,re
from concurrent.futures import ProcessPoolExecutor,as_completed
ROOT=Path(__file__).resolve().parent;SRC=ROOT/'baseline/q4better';SIM=Path('G:/QQ/jammers_linux')
sys.path.insert(0,str(SIM));sys.path.insert(0,str(SRC))
import numpy as np
import known16_tri25_benchmark as bench
import recovered_benchmark as rb
import phase_audit
from study_solver import StudySolver
from scenario_io import generate_document,load_scenario
ARMS=['R12','A1','B-lite','C1','C2','D','E-H2']

def save(path,x):rb.save(Path(path),x)
def hashes():return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/n for n in ('run_study.py','study_solver.py','strong_route.py','route_reference.py','endpoint_cost.py','scan_credit.py','soft_release.py','short_rollout.py'))}

def history():
    physical=set();seeds=set();scanned=[];errors=[]
    roots=[Path('J:/2026B_runs'),Path('J:/2026B_experiments'),Path('I:/GithubRick/2025-A-Q5/B_solver/results'),Path('I:/GithubRick/2025-A-Q5/comparisons')]
    for root in roots:
        for folder,dirs,files in os.walk(root):
            dirs[:]=[d for d in dirs if d not in ('.git','node_modules','__pycache__','venv','.venv','site-packages','traces','rows')]
            for name in files:
                p=Path(folder)/name
                if ROOT/'results' in p.parents:continue
                scene=name.endswith('.json') and ('scene' in p.parent.name.lower() or name.startswith('q4_'))
                manifest=name.endswith('.json') and any(t in name.lower() for t in ('manifest','plan','seed'))
                if not(scene or manifest):continue
                try:
                    if p.stat().st_size>20_000_000:continue
                    raw=p.read_bytes();data=json.loads(raw);scanned.append(str(p))
                    if manifest:seeds.update(re.findall(r'(?<![a-fA-F0-9])[a-fA-F0-9]{64}(?![a-fA-F0-9])',raw.decode('utf-8-sig')))
                    if isinstance(data,dict) and 'jammers' in data:physical.add(bench.physical_hash(data))
                except Exception as e:errors.append(dict(file=str(p),error=str(e)[:120]))
    save(ROOT/'HISTORICAL_EXCLUSION_AUDIT.json',dict(files=scanned,errors=errors,physical_count=len(physical),seed_or_digest_count=len(seeds),
        limitation='Accessible unpacked local scenarios/manifests only. Official unexported truths and nested scene archives not exhaustively accessible; no claim of complete official disjointness.'))
    return physical,seeds

def freeze(out,cohort,count,arms):
    assert not (out/'manifest.json').exists()
    used,seeds=history();cfg=json.loads((SRC/'configs/q4_known16_tri25_R12.yaml').read_bytes());records=[];k=0
    for slot in range(count):
        while True:
            seed=hashlib.sha256(f'2026B-R13-20260912-{cohort}-v1:{k}'.encode()).hexdigest();k+=1
            if seed in seeds:continue
            raw=generate_document(seed_hex=seed,problem=4,format='native')
            if len(raw['jammers'])!=10+slot%7 or {j.kind for j in load_scenario(raw).jammers}!={'omni','directional'}:continue
            h=bench.physical_hash(raw)
            if h not in used:break
        used.add(h);file=f'scenes/{slot:04d}.json';save(out/file,raw)
        records.append(dict(id=slot,cohort=cohort,family='native_strict_mixed_N_stratified',file=file,seed_hex=seed,scene_hash=rb.digest(raw),physical_hash=h,total=len(raw['jammers'])))
    configs=[dict(cfg,name=a,study_modules=[] if a=='R12' else a.split('+')) for a in arms]
    save(out/'manifest.json',dict(records=records,configs=configs,source_hashes=bench.fingerprints(SIM),research_hashes=hashes(),
        official_calls=0,formal_test_count=0,execution_backend='direct_local_engine',cohort=cohort,workers=8))
    print('Frozen',cohort,count,arms,flush=True)

def worker(job):
    out,index,arm=job;out=Path(out);m=json.loads((out/'manifest.json').read_bytes())
    assert hashes()==m['research_hashes'],'Research code changed after freeze'
    StudySolver.instances.clear();old=phase_audit.TaggedSolver;phase_audit.TaggedSolver=StudySolver
    try:row=bench.run_case((str(out),str(SIM),index,arm,False))
    finally:phase_audit.TaggedSolver=old
    s=StudySolver.instances[-1];row.update(known16_enabled=True,research_hash=rb.digest(m['research_hashes']),official_calls=0,formal_test_count=0)
    rt=[e['route_ms'] for e in s.route_events];dc=[e['decision_ms'] for e in s.events if e['kind']=='decision']
    row.update(route_compute_ms_p95=float(np.percentile(rt,95)) if rt else 0.,decision_compute_ms_p95=float(np.percentile(dc,95)) if dc else 0.,
        support_visits=sum(e.get('action',[''])[0]=='support' for e in s.events),route_refresh_count=len(s.route_events))
    p=out/'core/traces'/f'{arm}_{index:04d}.json.gz'
    with gzip.open(p,'rt',encoding='utf-8') as f:trace=json.load(f)
    trace.update(row=row,study_events=s.events,route_events=s.route_events)
    with gzip.open(p,'wt',encoding='utf-8') as f:json.dump(trace,f,ensure_ascii=False)
    save(out/'core/rows'/f'{arm}_{index:04d}.json',row)
    return row

def run(out,workers):
    m=json.loads((out/'manifest.json').read_bytes());jobs=[(str(out),r['id'],c['name']) for r in m['records'] for c in m['configs'] if not(out/'core/rows'/f'{c["name"]}_{r["id"]:04d}.json').exists()]
    start=time.perf_counter();done=0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        fs=[pool.submit(worker,j) for j in jobs]
        for f in as_completed(fs):
            r=f.result();done+=1
            if r['run_status']!='FULL_CLEAR' or not r['audit_passed']:print('FAILED',r['id'],r['variant'],r['error'],flush=True)
            if done%8==0:print(done,'/',len(jobs),'elapsed',round(time.perf_counter()-start,1),flush=True)
    print('BATCH_COMPLETE',len(jobs),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['freeze','run']);p.add_argument('cohort');p.add_argument('--count',type=int,default=128);p.add_argument('--arms',default=','.join(ARMS));p.add_argument('--workers',type=int,default=8);a=p.parse_args();out=ROOT/'results'/a.cohort
    if a.action=='freeze':freeze(out,a.cohort,a.count,a.arms.split(','))
    else:run(out,a.workers)

