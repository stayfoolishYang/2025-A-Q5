"""Read derived CSV only; never launches a solver. Run with Python/numpy/pandas/matplotlib."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1];D=ROOT/'02_绘图数据';F=ROOT/'03_参考图';F.mkdir(exist_ok=True)
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
def save(fig,name):
    fig.tight_layout();fig.savefig(F/(name+'.pdf'));fig.savefig(F/(name+'.png'),dpi=180);plt.close(fig)
c=pd.read_csv(D/'simulation_cases_final.csv');p=pd.read_csv(D/'paired_versions_same_1000.csv')
fig,ax=plt.subplots(figsize=(6,4))
for family,g in c.groupby('family'):
    y=np.sort(g.mean_time_per_source);ax.step(y,np.arange(1,len(y)+1)/len(y),where='post',label=f'{family} (n={len(y)})')
ax.set(xlabel='Virtual time per source (s/source)',ylabel='Empirical cumulative probability',title='Revised 21+R12+F+CT: simulation');ax.legend();save(fig,'01_ecdf')
fig,ax=plt.subplots(figsize=(6,4));ns=sorted(c.total.unique());ax.boxplot([c.loc[c.total==n,'mean_time_per_source'] for n in ns],tick_labels=ns)
ax.set(xlabel='Number of sources',ylabel='Virtual time per source (s/source)',title='Revised simulation: stratification by source count');save(fig,'02_source_count')
fig,axs=plt.subplots(1,2,figsize=(10,4))
for ax,col,title in [(axs[0],'delta_s_per_source','Historical B - historical A'),(axs[1],'final_minus_historical_B','Revised B - historical B')]:
    ax.scatter(p.id,p[col],s=6,alpha=.65);ax.axhline(0,color='black',lw=.8);ax.set(xlabel='Matched case ID',ylabel='Paired difference (s/source)',title=title)
save(fig,'03_paired_differences')
st=pd.read_csv(D/'stage_costs.csv');means=st.groupby('stage').total_s.sum()/len(c)
fig,ax=plt.subplots(figsize=(7,4));ax.barh(means.index,means.values,color='#326a9b');ax.set(xlabel='Mean virtual time per game (s)',title='Stage costs: revised simulation, n=1000');save(fig,'04_stage_costs')
points=np.array(json.loads((ROOT/'04_模拟原包展开/support/code/q4betterv3/points21.json').read_bytes())['points'])
fig,ax=plt.subplots(figsize=(6,6));a=np.linspace(0,2*np.pi,361);ax.plot(1800*np.cos(a),1800*np.sin(a),'--',color='gray',label='Source domain radius 1800 m');ax.scatter(*points.T,label='Provided 21 stations')
for i,(x,y) in enumerate(points):ax.annotate(str(i),(x,y),xytext=(4,4),textcoords='offset points',fontsize=8)
ax.set_aspect('equal');ax.set(xlabel='x (m)',ylabel='y (m)',title='Provided 21-point layout (not a coverage proof)');ax.legend(fontsize=8);save(fig,'05_station_layout')
selected=pd.read_csv(D/'representative_cases.csv');acts=pd.read_csv(D/'all_actions.csv');src=pd.read_csv(D/'all_sources_raw_fields.csv')
for _,r in selected.iterrows():
    i=int(r.case_id);g=acts[acts.case_id==i].sort_values('action_index');fig,ax=plt.subplots(figsize=(6,6))
    ax.plot(g.end_x_m,g.end_y_m,color='#9aa7b0',lw=.6,zorder=1)
    for stage,h in g.groupby('stage'):ax.scatter(h.end_x_m,h.end_y_m,s=6,label=stage)
    h=g[g.path=='/clear'];ax.scatter(h.end_x_m,h.end_y_m,marker='x',color='black',s=22,label='clear attempt')
    truth=src[src.case_id==i];ax.scatter(truth.x_um/1e6,truth.y_um/1e6,marker='*',facecolors='none',edgecolors='#b32032',s=65,label='source truth (offline)')
    ax.plot(1800*np.cos(a),1800*np.sin(a),'--',color='gray',lw=.8);ax.set_aspect('equal');ax.set(xlabel='x (m)',ylabel='y (m)',title=f'{r.family}: {r.selection}, case {i}, {r.seconds_per_source:.2f} s/source');ax.legend(fontsize=6,loc='upper left');save(fig,f'06_route_{r.family}_{r.selection}_{i}')
ev=pd.read_csv(D/'ct_events.csv');eligible=ev[(ev.adopted==True)&(ev.saving_us>0)].sort_values(['case_id','event_index']);e=eligible.iloc[0]
poly=pd.read_csv(D/'ct_polygons.csv');h=poly[(poly.case_id==e.case_id)&(poly.event_index==e.event_index)].sort_values('vertex_index');v=np.vstack([h[['x_m','y_m']].values,h[['x_m','y_m']].values[:1]])
fig,ax=plt.subplots(figsize=(6,5));ax.fill(v[:,0],v[:,1],alpha=.2,label='Hard polygon')
for name,marker in [('start','s'),('z','x'),('q','o'),('next','^')]:
    if pd.notna(e.get(name+'_x_m',np.nan)):ax.scatter(e[name+'_x_m'],e[name+'_y_m'],marker=marker,label=name)
for name in ['z','q']:
    ax.plot([e.start_x_m,e[name+'_x_m'],e.next_x_m],[e.start_y_m,e[name+'_y_m'],e.next_y_m],label=f'via {name}',lw=1)
ax.set_aspect('equal');ax.set(xlabel='x (m)',ylabel='y (m)',title=f'CT case {int(e.case_id)}, event {int(e.event_index)}; local saving {e.saving_us/1e6:.3f} s');ax.legend();save(fig,'07_ct_example')
print('Saved',len(list(F.glob('*.png'))),'PNG/PDF pairs')
