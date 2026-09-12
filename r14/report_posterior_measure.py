"""Evidence report for Q1; no advantage estimates or oracle costs."""
import json,collections,hashlib
from pathlib import Path
from collect import ROOT
import numpy as np
import pandas as pd
OUT=ROOT/'analysis/posterior_measure';OUT.mkdir(exist_ok=True)
worlds=[json.loads(p.read_bytes()) for p in (ROOT/'results/posterior_worlds_pivot').glob('*.json')]
channel_rows=[dict(id=w['state']['id'],step=w['state']['step'],repeat=w['repeat'],channel=c,**m) for w in worlds for c,m in w['result'].get('channels',{}).items()]
pd.DataFrame(channel_rows).to_csv(OUT/'channel_ess.csv',index=False)
banks=collections.defaultdict(list)
for p in (ROOT/'results/posterior_measure_pivot').glob('*bank*.json'):
    d=json.loads(p.read_bytes());banks[(d['state']['id'],d['state']['step'])].append(d)
rows=[]
for (i,j),ds in sorted(banks.items()):
    rs=[d['runs'][0] for d in ds];P=np.array([r['p_hit'] for r in rs])
    rows.append(dict(id=i,step=j,channel=ds[0]['channel'],phase=ds[0]['state']['phase'],banks=len(rs),max_probability_range=float(np.ptp(P,axis=0).max()),min_source_ess=min(r['source_ess'] for r in rs),top3_orderings=len(set(tuple(r['top3']) for r in rs)),top3_sets=len(set(tuple(sorted(r['top3'])) for r in rs))))
pd.DataFrame(rows).to_csv(OUT/'independent_bank_stability.csv',index=False)
summary=dict(Q0='PASS (observed replay regression)',Q1='NOT QUALIFIED',Q2='BLOCKED BY Q1',model='independent persistent uniform grid approximation',worlds=len(worlds),world_replay=dict(collections.Counter(w['result']['status'] for w in worlds)),known_channel_draws=len(channel_rows),min_source_ess=min(r['source_ess'] for r in channel_rows),min_selected_noise_ess=min(r['selected_noise_ess'] for r in channel_rows),independent_bank_states=len(rows),max_probability_range=max(r['max_probability_range'] for r in rows),changed_top3_sets=sum(r['top3_sets']>1 for r in rows),official_calls=0,new_end_to_end_runs=0,advantage_evaluations=0)
(OUT/'summary.json').write_text(json.dumps(summary,indent=2))
files=['grid_measure.py','weighted_world_sampler.py','audit_weighted_worlds.py','audit_posterior_measure.py','audit_pivot_measure.py']
(OUT/'source_manifest.json').write_text(json.dumps({f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files},indent=2))
from sampler_plot_style import paper_style
import matplotlib as mpl
import matplotlib.pyplot as plt
with paper_style(font='Times New Roman'):
    mpl.rcParams.update({'font.family':['Times New Roman','SimSun'],'svg.fonttype':'none'})
    fig,ax=plt.subplots(1,2,figsize=(9,3.5),layout='constrained')
    ess=np.sort([r['source_ess']/r['source_proposals'] for r in channel_rows])
    ax[0].plot(ess,np.arange(1,len(ess)+1)/len(ess),color='#0072BD');ax[0].set_xlabel('位置有效样本比例');ax[0].set_ylabel('累计比例');ax[0].set_xlim(0,1);ax[0].set_ylim(0,1)
    ax[1].bar(range(len(rows)),[r['max_probability_range']*100 for r in rows],color='#D95319');ax[1].set_xticks(range(len(rows)),[str(r['id']) for r in rows],rotation=45);ax[1].set_xlabel('审计场景编号');ax[1].set_ylabel('独立采样接收概率极差（百分点）')
    for a in ax:a.spines[['top','right']].set_visible(False)
    fig.savefig(OUT/'后验权重与稳定性.svg');fig.savefig(OUT/'后验权重与稳定性.png',dpi=180);plt.close(fig)
print(json.dumps(summary,indent=2))
