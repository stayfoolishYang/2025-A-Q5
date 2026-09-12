"""Report replay qualification; no continuation or policy scoring."""
import json,gzip,collections,sys
from pathlib import Path
import pandas as pd
from collect import ROOT
OUT=ROOT/'analysis/sampler_qualification';OUT.mkdir(parents=True,exist_ok=True)
source=ROOT/'results/value_oracle';states=json.loads((source/'selection.json').read_bytes())['states']
cache={};rows=[];internal=[]
for state in states:
    i,j=state['id'],state['step']
    if i not in cache:
        with gzip.open(source/'snapshots'/f'{i:04d}.json.gz','rt') as f:cache[i]=json.load(f)
    snap=cache[i][j];history=sum(len(h) for h in snap['history'].values())
    for version,folder in [('v1','sampler_qualification'),('v2','sampler_qualification_v2')]:
        p=ROOT/'results'/folder/f'{i:04d}_{j:02d}.json'
        if not p.exists():continue
        result=json.loads(p.read_bytes())
        for k,w in enumerate(result['worlds']):
            rows.append(dict(version=version,id=i,step=j,world_index=k,phase=state['phase'],N=state['N'],history_length=history,known_count=len(snap['confirmed']),rejected=int(w['status']!='compatible')))
            if version=='v2' and w['status']=='compatible':
                for c,kind in w['source_kinds'].items():
                    if int(c) in snap['confirmed']:internal.append(dict(kind=kind,channel=int(c),rejected=0))
                for r in w['noise_rejections']:internal.append(dict(kind=r['kind'],channel=r['channel'],rejected=1))
df=pd.DataFrame(rows);df.to_csv(OUT/'worlds.csv',index=False)
df['history_bin']=pd.cut(df.history_length,[-1,20,50,100,200,100000],labels=['0-20','21-50','51-100','101-200','201+'])
for col in ['phase','N','history_bin','known_count']:
    df.groupby(['version',col],observed=True).rejected.agg(['count','sum','mean']).to_csv(OUT/f'rejection_by_{col}.csv')
pd.DataFrame(internal).groupby('kind').rejected.agg(['count','sum','mean']).to_csv(OUT/'v2_noise_proposal_rejection_by_kind.csv')
pd.DataFrame(internal).groupby('channel').rejected.agg(['count','sum','mean']).to_csv(OUT/'v2_noise_proposal_rejection_by_channel.csv')
fs=[];diagnostics=list((ROOT/'results/sampler_diagnostics').glob('*_*_*.json'))
for p in diagnostics:fs.extend(json.loads(p.read_bytes())['failures'])
pd.DataFrame(fs).to_csv(OUT/'failed_observations.csv',index=False)
counts=collections.Counter(f['mechanism'] for f in fs)
summary=dict(status='NOT QUALIFIED',worlds=df.groupby('version').rejected.agg(['count','sum','mean']).to_dict('index'),failed_worlds_diagnosed=len(diagnostics),failed_observations=len(fs),mechanisms=dict(counts),official_calls=0,new_end_to_end_runs=0)
(OUT/'summary.json').write_text(json.dumps(summary,indent=2))
sys.path.insert(0,'C:/Users/13578/.codex/skills/matlab-scientific-plotting')
from sampler_plot_style import paper_style
import matplotlib as mpl
import matplotlib.pyplot as plt
with paper_style(font='Times New Roman'):
    mpl.rcParams.update({'font.family':['Times New Roman','SimSun'],'svg.fonttype':'none'})
    fig,ax=plt.subplots(1,2,figsize=(9,3.4),layout='constrained')
    classes=['ANGLE_ROUNDING_MISMATCH','NUMERIC_REPLAY_MISMATCH','RESPONSE_TYPE_MISMATCH']
    cc=collections.Counter(f['failure_class'] for f in fs)
    ax[0].bar(['报告角取整及裁剪','数值重放','响应类型'],[cc[c] for c in classes],color='#0072BD');ax[0].set_ylabel('失败观测数')
    grouped=df[df.version=='v1'].groupby('phase').rejected.mean().reindex(['early','middle','late'])
    ax[1].bar([{'early':'早期','middle':'中期','late':'后期'}.get(x,x) for x in grouped.index],grouped.values*100,color='#D95319');ax[1].set_ylabel('旧版世界拒绝率 (%)')
    for a in ax:a.spines[['top','right']].set_visible(False)
    fig.savefig(OUT/'失败分布.svg');fig.savefig(OUT/'失败分布.png',dpi=180);plt.close(fig)
print(json.dumps(summary,indent=2))

