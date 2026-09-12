import json,collections,hashlib
import numpy as np,pandas as pd
from collect import ROOT
OUT=ROOT/'analysis/random_blocks_rb';OUT.mkdir(exist_ok=True)
summary={};allrows=[]
for folder in ['receive_rb','rb64']:
 g=collections.defaultdict(list);failures=[]
 for p in (ROOT/'results'/folder).glob('[0-9]*.json'):
  d=json.loads(p.read_bytes())
  if 'p_hit' not in d:failures.append(d);continue
  g[(d['state']['id'],d['state']['step'])].append(d)
 allranges=[];changed=0;degenerate=0;cleared=0;indranges=[]
 for (i,j),ds in sorted(g.items()):
  assert len(ds)==3
  P=np.array([d['p_hit'] for d in ds]);ranges=np.ptp(P,axis=0);allranges.extend(ranges);indranges.extend(np.ptp([d['indicator'] for d in ds],axis=0))
  same=len(set(tuple(sorted(d['top3'])) for d in ds))==1;changed+=not same;degenerate+=bool(np.all(P==0));cleared+=ds[0]['cleared']
  allrows.append(dict(experiment=folder,id=i,step=j,max_range=float(ranges.max()),top3_same=same,gap3_min=min(d['gap3'] for d in ds) if all(d['gap3'] is not None for d in ds) else None,cleared=ds[0]['cleared'],all_zero=bool(np.all(P==0))))
 summary[folder]=dict(states=len(g),banks=sum(map(len,g.values())),nodes=len(allranges),max_range=max(allranges),fraction_within_002=float(np.mean(np.array(allranges)<=.02)),top3_agreement=1-changed/len(g),same_bank_indicator_max_range=max(indranges),cleared_source_states=int(cleared),all_zero_states=int(degenerate))
 summary[folder]['unsupported_banks']=len(failures)
 summary[folder]['attempted_states']=len(g)+len(set((d['state']['id'],d['state']['step']) for d in failures))
 summary[folder]['local_functional_gate']=bool(not failures and summary[folder]['max_range']<=.05 and summary[folder]['fraction_within_002']>=.95 and summary[folder]['top3_agreement']>=.95)
pd.DataFrame(allrows).to_csv(OUT/'functional_stability.csv',index=False)
summary.update(Q0='PASS observed history',Q1='NOT QUALIFIED: 64-state gate not passed: unsupported no-known-source states and full sampler coverage incomplete',Q2='BLOCKED',official_calls=0,continuations=0,new_end_to_end_runs=0)
(OUT/'summary.json').write_text(json.dumps(summary,indent=2))
# Boundary mass aligned to every A bank; preserve zeros and identify channel status.
rows=[]
for p in (ROOT/'results/random_block_audit').glob('*_A.json'):
 d=json.loads(p.read_bytes())
 for k,prob in enumerate(d['p_hit']):rows.append(dict(id=d['state']['id'],step=d['state']['step'],pair=d['pair'],node=k,p=prob,cleared=d['cleared'],radius_mass=d['radius_boundary_mass'][k],heading_mass=d['heading_boundary_mass'][k],radius_relevant_mass=d['radius_relevant_boundary_mass'][k],heading_relevant_mass=d['heading_relevant_boundary_mass'][k]))
pd.DataFrame(rows).to_csv(OUT/'boundary_masses.csv',index=False)
files=['receive_integral.py','audit_receive_rb.py','audit_random_blocks.py','select_rb64.py','audit_rb64.py','check_receive_integral.py']
(OUT/'source_manifest.json').write_text(json.dumps({f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files},indent=2))
print(json.dumps(summary,indent=2))
