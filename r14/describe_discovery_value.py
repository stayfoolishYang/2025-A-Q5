"""Residual-time weighted hits are descriptive, not marginal-value estimates."""
import json,gzip
from pathlib import Path
import pandas as pd
import numpy as np
from collect import ROOT
from bounded_rerank import length
from endpoint_cost import scan
SOURCE=ROOT/'results/prior_comparison128';rows=[]
for i in range(128):
    r=json.loads((SOURCE/'core/rows'/f'R12_{i:04d}.json').read_bytes())
    with gzip.open(SOURCE/'snapshots'/f'{i:04d}.json.gz','rt') as f:states=json.load(f)
    metrics=json.loads((SOURCE/'evaluation1800'/f'{i:04d}.json').read_bytes())['rows']
    lookup={(m['step'],m['method']):m for m in metrics}
    for step,s in enumerate(states):
        residual=r['virtual_time_s']-s['time_s'];mandatory=length(s['nodes'],s['position'])/5+scan(s['channel'],set(s['cleared']),len(s['nodes']))[0]
        rows.append(dict(id=i,step=step,N=r['total'],confirmed=len(s['confirmed']),residual=residual,planned_discovery_cost=mandatory,
             belief_hit=lookup[step,'belief']['top1'],R12_hit=lookup[step,'R12']['top1']))
d=pd.DataFrame(rows);d['residual_quartile']=pd.qcut(d.residual,4,labels=['Q1_low','Q2','Q3','Q4_high'])
out=ROOT/'analysis/discovery_value';out.mkdir(exist_ok=True)
d.to_csv(out/'descriptive_states.csv',index=False)
q=d.groupby('residual_quartile',observed=True).agg(states=('id','size'),residual_mean=('residual','mean'),belief_hit=('belief_hit','mean'),R12_hit=('R12_hit','mean'))
q.to_csv(out/'residual_quartiles.csv');print(q.to_string())
results=[]
for w in ['residual','planned_discovery_cost']:
    for method in ['belief_hit','R12_hit']:results.append(dict(weight=w,method=method,weighted_hit=np.average(d[method],weights=d[w])))
pd.DataFrame(results).to_csv(out/'weighted_hits.csv',index=False);print(pd.DataFrame(results).to_string(index=False))
