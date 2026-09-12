"""Q1-U gate report; all attempted states retained, ranking threshold unchanged."""
import json,itertools,collections,hashlib
import numpy as np,pandas as pd
from collect import ROOT
OUT=ROOT/'analysis/unknown_discovery';OUT.mkdir(exist_ok=True)
def main():
 g=collections.defaultdict(list)
 for p in (ROOT/'results/unknown_discovery').glob('[0-9]*.json'):
  d=json.loads(p.read_bytes());g[(d['state']['id'],d['state']['step'])].append(d)
 assert len(g)==64 and all(len(ds)==3 for ds in g.values()),'Not all banks complete'
 rows=[];node_rows=[];failures=[];alltv=[]
 for (i,j),ds in sorted(g.items()):
  rs=[d['result'] for d in ds]
  if any(r['status']!='FUNCTIONAL_READY' for r in rs):failures.append((i,j));continue
  P=np.array([r['p_new'] for r in rs]);ranges=np.ptp(P,axis=0);same=len(set(tuple(sorted(r['top3'])) for r in rs))==1
  tv=max(.5*np.abs(np.array(a['pm'])-b['pm']).sum() for a,b in itertools.combinations(rs,2));alltv.append(tv)
  gap=[r['gap3'] for r in rs if r['gap3'] is not None]
  rows.append(dict(id=i,step=j,known=rs[0]['known'],classes=rs[0]['classes'],max_range=float(ranges.max()),top3_same=same,gap3_max=max(gap) if gap else None,gap3_min=min(gap) if gap else None,count_tv=float(tv),replay_pass=sum(r['world_replay']=='PASS' for r in rs),zero_event=bool(np.all(P==0))))
  for q,r in enumerate(ranges):node_rows.append(dict(id=i,step=j,node=q,probability_range=float(r),mean_probability=float(P[:,q].mean())))
 df=pd.DataFrame(rows);nf=pd.DataFrame(node_rows);df.to_csv(OUT/'states.csv',index=False);nf.to_csv(OUT/'nodes.csv',index=False)
 summary=dict(attempted_states=64,banks=192,supported_states=len(rows),functional_failures=failures,state_nodes=len(node_rows),max_probability_range=float(nf.probability_range.max()),fraction_within_002=float((nf.probability_range<=.02).mean()),top3_agreement=float(df.top3_same.mean()),ranking_changed_states=int((~df.top3_same).sum()),max_count_tv=max(alltv),world_replay_pass=int(df.replay_pass.sum()),zero_known_states=int((df.known==0).sum()),zero_event_states=int(df.zero_event.sum()),max_changed_state_gap=float(df.loc[~df.top3_same,'gap3_max'].max()) if (~df.top3_same).any() else None,official_calls=0,continuations=0)
 summary['gate_pass']=bool(not failures and summary['fraction_within_002']>=.95 and summary['max_probability_range']<=.05 and summary['top3_agreement']>=.95 and summary['max_count_tv']<=.02 and summary['world_replay_pass']==192)
 summary['Q1_U']='PASS_ON_FROZEN_GATE' if summary['gate_pass'] else 'NOT QUALIFIED';summary['Q2']='NOT RUN' if summary['gate_pass'] else 'BLOCKED'
 (OUT/'summary.json').write_text(json.dumps(summary,indent=2))
 files=['unknown_discovery.py','audit_unknown_discovery.py','check_unknown_discovery.py','check_unknown_groups.py','weighted_world_sampler.py']
 (OUT/'source_manifest.json').write_text(json.dumps({f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files},indent=2));print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
