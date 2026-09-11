"""Oracle incumbent must reproduce the saved R12 suffix, including RNG digests."""
import json,gzip
from collect import ROOT,SIM,bench,phase_audit,StudySolver,rb
from oracle_replay import run_branch
SOURCE=ROOT/'results/prior_comparison128';OUT=ROOT/'results/oracle_invariance'
m=json.loads((SOURCE/'manifest.json').read_bytes())
for r in m['records']:r['file']=str(SOURCE/r['file'])
if not(OUT/'manifest.json').exists():rb.save(OUT/'manifest.json',m)
checks=[]
class Capture(StudySolver):
    def decision(self,nodes):
        action=super().decision(nodes)
        if action[0]=='explore':
            self.counter=getattr(self,'counter',0)+1
            if self.counter in (1,4,7):
                offset=len(self.api.log);branch=run_branch(self,nodes,0)
                checks.append(dict(offset=offset,branch=branch))
        return action
for index in (0,7):
    checks.clear();old=phase_audit.TaggedSolver;phase_audit.TaggedSolver=Capture
    try:r=bench.run_case((str(OUT),str(SIM),index,'R12',False))
    finally:phase_audit.TaggedSolver=old
    with gzip.open(OUT/'core/traces'/f'R12_{index:04d}.json.gz','rt') as f:trace=json.load(f)
    for c in checks:
        expected={'actions':trace['actions'][c['offset']:]}
        assert bench.canonical_actions(expected)==bench.canonical_actions(c['branch'])
        assert abs(c['branch']['cost']-(r['virtual_time_s']-expected['actions'][0]['response']['virtual_time_s']+expected['actions'][0]['total_s']))<1e-6
    print('EXACT_SUFFIX',index,len(checks),flush=True)
rb.save(ROOT/'ORACLE_INVARIANCE.json',dict(cases=[0,7],selected_ordinals=[1,4,7],exact_physical_and_rng_suffix=True,official_calls=0))
