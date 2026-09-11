import argparse,gzip,json,sys,time,os,hashlib,zipfile
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
import public_max37_benchmark as base
import recovered_benchmark as rb
import phase_audit
from ctspn import CTSolver
SRC=Path(__file__).resolve().parent;ROOT=SRC.parents[1];OUT=ROOT/'results/ctspn_20260912_v1';OLD=ROOT/'results/tspn_20260912_v1/Q4_TSPN_clear_neighborhood_review.zip';SIM=Path(r'D:\桌面\2026国赛\b模拟器\Jammers-Offline-Windows')
def read(p):return json.loads(gzip.decompress(Path(p).read_bytes()) if str(p).endswith('.gz') else Path(p).read_bytes())
def fingerprints(sim):return {'solver/'+p.relative_to(SRC).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in SRC.rglob('*.py')}|{'engine/'+n:hashlib.sha256((sim/n).read_bytes()).hexdigest() for n in ('engine.py','scenario_io.py','recovered_generator.py','protocol.py')}
base.fingerprints=fingerprints
def freeze(cohort):
    assert cohort=='development';out=OUT/cohort;assert not (out/'manifest.json').exists()
    with zipfile.ZipFile(OLD) as z:
        m=json.loads(z.read('evaluation/manifest.json'));records=m['records']
        for r in records:rb.save(out/r['file'],json.loads(z.read('evaluation/'+r['file'])))
    cfg=read(SRC/'configs/q4_known16_tri25_R12.yaml')
    configs=[dict(cfg,name=v,ctspn_enabled=v=='CT') for v in ('A','CT')]
    rb.save(out/'manifest.json',dict(records=records,configs=configs,source_hashes=fingerprints(SIM),simulator_root=str(SIM),execution_backend='LOCAL_DEV',execution_purpose='FRAMEWORK_INTEGRATION',production_eligible=False,scope='USED DEVELOPMENT DATA: previous evaluation128'))
    for c in configs:rb.save(OUT/'configs'/f'{c["name"]}.json',c)
def run_case(job):
    out,sim,i,v,_=job
    class Captured(CTSolver):
        def run(self):
            try:return super().run()
            finally:
                rb.save(Path(out)/f'ct_events/{v}_{i:04d}.json',dict(events=self.ct_events,pending_bridge=self.api.pending is not None))
    prior=phase_audit.TaggedSolver;phase_audit.TaggedSolver=Captured
    try:return base.run_case(job)
    finally:phase_audit.TaggedSolver=prior
def main():
    p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');p.add_argument('--variant',choices=['A','CT']);p.add_argument('--cohort',default='development');p.add_argument('--ids',nargs='+',type=int);p.add_argument('--resume',action='store_true');a=p.parse_args()
    sys.path.insert(0,str(SIM));os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
    if a.freeze:freeze(a.cohort);return
    out=OUT/a.cohort;m=read(out/'manifest.json');assert fingerprints(SIM)==m['source_hashes']
    jobs=[(out,SIM,r['id'],a.variant,None) for r in m['records'] if (a.ids is None or r['id'] in a.ids) and not(a.resume and (out/f'core/rows/{a.variant}_{r["id"]:04d}.json').exists())]
    with ProcessPoolExecutor(max_workers=4) as pool:
        for n,f in enumerate(as_completed([pool.submit(run_case,j) for j in jobs]),1):
            r=f.result();print(n,len(jobs),a.variant,r['id'],r['run_status'],r['audit_passed'],r['error'],flush=True)
if __name__=='__main__':main()
