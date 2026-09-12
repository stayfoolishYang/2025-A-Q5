"""Portable offline entry point for the frozen 21+R12+F+CT policy."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
ENGINE=ROOT.parents[1]/'runtime/q4'
sys.path.insert(0,str(ROOT/'source'));sys.path.insert(0,str(ENGINE))
import numpy as np
import geometry,solver,phase_audit
import public_max37_benchmark as base
import recovered_benchmark as rb
from ctspn import CTSolver

def fingerprints(sim):
    files=list((ROOT/'source').rglob('*.py'))
    files += [ROOT/'config_21r12ctf.json',ROOT/'points21.json',Path(__file__)]
    result={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    result.update({'runtime/'+p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in ENGINE.glob('*.py')})
    return result


def run_scene(scene_path,output):
    output=Path(output).resolve()
    if output.exists():raise FileExistsError('Use a new output directory; existing results are preserved')
    for name,h in json.loads((ROOT/'SOURCE_SHA256.json').read_bytes()).items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=h:raise RuntimeError('Frozen file changed: '+name)
    raw=json.loads(Path(scene_path).read_bytes());cfg=json.loads((ROOT/'config_21r12ctf.json').read_bytes())
    rb.save(output/'scenes/0000.json',raw)
    rec=dict(id=0,total=len(raw['jammers']),cohort='portable_release',family='user_scene',file='scenes/0000.json',scene_hash=rb.digest(raw))
    rb.save(output/'manifest.json',dict(records=[rec],configs=[cfg],source_hashes=fingerprints(ENGINE),execution_backend='LOCAL_DEV',execution_purpose='FRAMEWORK_INTEGRATION',production_eligible=False))
    points=np.asarray(json.loads((ROOT/'points21.json').read_bytes())['points'])
    assert points.shape==(21,2) and cfg['failure_context_repair'] and cfg['ctspn_enabled']
    previous_g,previous_s,previous_cls=geometry.coverage,solver.coverage,phase_audit.TaggedSolver
    def coverage(mixed=False,ring=1130.,*,version='legacy45'):
        return points.copy() if mixed and version=='certified25' else previous_g(mixed,ring,version=version)
    class Captured(CTSolver):
        def run(self):
            try:return super().run()
            finally:rb.save(output/'ct_events.json',dict(events=self.ct_events,pending_bridge=self.api.pending is not None))
    geometry.coverage=solver.coverage=coverage;phase_audit.TaggedSolver=Captured;base.fingerprints=fingerprints
    try:row=base.run_case((output,ENGINE,0,'B',None))
    finally:geometry.coverage=previous_g;solver.coverage=previous_s;phase_audit.TaggedSolver=previous_cls
    if row['run_status']!='FULL_CLEAR' or not row['audit_passed']:raise RuntimeError('Run or audit failed; inspect saved output')
    return row

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scene',type=Path,default=ROOT/'example_scene.json')
    p.add_argument('--output',type=Path,default=ROOT/'run_output')
    a=p.parse_args();r=run_scene(a.scene,a.output)
    print(json.dumps({k:r[k] for k in ['total','cleared','virtual_time_s','mean_time_per_source','failed_clears','audit_passed']},ensure_ascii=False))

if __name__=='__main__':main()
