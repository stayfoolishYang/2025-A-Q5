"""Generate manuscript figures and tables from the existing numerical results."""
from pathlib import Path
import csv
import hashlib
import json
import sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

PAPER = Path(__file__).resolve().parent
ROOT = PAPER.parent
sys.path.insert(0, str(ROOT))
from physics.boundary import Boundary

FIG = PAPER / 'figures'
TAB = PAPER / 'tables'
FIG.mkdir(exist_ok=True)
TAB.mkdir(exist_ok=True)
font_manager.fontManager.addfont(str(PAPER/'完整论文-LaTeX/fonts/SimHei.ttf'))
plt.rcParams.update({'font.family':'SimHei','font.size':9, 'axes.titlesize':10,
    'axes.labelsize':9,'legend.fontsize':8,'axes.unicode_minus':False,
    'pdf.fonttype':42,'ps.fonttype':42,'savefig.dpi':360,'lines.linewidth':1.55,
    'axes.spines.top':False,'axes.spines.right':False,
    'axes.prop_cycle':plt.cycler(color=['#176B87','#D07935','#4F8460','#9A5B75','#5261A6'])})
COL=['#176B87','#D07935','#4F8460','#9A5B75','#5261A6']

def save(fig, name):
    fig.savefig(FIG/f'{name}.pdf', bbox_inches='tight')
    fig.savefig(FIG/f'{name}.png', bbox_inches='tight', dpi=360)
    plt.close(fig)

def grid(ax):
    ax.grid(alpha=.18)
    ax.set_axisbelow(True)

def load(q):
    d=np.load(ROOT/'results'/f'q{q}.npz')['data']
    n=(d.shape[1]-2)//2
    faces=np.r_[0,(np.arange(n-1)+.5)/(n-1),1]
    v=np.diff(faces**2)/2
    return d, n, v

b=Boundary(tail='mean')
t=np.linspace(0,14400,1000)
a=b.ambient(t)
fig,axs=plt.subplots(1,2,figsize=(6.25,2.55),layout='constrained')
for j,ax in enumerate(axs):
    ax.plot(t/3600,a[:,j],label='PCHIP 插值')
    ax.scatter(b.data[::6,0]/3600,b.data[::6,j+1],s=6,color=COL[1],label='观测值（每6点显示1点）',zorder=3)
    ax.set(xlabel='时间 / h',ylabel='温度 / °C' if j==0 else '附件水分变量 / (kg/kg)',title='(a) 烘房温度' if j==0 else '(b) 烘房水分变量')
    ax.axvspan(3,4,color=COL[2],alpha=.08)
    grid(ax)
axs[0].legend(loc='lower right',frameon=False)
save(fig,'boundary')

fig,axs=plt.subplots(1,2,figsize=(6.25,2.45),layout='constrained')
tr=np.linspace(0,72,1200)
rr=b.radius(tr*3600)
axs[0].plot(tr,rr*100,label='PCHIP 插值')
axs[0].scatter(b.radius_data[::4,0]/3600,b.radius_data[::4,1],s=6,c=COL[1],label='观测值（间隔2h显示）')
axs[0].axvline(51.0912847222,color=COL[2],ls='--',lw=1)
axs[0].set(xlabel='时间 / h',ylabel='半径 / cm',title='(a) 附件2半径轨迹')
axs[0].legend(frameon=False)
axs[1].plot(tr,.02**2/rr**2,label='扩散系数几何倍率 (R0/R)^2')
axs[1].plot(tr,.02/rr,label='边界系数几何倍率 R0/R')
axs[1].set(xlabel='时间 / h',ylabel='相对初始状态的倍率',title='(b) 归一化方程中的几何作用')
axs[1].legend(frameon=False,loc='lower right')
for ax in axs:grid(ax)
save(fig,'radius')

for q,times in [(1,[100,600,1200,1800]),(2,[1800,3600,7200,10800])]:
    d,n,v=load(q)
    fig,axs=plt.subplots(1,2,figsize=(6.25,2.55),layout='constrained')
    for time in times:
        row=d[np.argmin(abs(d[:,0]-time))]
        label=f'{time:g} s' if q==1 else f'{time/3600:g} h'
        axs[0].plot(np.linspace(0,2,n),row[2:2+n],label=label)
        axs[1].plot(np.linspace(0,2,n),row[2+n:],label=label)
    axs[0].set(ylabel='温度 / °C',title='(a) 温度的径向分布')
    axs[1].set(ylabel='干基含水率 / (kg/kg)',title='(b) 含水率的径向分布')
    for ax in axs:
        ax.set_xlabel('到轴线的距离 / cm')
        ax.legend(frameon=False,ncol=2)
        grid(ax)
    save(fig,f'q{q}_fields')

