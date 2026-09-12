"""1000 newly generated paired scenes: A25 R12 CT versus B21 R12 F CT."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import argparse,csv,gzip,hashlib,json,sys,time,zipfile
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
OUT=ROOT/'results/sub21_f_ct1000_20260912_v1'
REFERENCE=ROOT/'results/sub21_f_ct128_20260912_v1'
PRIOR=ROOT/'results/sub21_r12_pilot_20260912_v1'
OLD=ROOT/'results/ctspn_20260912_v1/evaluation256'
GEOM=ROOT/'results/sub25_fast_20260912_v1'
SIM=Path('<LOCAL_PATH>')
sys.path.insert(0,str(ROOT))
import public_max37_benchmark as base
import recovered_benchmark as rb
import geometry,solver,phase_audit
from ctspn import CTSolver

def read(p):return json.loads(Path(p).read_bytes())
def paths():
    ps=list(ROOT.glob('*.py'))+list((ROOT/'directional').glob('*.py'))+list((ROOT/'reporting').glob('*.py'))
    ps += [ROOT/'configs/q4_known16_tri25_R12.yaml',Path(__file__),HERE/'candidate21.json',HERE/'report_results.py',HERE/'ctspn.py',HERE/'tspn_geometry.py']
    return {'solver/'+p.relative_to(ROOT).as_posix():p for p in ps}|{'engine/'+n:SIM/n for n in ('engine.py','scenario_io.py','recovered_generator.py','protocol.py')}
def fingerprints(sim):return {name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in paths().items()}
base.fingerprints=fingerprints

def freeze():
    assert not (OUT/'manifest.json').exists(),'New output required'
    import shutil
    assert len(read(HERE/'candidate21.json')['points'])==21
    shutil.copyfile(PRIOR/'EXTERNAL_COVERAGE_REPORT.md',OUT/'EXTERNAL_COVERAGE_REPORT.md')
    old=read(REFERENCE/'manifest.json');original=read(ROOT/'configs/q4_known16_tri25_R12.yaml')
    current_hashes=fingerprints(SIM)
    for name,h in old['source_hashes'].items():
        if name in current_hashes:assert current_hashes[name]==h
    configs=[dict(original,name=v,ctspn_enabled=True,failure_context_repair=v=='B') for v in 'AB']
    for v,pv in [('A','D'),('B','F')]:
        prior=next(c for c in old['configs'] if c['name']==pv)
        assert {k:x for k,x in prior.items() if k!='name'}=={k:x for k,x in next(c for c in configs if c['name']==v).items() if k!='name'}
    sys.path.insert(0,str(SIM))
    from scenario_io import generate_document,load_scenario
    old_seeds=set();old_hashes=set();history_files=[]
    for p in (ROOT/'results').rglob('manifest.json'):
        history=read(p);history_files.append(str(p.relative_to(ROOT)))
        for rec in history.get('records',[]):
            if rec.get('seed_hex'):old_seeds.add(rec['seed_hex'])
            if rec.get('scene_hash'):old_hashes.add(rec['scene_hash'])
    records=[]
    for i in range(1000):
        seed=hashlib.sha256(f'2026B-21FCT-vs25CT-fresh1000-20260912-v1:{i}'.encode()).hexdigest()
        raw=generate_document(seed_hex=seed,problem=4,format='native');load_scenario(raw)
        h=rb.digest(raw);assert seed not in old_seeds and h not in old_hashes
        file=f'scenes/{i:04d}.json';rb.save(OUT/file,raw)
        records.append(dict(id=i,seed_hex=seed,scene_hash=h,file=file,total=len(raw['jammers']),cohort='fresh1000',family='practice-gen-v1'))
    assert len({r['scene_hash'] for r in records})==1000
    manifest=dict(records=records,configs=configs,source_hashes=current_hashes,
       variants=dict(A='25 R12 CT',B='21 R12 F CT'),
       scope='1000 fresh paired generated scenes; exactly two frozen policies; no outcome selection or tuning',
       seed_prefix='2026B-21FCT-vs25CT-fresh1000-20260912-v1:',
       historical_overlap=0,history_files=history_files,known_historical_seeds=len(old_seeds),known_historical_scenes=len(old_hashes),history_limitation='Only saved result manifests checked; unavailable unarchived history excluded',
       execution_backend='LOCAL_DEV',execution_purpose='FRAMEWORK_INTEGRATION',production_eligible=False,
       coverage_status='USER_PROVIDED_CONTINUOUS_CERTIFICATE_REPORT',coverage_reaudited=False,
       planned_metrics=['mean T/N','P50/P95/P99 T/N','slowest 5 percent mean','paired wins/ties/losses','worst paired regression','per-N strata','full clear','failed clear attempts'],
       node_patch='A original25; B unchanged user21; byte-identical retained CT; worker memory coverage patch')
    rb.save(OUT/'manifest.json',manifest)
    with zipfile.ZipFile(OUT/'frozen_source.zip','x',compression=zipfile.ZIP_DEFLATED) as z:
        for n,p in paths().items():z.write(p,n)
        z.write(OUT/'manifest.json','manifest.json')

def run_case(job):
    previous_g,previous_s=geometry.coverage,solver.coverage
    if job[3]=='B':
        points=np.asarray(read(HERE/'candidate21.json')['points'])
        def selected(mixed=False,ring=1130.,*,version='legacy45'):
            return points.copy() if mixed and version=='certified25' else previous_g(mixed,ring,version=version)
        geometry.coverage=solver.coverage=selected
    class Captured(CTSolver):
        def run(self):
            try:return super().run()
            finally:rb.save(Path(job[0])/f'ct_events/{job[3]}_{job[2]:04d}.json',dict(events=self.ct_events,pending_bridge=self.api.pending is not None))
    prior=phase_audit.TaggedSolver;phase_audit.TaggedSolver=Captured
    try:return base.run_case(job)
    finally:
        geometry.coverage=previous_g;solver.coverage=previous_s;phase_audit.TaggedSolver=prior

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--freeze',action='store_true');ap.add_argument('--report',action='store_true');ap.add_argument('--ids',type=int,nargs='+');a=ap.parse_args()
    if a.freeze:freeze();return
    if a.report:
        from report_results import report
        report();return
    ids=a.ids if a.ids is not None else list(range(1000));jobs=[(OUT,SIM,i,v,None) for i in ids for v in 'AB' if not(OUT/f'core/rows/{v}_{i:04}.json').exists()]
    with ProcessPoolExecutor(max_workers=8) as pool:
        for n,f in enumerate(as_completed([pool.submit(run_case,j) for j in jobs]),1):
            r=f.result();print(n,len(jobs),r['variant'],r['id'],r['run_status'],r['audit_passed'],r['error'],flush=True)

if __name__=='__main__':main()

