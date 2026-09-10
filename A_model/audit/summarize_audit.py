import json
from pathlib import Path
import sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from solver.fvm_cpu import solve, geometry
from physics.boundary import Boundary
from physics.material import MODEL_Q4

dest=Path(__file__).resolve().parent
m=json.loads((dest/'results.json').read_text(encoding='utf-8'))
b=Boundary(); late=b.data[b.data[:,0]>=10800,1:]
stats=dict(last_hour_samples=len(late),last_hour_mean=late.mean(0).tolist(),
           last_hour_min=late.min(0).tolist(),last_hour_max=late.max(0).tolist(),
           last_hour_sample_std=late.std(0,ddof=1).tolist(),
           geometry_reduction_h=m['fixed']['event_h']-m['moving_material']['event_h'],
           eulerian_term_increment_h=m['moving_eulerian']['event_h']-m['moving_material']['event_h'],
           net_reduction_h=m['fixed']['event_h']-m['moving_eulerian']['event_h'])
_,v=geometry(81)
stats['independent_budget_output1s']={}
for name,ale in [('moving_material',False),('moving_eulerian',True)]:
    data,meta=solve(model=MODEL_Q4,moving=True,ale=ale,tail='last',n=81,dt=.5,interval=1.,end=60*3600.)
    C=data[:,83:]; avg=2*(C@v)
    flux=-2*8e-7/data[:,1]*(C[:,-1]-b.ambient(data[:,0])[:,1])
    mismatch=(avg[-1]-2.55-np.trapz(flux,data[:,0]))/2.55
    stats['independent_budget_output1s'][name]=float(mismatch)
    del data,C,avg,flux
(dest/'diagnostics.json').write_text(json.dumps(stats,indent=2),encoding='utf-8')
fig,axes=plt.subplots(2,2,figsize=(12,8),layout='constrained')
for name,label in [('fixed','Fixed R=2 cm'),('moving_material','Moving, material'),('moving_eulerian','Moving, Eulerian')]:
    data=np.load(dest/(name+'.npz'))['data']
    axes[0,0].plot(data[:,0]/3600,data[:,83:].max(1),label=label)
    budget=np.loadtxt(dest/(name+'_budget.csv'),delimiter=',',skiprows=1)
    axes[1,0].plot(budget[:,0]/3600,budget[:,3],label=label)
    axes[1,1].plot(budget[:,0]/3600,100*budget[:,4],label=label)
axes[0,0].axhline(.15,c='gray',ls='--');axes[0,0].set(ylabel='Max dry-basis moisture (kg/kg)',xlabel='Time (h)');axes[0,0].legend()
names=['fixed','moving_material','moving_eulerian']
bars=axes[0,1].bar(['Fixed','Moving\nmaterial','Moving\nEulerian'],[m[k]['event_h'] for k in names],color=['C0','C1','C2'])
axes[0,1].bar_label(bars,fmt='%.4f h');axes[0,1].set(ylabel='Threshold time (h)',ylim=(0,145))
axes[1,0].axhline(1,c='gray',ls='--');axes[1,0].set(xlabel='Time (h)',ylabel='Implied dry mass / initial dry mass',title='Conditional on rho(C) = total wet density')
axes[1,1].set(xlabel='Time (h)',ylabel='Water-budget mismatch (% initial water)',title='Uniform material density; 60 s quadrature')
fig.suptitle('Q4 controlled audit: same appendix-4 properties, N=81, dt=0.5 s')
fig.savefig(dest/'audit.png',dpi=180);fig.savefig(dest/'audit.svg')
print(json.dumps(stats,indent=2))