for q in [3,4]:
    d,n,v=load(q);c=d[:,2+n:]
    fig,axs=plt.subplots(1,2,figsize=(6.25,2.6),layout='constrained')
    axs[0].semilogy(d[:,0]/3600,c.max(axis=1),label='最大含水率')
    axs[0].semilogy(d[:,0]/3600,2*c@v,label='干质量加权平均')
    axs[0].semilogy(d[:,0]/3600,c[:,-1],label='侧表面')
    axs[0].axhline(.15,c='#777777',ls='--',lw=.8,label='达标阈值0.15')
    axs[0].set_yticks([.05,.1,.15,.3,1,2.55],labels=['0.05','0.1','0.15','0.3','1','2.55'])
    axs[0].yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    axs[0].set(xlabel='时间 / h',ylabel='干基含水率 / (kg/kg)',title='(a) 干燥过程（纵轴为对数）')
    axs[0].legend(frameon=False)
    for time in [6*3600,12*3600,24*3600,d[-1,0]]:
        row=d[np.argmin(abs(d[:,0]-time))]
        axs[1].plot(np.linspace(0,row[1]*100,n),row[2+n:],label=f'{time/3600:.2f} h')
    axs[1].set(xlabel='到轴线的距离 / cm',ylabel='干基含水率 / (kg/kg)',title='(b) 代表时刻的物理坐标剖面')
    axs[1].legend(frameon=False)
    for ax in axs:grid(ax)
    save(fig,f'q{q}_drying')

d,n,v=load(4);c=d[:,2+n:]
ratio=(d[:,1]/.02)**2*(2*((760+90*c)/(1+c))@v)/((760+90*2.55)/(1+2.55))
statistics={'q4_implied_dry_mass_min':float(ratio.min()),'q4_implied_dry_mass_min_time_h':float(d[ratio.argmin(),0]/3600),
    'q4_implied_dry_mass_final':float(ratio[-1]),'q4_final_mean_C':float(2*c[-1]@v)}
fig,axs=plt.subplots(1,2,figsize=(6.25,2.45),layout='constrained')
axs[0].plot(d[:,0]/3600,(.02/d[:,1])**2,label='独立干密度 s/s0')
axs[0].plot(d[:,0]/3600,np.ones(len(d)),ls='--',label='真实干质量 Md/Md0')
axs[0].set(xlabel='时间 / h',ylabel='相对初始值',title='(a) 随体收缩模型的质量定义')
axs[0].legend(frameon=False)
axs[1].plot(d[:,0]/3600,ratio,c=COL[1])
axs[1].axhline(1,ls='--',c='#777777',lw=.8)
axs[1].scatter([d[ratio.argmin(),0]/3600],[ratio.min()],s=17,c=COL[1])
axs[1].annotate(f'最低 {ratio.min():.4f}',xy=(d[ratio.argmin(),0]/3600,ratio.min()),xytext=(18,.78),arrowprops={'arrowstyle':'->','color':'#555555'},fontsize=8)
axs[1].set(xlabel='时间 / h',ylabel='推算干质量 / 初始推算干质量',title='(b) 额外令 s=ρ(C)/(1+C) 的矛盾')
for ax in axs:grid(ax)
save(fig,'q4_mass_definition')

cases=json.loads((ROOT/'results/q4_release_experiments.json').read_text())
by={r['name']:r for r in cases}
fig,axs=plt.subplots(1,2,figsize=(6.25,2.4),layout='constrained')
labels=['末点保持','末小时均值','名义平台']
values=[by[n]['event_h'] for n in ['material_last','material_mean','material_nominal']]
axs[0].barh(labels,values,color=[COL[1],COL[0],COL[2]],height=.55)
axs[0].set(xlim=(0,58),xlabel='干燥时长 / h',title='(a) 材料坐标的三种边界情景')
for i,val in enumerate(values):axs[0].text(val+.5,i,f'{val:.4f}',va='center',fontsize=8)
axs[1].barh(['固定半径','随体收缩','Eulerian对照'],[by[n]['event_h'] for n in ['fixed_mean','material_mean','eulerian_mean']],color=[COL[1],COL[0],COL[2]],height=.55)
axs[1].set(xlim=(0,151),xlabel='干燥时长 / h',title='(b) 同物性、同均值平台对照')
for i,name in enumerate(['fixed_mean','material_mean','eulerian_mean']):
    val=by[name]['event_h'];axs[1].text(val+1.5,i,f'{val:.4f}',va='center',fontsize=8)
for ax in axs:ax.invert_yaxis();ax.grid(axis='x',alpha=.18);ax.set_axisbelow(True)
save(fig,'q4_scenarios_ablation')

rows=list(csv.DictReader((ROOT/'results/q4_convergence.csv').open(encoding='utf-8-sig')))
bc={r['name']:r for r in rows}
fig,axs=plt.subplots(1,2,figsize=(6.25,2.45),layout='constrained')
x=np.array([41,81,161]);y=np.array([float(bc[f'grid_{n}']['event_h']) for n in x])
axs[0].plot(x,(y-y[-1])*3600,'o-')
axs[0].set(xlabel='径向节点数 N',ylabel='相对 N=161 的时差 / s',xticks=x,title='(a) 空间加密（时间步长1s）')
x=np.array([.5,1.,2.,4.]);y=np.array([float(bc[k]['event_h']) for k in ['dt_0.5','grid_81','dt_2','dt_4']])
axs[1].plot(x,(y-y[0])*3600,'o-')
axs[1].set(xlabel='时间步长 / s',ylabel='相对步长0.5s的时差 / s',xticks=x,title='(b) 时间加密（81节点）')
for ax in axs:grid(ax)
save(fig,'q4_convergence')

