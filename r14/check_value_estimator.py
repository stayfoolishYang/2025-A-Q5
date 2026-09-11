"""Integration checks, not estimator performance evidence or gate tuning."""
import json,gzip
from collect import ROOT,SIM,bench,rb,phase_audit,StudySolver
from paired_value_estimator import public_state,estimate
SOURCE=ROOT/'results/value_oracle';OUT=ROOT/'results/value_estimator_integration'
m=json.loads((SOURCE/'manifest.json').read_bytes())
for r in m['records']:r['file']=str(SOURCE/r['file'])
if not(OUT/'manifest.json').exists():rb.save(OUT/'manifest.json',m)
reports=[]
class Capture(StudySolver):
    def decision(self,nodes):
        action=super().decision(nodes)
        if action[0]=='explore':
            self.ordinal=getattr(self,'ordinal',0)+1
            if self.ordinal==4:
                # Eight paired worlds verify state transfer and full continuation.
                # Production qualification retains a maximum64-world gate.
                result=estimate(public_state(self),self.api.log,nodes,1400800,max_worlds=8)
                reports.append(result)
        return action
for i in (0,512):
    old=phase_audit.TaggedSolver;phase_audit.TaggedSolver=Capture
    try:r=bench.run_case((str(OUT),str(SIM),i,'R12',False))
    finally:phase_audit.TaggedSolver=old
    ref=json.loads((SOURCE/'core/rows'/f'R12_{i:04d}.json').read_bytes())
    assert r['virtual_time_s']==ref['virtual_time_s'] and r['audit_passed']
    print('INTEGRATION',i,reports[-1]['available'],reports[-1].get('worlds'),reports[-1].get('reason'),flush=True)
rb.save(ROOT/'VALUE_ESTIMATOR_INTEGRATION.json',dict(reports=reports,baseline_execution_unchanged=True,official_calls=0))
