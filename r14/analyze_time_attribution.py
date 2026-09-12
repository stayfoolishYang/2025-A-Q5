"""Paired ledger decomposition: physical costs and task stages are separate views."""
from pathlib import Path
import json,gzip
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parent;SOURCE=ROOT/'results/bounded_development128';OUT=ROOT/'analysis/bounded_development128/time_attribution';OUT.mkdir(exist_ok=True)
rows=[]
for p in sorted((SOURCE/'core/traces').glob('*.json.gz')):
    with gzip.open(p,'rt') as f:t=json.load(f)
    r=t['row'];n=r['total'];assert r['audit_passed'] and r['run_status']=='FULL_CLEAR'
    assert abs(sum(s['total_s'] for s in t['stages'].values())-r['virtual_time_s'])<1e-6
    d=dict(id=r['id'],arm=r['variant'],N=n,total=r['virtual_time_s'],runtime=r['runtime_s'])
    for stage,s in t['stages'].items():
        for component in ('travel_s','measure_s','switch_s','clear_s','total_s'):
            d[stage+'__'+component]=s[component]
    for component in ('travel_s','measure_s','switch_s','clear_s'):
        d['all__'+component]=sum(s[component] for s in t['stages'].values())
    for key in ('last_source_first_seen_s','post_last_seen_discovery_s','post_all_cleared_discovery_s','discovery_nodes','detect_count','clear_attempts','fallback_count','diagnostic_count','distance'):
        d[key]=r[key]
    rows.append(d)
df=pd.DataFrame(rows);assert len(df)==640
base=df[df.arm=='R12'].set_index('id');deltas=[]
cols=[c for c in df.columns if c not in ('id','arm','N')]
for arm in ('B0','B5','B10','B20'):
    g=df[df.arm==arm].set_index('id');assert (g.N==base.N).all()
    delta=g[cols]-base[cols]
    for key in cols:
        deltas.append(dict(arm=arm,metric=key,delta_per_scene=delta[key].mean(),delta_per_source=(delta[key]/base.N).mean()))
    worst=delta.total/base.N;chosen=worst.sort_values(ascending=False).head(5).index
    detail=delta.loc[chosen].copy();detail.insert(0,'delta_s_per_source',worst.loc[chosen]);detail.to_csv(OUT/f'{arm}_worst5.csv')
    for i in chosen[:1]:
        with gzip.open(SOURCE/'routing_events'/f'{arm}_{i:04d}.json.gz','rt') as f:events=json.load(f)
        deviations=[e for e in events if e.get('index',0)!=0]
        (OUT/f'{arm}_worst_event.json').write_text(json.dumps(dict(id=int(i),first_deviation=deviations[0] if deviations else None,deviations=len(deviations),all_events=events),indent=2))
result=pd.DataFrame(deltas);result.to_csv(OUT/'paired_time_decomposition.csv',index=False);df.to_csv(OUT/'per_case_ledger.csv',index=False)
for selected in [['total','all__travel_s','all__measure_s','all__switch_s','all__clear_s'],['discovery__total_s','active_localization__total_s','diagnostic__total_s','optical_fallback__total_s','certified_clear__total_s'],['discovery__travel_s','discovery__measure_s','discovery__switch_s','last_source_first_seen_s','post_last_seen_discovery_s','post_all_cleared_discovery_s','distance','runtime']]:
    print(result[result.metric.isin(selected)].pivot(index='metric',columns='arm',values='delta_per_source').to_string())
print('WORST B0');print(pd.read_csv(OUT/'B0_worst5.csv').iloc[:1].to_string(index=False))
