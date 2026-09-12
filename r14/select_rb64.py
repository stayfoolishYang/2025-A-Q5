import json,gzip,numpy as np
from collect import ROOT
out=ROOT/'results/rb64';out.mkdir(exist_ok=True)
states=json.loads((ROOT/'results/value_oracle/selection.json').read_bytes())['states'];selected=[];used=set()
for name,predicate in [('early',lambda s:s['phase']=='early'),('middle',lambda s:s['phase']=='middle'),('late',lambda s:s['phase']=='late' and s['N']!=16),('N16late',lambda s:s['phase']=='late' and s['N']==16)]:
 pool=[s for s in states if predicate(s)];pool=sorted(pool,key=lambda s:(s['time_s'],s['id'],s['step']))
 for ix in np.linspace(0,len(pool)-1,16).astype(int):
  s=dict(pool[ix],qualification_group=name);key=(s['id'],s['step']);assert key not in used;used.add(key);selected.append(s)
# Explicitly include diagnosed low-ESS case in its stratum, without duplicates.
worst=next(s for s in states if s['id']==653 and s['step']==18)
if (653,18) not in used:
 group='N16late' if worst['N']==16 else 'late';idx=next(i for i,s in enumerate(selected) if s['qualification_group']==group);selected[idx]=dict(worst,qualification_group=group,audit_channel=14)
else:
 for s in selected:
  if (s['id'],s['step'])==(653,18):s['audit_channel']=14
(out/'selection.json').write_text(json.dumps(selected,indent=2))
(out/'preregistration.json').write_text(json.dumps(dict(states=64,banks=3,sources=512,noise=512,probability_fraction_within_002=.95,max_range=.05,top3_agreement=.95,scope='one known-source functional per state; NOT whole-sampler qualification',Q2='remains blocked pending unknown-channel and full-world coverage',selection='time-stratified plus explicit difficult channel; no oracle costs'),indent=2))
