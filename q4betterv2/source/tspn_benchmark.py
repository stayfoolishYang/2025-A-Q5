"""Isolated, paired R12 clear-neighborhood experiment; online policy gets no truth."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip, hashlib, json, os, sys, zipfile
from pathlib import Path
import numpy as np
import public_max37_benchmark as base
import recovered_benchmark as rb
import phase_audit

SRC=Path(__file__).resolve().parent
ROOT=SRC.parents[1]
OUT=ROOT/'results/tspn_20260912_v1'
OLD=ROOT/'results/p2_rx_20260912_005510'
SIM=Path(r'D:\桌面\2026国赛\b模拟器\Jammers-Offline-Windows')
def read(p):
    return json.loads(gzip.decompress(Path(p).read_bytes()) if str(p).endswith('.gz') else Path(p).read_bytes())
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def fingerprints(sim):
    return {'solver/'+p.relative_to(SRC).as_posix():sha(p) for p in SRC.rglob('*.py')} | {'engine/'+n:sha(sim/n) for n in ('engine.py','scenario_io.py','recovered_generator.py','protocol.py')}
base.fingerprints=fingerprints

class Observed(phase_audit.TaggedSolver):
    """Read-only instrumentation; inherited run/localize/clear ordering is untouched."""
    def release_discovery(self,nodes):
        super().release_discovery(nodes)
        self.mandatory_nodes=nodes
    def check_set(self,c):
        if c in self.tracks:
            self.target_trace(c).setdefault('conservative_sets',[]).append(dict(time=self.api.virtual_time,polygon=self.tracks[c]['poly'].tolist()))
    def measure(self,c,p):
        result=super().measure(c,p); self.check_set(c); return result
    def clear(self,c,p,certified=False):
        self.check_set(c)
        return super().clear(c,p,certified)
    def anchor(self):
        nodes=getattr(self,'mandatory_nodes',[])
        return np.asarray(nodes[0]).copy() if nodes and self.known16_trigger is None else None
    def clear_certified_polygon(self,c,center,radius):
        log=self.target_trace(c); before=len(log.get('certified_clearance_events',[]))
        anchor=self.anchor(); receiver=self.api.channel
        result=super().clear_certified_polygon(c,center,radius)
        if len(log.get('certified_clearance_events',[]))>before:
            log['certified_clearance_events'][-1].update(next_mandatory_anchor=None if anchor is None else anchor.tolist(),receiver_before=receiver,receiver_after=self.api.channel,model='R12',optimization_wall_s=0.,optimization_cpu_s=0.)
        return result

def run_case(job):
    out,sim,i,v,_=job
    original=phase_audit.TaggedSolver
    if v=='A': phase_audit.TaggedSolver=Observed
    else:
        from tspn_policy import NeighborhoodSolver
        phase_audit.TaggedSolver=NeighborhoodSolver
    try: return base.run_case(job)
    finally: phase_audit.TaggedSolver=original

def freeze_development():
    out=OUT/'development'; assert not (out/'manifest.json').exists()
    old=read(OLD/'manifest.json');cfg=read(SRC/'configs/q4_known16_tri25_R12.yaml')
    records=old['records'];assert len(records)==40
    for r in records:
        raw=read(OLD/r['file']);assert rb.digest(raw)==r['scene_hash'];rb.save(out/r['file'],raw)
    configs=[dict(cfg,name=v,tspn_mode=mode) for v,mode in [('A','OFF'),('B','MEC'),('C','EXACT')]]
    rb.save(out/'manifest.json',dict(records=records,configs=configs,source_hashes=fingerprints(SIM),simulator_root=str(SIM),execution_backend='LOCAL_DEV',execution_purpose='FRAMEWORK_INTEGRATION',production_eligible=False,scope='USED DEVELOPMENT CASES'))
    for c in configs:rb.save(OUT/'configs'/f'{c["name"]}.json',c)

def canonical():
    out=OUT/'development';m=read(out/'manifest.json');checks=[]
    for r in m['records']:
        a=read(OLD/f'core/traces/H0_{r["id"]:04d}.json.gz');b=read(out/f'core/traces/A_{r["id"]:04d}.json.gz')
        x,y=base.canonical_actions(a),base.canonical_actions(b)
        checks.append(dict(id=r['id'],passed=x==y and b['row']['audit_passed'],old_hash=rb.digest(x),new_hash=rb.digest(y)))
    rb.save(OUT/'R12_CANONICAL_REPLAY.json',dict(passed=all(c['passed'] for c in checks),cases=checks))
    assert all(c['passed'] for c in checks)
    print('Canonical R12 physical actions/feedback/RNG:40/40 PASS',flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');p.add_argument('--variant',choices=['A','B','C']);p.add_argument('--cohort',default='development');a=p.parse_args()
    sys.path.insert(0,str(SIM));os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
    if a.freeze:freeze_development();return
    out=OUT/a.cohort;m=read(out/'manifest.json')
    assert fingerprints(SIM)==m['source_hashes'],'SOURCE_CHANGED'
    if a.variant!='A':assert read(OUT/'OPPORTUNITY.json')['passed'] and read(OUT/'R12_CANONICAL_REPLAY.json')['passed']
    jobs=[(out,SIM,r['id'],a.variant,None) for r in m['records']]
    assert not any((out/f'core/rows/{a.variant}_{r["id"]:04d}.json').exists() for r in m['records'])
    with ProcessPoolExecutor(max_workers=4) as pool:
        for n,f in enumerate(as_completed([pool.submit(run_case,j) for j in jobs]),1):
            r=f.result();print(n,len(jobs),a.variant,r['id'],r['run_status'],r['audit_passed'],r['error'],flush=True)
    if a.variant=='A' and a.cohort=='development':canonical()
if __name__=='__main__': main()
