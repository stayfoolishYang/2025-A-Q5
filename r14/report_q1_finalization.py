import json,itertools,collections,hashlib
import numpy as np,pandas as pd
from collect import ROOT
OUT=ROOT/'analysis/q1_finalization';OUT.mkdir(exist_ok=True)
def main():
 g=collections.defaultdict(list)
 for p in (ROOT/'results/q1_finalization').glob('[0-9]*.json'):
  d=json.loads(p.read_bytes());g[(d['state']['id'],d['state']['step'])].append(d)
 assert len(g)==64 and all(len(v)==3 for v in g.values()),'Incomplete run'
 rows=[];channel_rows=[];ranges=[];failures=[]
 for (i,j),ds in sorted(g.items()):
  rs=[d['result'] for d in ds]
  if any(r['status']!='FUNCTIONAL_READY' for r in rs):failures.append(dict(id=i,step=j,reason='functional unavailable'));continue
  rr=np.ptp([r['p_new'] for r in rs],axis=0);ranges.extend(rr)
  union=set().union(*(set(r['top3']) for r in rs));closure=all(union<=set(r['candidates']) for r in rs)
  tv=max(.5*np.abs(np.array(a['pm'])-b['pm']).sum() for a,b in itertools.combinations(rs,2))
  jac=min(len(set(a['candidates'])&set(b['candidates']))/len(set(a['candidates'])|set(b['candidates'])) for a,b in itertools.combinations(rs,2))
  rows.append(dict(id=i,step=j,max_range=float(rr.max()),count_tv=float(tv),closure=closure,min_jaccard=jac,top3_union_size=len(union),replay_pass=sum(r['world_replay']=='PASS' for r in rs),top3_union=sorted(union),candidates=[r['candidates'] for r in rs]))
  for d in ds:
   r=d['result']
   if r['world_replay']!='PASS':failures.append(dict(id=i,step=j,bank=d['bank'],reason=r.get('world_reason','unknown')))
   for c,m in r.get('sampler_meta',{}).get('channels',{}).items():channel_rows.append(dict(id=i,step=j,bank=d['bank'],channel=c,**m))
 pd.DataFrame(rows).to_csv(OUT/'state_gates.csv',index=False);pd.DataFrame(channel_rows).to_csv(OUT/'proposal_diagnostics.csv',index=False)
 summary=dict(states=64,banks=192,max_probability_range=max(ranges),fraction_within_002=float(np.mean(np.array(ranges)<=.02)),max_count_tv=max(r['count_tv'] for r in rows),candidate_closure_states=sum(r['closure'] for r in rows),world_replay_pass=sum(r['replay_pass'] for r in rows),failures=failures,extended_channel_banks=sum(r['extended_budget'] for r in channel_rows),max_raw_attempts=max(r['raw_attempts'] for r in channel_rows),min_source_ess=min(r['source_ess'] for r in channel_rows),official_calls=0,continuations=0)
 summary['Q1_PASS']=bool(summary['fraction_within_002']>=.95 and summary['max_probability_range']<=.05 and summary['max_count_tv']<=.02 and summary['candidate_closure_states']==64 and summary['world_replay_pass']==192 and not failures)
 summary['Q2']='READY_FOR_CALIBRATION' if summary['Q1_PASS'] else 'BLOCKED'
 (OUT/'summary.json').write_text(json.dumps(summary,indent=2));(OUT/'source_manifest.json').write_text(json.dumps({f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in ['staged_world_sampler.py','audit_q1_finalization.py','unknown_discovery.py']},indent=2));print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
