import json,collections,math
from pathlib import Path
import pandas as pd,numpy as np
root=Path('r14');out=root/'analysis/tie_rollout200/detailed_audit';out.mkdir(exist_ok=True)
a=pd.read_csv(root/'analysis/tie_rollout200/candidate_estimates.csv');s=pd.read_csv(root/'analysis/tie_rollout200/states.csv');a=a.merge(s[['id','step','group']],on=['id','step'])
b=a.loc[a.groupby(['id','step'])['mean'].idxmax()].copy();pos=b[b['mean']>0].copy();bad=pos[pos.oracle_delta<0]
counts=dict(states=len(s),candidates=len(a),opportunity_states=int(s.candidate_opportunity.sum()),positive_mean_candidates=int((a['mean']>0).sum()),positive_lcb_candidates=int((a.lcb>0).sum()),risk_pass_candidates=int((a.loss_cvar90<=0).sum()),oracle_positive_candidates=int((a.oracle_delta>0).sum()),positive_mean_true_positive=int(((a['mean']>0)&(a.oracle_delta>0)).sum()),oracle_positive_pred_negative=int(((a['mean']<=0)&(a.oracle_delta>0)).sum()),mean_only_states=len(pos),mean_only_true_positive=int((pos.oracle_delta>0).sum()),mean_only_wrong=len(bad),mean_only_precision=float((pos.oracle_delta>0).mean()),mean_only_average_oracle_gain=float(pos.oracle_delta.mean()),mean_only_wrong_mean_loss=float(-bad.oracle_delta.mean()),mean_only_wrong_max_loss=float(-bad.oracle_delta.min()),mean_only_gain_per_completed_state=float(pos.oracle_delta.sum()/len(s)),candidate_pearson=float(a[['mean','oracle_delta']].corr().iloc[0,1]),minimum_cvar=float(a.loss_cvar90.min()),median_cvar=float(a.loss_cvar90.median()))
records=[json.loads(p.read_bytes()) for p in (root/'results/tie_rollout200').glob('[0-9]*.json')]
counts['partial_states']=[dict(id=d['state']['id'],step=d['state']['step'],paired=len(d.get('paired',[]))) for d in records if not d.get('complete')]
counts['stored_paired_worlds']=sum(len(d.get('paired',[])) for d in records);counts['stored_continuations']=sum(len(w['costs']) for d in records for w in d.get('paired',[]))
counts['completed_groups']=s.groupby('group').size().to_dict()
# Read-only, hypothetical ablations; no gate change and no new solver runs.
pos.to_csv(out/'hypothetical_mean_only_decisions.csv',index=False);a[a.lcb>0].to_csv(out/'positive_lcb_candidates.csv',index=False)
a.groupby('group').agg(candidates=('candidate','size'),positive_mean=('mean',lambda x:int((x>0).sum())),oracle_positive=('oracle_delta',lambda x:int((x>0).sum()))).to_csv(out/'group_candidates.csv')
(out/'metrics.json').write_text(json.dumps(counts,indent=2));print(json.dumps(counts,indent=2))