rows=list(csv.DictReader((ROOT/'results/q4_sensitivity.csv').open(encoding='utf-8-sig')))
fig,axs=plt.subplots(1,2,figsize=(6.25,2.5),layout='constrained')
for p,label in [('D',r'$D$'),('hm',r'$h_m$'),('hT',r'$h_T$'),('k',r'$k$')]:
    rr=[r for r in rows if r['parameter']==p]
    x=[float(r['factor']) for r in rr];y=[float(r['change_percent']) for r in rr]
    axs[0].plot(x,y,'o-',label=label,ms=3)
    if p!='D':axs[1].plot(x,y,'o-',label=label,ms=3)
for ax in axs:
    ax.set(xlabel='参数倍率',ylabel='干燥时长变化 / %',xticks=[.8,.9,1,1.1,1.2])
    ax.legend(frameon=False);grid(ax)
axs[0].set_title('(a) 全部参数的相对影响')
axs[1].set_title('(b) 其余三个参数的局部放大')
save(fig,'q4_sensitivity')

en=json.loads((ROOT/'results/endface_summary.json').read_text())
rr=en['representative_time_pairs']['fine'][1:]
fig,axs=plt.subplots(1,2,figsize=(6.25,2.5),layout='constrained')
x=np.arange(len(rr));w=.34
axs[0].bar(x-w/2,[r['mean_C_1d'] for r in rr],w,label='一维',color=COL[0])
axs[0].bar(x+w/2,[r['mean_C_2d'] for r in rr],w,label='二维开放端面',color=COL[1])
axs[0].set(xticks=x,xticklabels=['0.5','4','24','51.10'],xlabel='时间 / h',ylabel='平均干基含水率 / (kg/kg)',title='(a) 同设置配对的平均含水率')
axs[0].legend(frameon=False)
endata=np.load(ROOT/'results/endface_fine.npz')
statistics['endface_npz_shapes']={k:list(endata[k].shape) for k in endata.files}
delta=[100*(r['mean_C_2d']/r['mean_C_1d']-1) for r in rr]
axs[1].bar(x,delta,color=COL[1],width=.55)
for i,val in enumerate(delta):axs[1].text(i,val-.06,f'{val:.2f}%',ha='center',va='top',fontsize=8)
axs[1].set(xticks=x,xticklabels=['0.5','4','24','51.10'],xlabel='时间 / h',ylabel='二维相对一维的变化 / %',title='(b) 平均含水率对端面交换的响应',ylim=(-3.8,0))
for ax in axs:ax.grid(axis='y',alpha=.18);ax.set_axisbelow(True)
save(fig,'endface')

# The six requested tables: generate all displayed values from authoritative CSV.
captions=['30分钟内药材的温度（单位：$^\circ$C）','30分钟内药材的干基含水率（单位：kg/kg）',
          '3小时内药材的温度（单位：$^\circ$C）','3小时内药材的干基含水率（单位：kg/kg）',
          '固定半径药材烘干过程的干基含水率（单位：kg/kg）',
          '随体收缩药材烘干过程的干基含水率（单位：kg/kg）']
for i in range(1,7):
    rows=list(csv.reader((ROOT/'results'/f'table{i}.csv').open(encoding='utf-8-sig')))
    headers=rows[0];body=rows[1:]
    # CSV uses a textual first column; every remaining numerical entry has 4 decimals.
    nc=len(headers)
    colspec='r'+'r'*(nc-1)
    first='时间 / s' if i<=2 else '时间 / h'
    h=[first,'0 cm','0.5 cm','1 cm','1.5 cm','2 cm']
    if i==6:h+=['侧表面','半径 / cm']
    text=['\\begin{table}[htbp]',f'\\caption{{{captions[i-1]}}}\\label{{tab:required-{i}}}',
          '\\centering',('\\small' if i!=6 else '\\footnotesize'),f'\\begin{{tabular}}{{{colspec}}}','\\toprule',' & '.join(h)+r' \\',r'\midrule']
    for row in body:
        vals=[]
        for j,vv in enumerate(row):
            if vv in ('','—','nan'):vals.append('---')
            elif j==0:vals.append(f'{float(vv):.4f}' if i>=5 and float(vv)%6 else f'{float(vv):g}')
            else:vals.append(f'{float(vv):.4f}')
        text.append(' & '.join(vals)+r' \\')
    text += [r'\bottomrule',r'\end{tabular}',r'\end{table}']
    (TAB/f'table{i}.tex').write_text('\n'.join(text)+'\n',encoding='utf-8')

statistics['assets_sources']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
    [ROOT/'results'/f'q{q}.npz' for q in range(1,5)]+[ROOT/'results/q4_convergence.csv',ROOT/'results/q4_sensitivity.csv',ROOT/'results/endface_summary.json']}
(PAPER/'asset_statistics.json').write_text(json.dumps(statistics,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(statistics,ensure_ascii=False,indent=2))
