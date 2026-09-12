"""Source-backed scientific figures. Run from repository root."""
import csv
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon
from geometry import coverage

BASE=Path(__file__).resolve().parent
OUT=BASE/'figures';OUT.mkdir(exist_ok=True)
plt.rcParams.update({'font.sans-serif':['Microsoft YaHei','DejaVu Sans'],'axes.unicode_minus':False,
    'svg.fonttype':'none','axes.spines.top':False,'axes.spines.right':False,'legend.frameon':False,
    'font.size':10,'axes.labelsize':10,'xtick.labelsize':9,'ytick.labelsize':9})
BLUE='#0F4D92';GRAY='#767676';RED='#B64342';TEAL='#42949E'


def save(fig,name):
    fig.savefig(OUT/f'{name}.svg',bbox_inches='tight')
    fig.savefig(OUT/f'{name}.png',dpi=300,bbox_inches='tight');plt.close(fig)


def main():
    check=json.loads((BASE/'results/geometry_checks.json').read_text())
    c=check['counterexample']; fig,ax=plt.subplots(figsize=(6,5))
    ax.add_patch(Polygon(c['polygon'],facecolor=BLUE,alpha=.15,edgecolor=BLUE))
    ax.add_patch(Circle(c['diameter_circle_center'],c['diameter_circle_radius'],fill=False,color=RED,linestyle='--',label='直径圆 R=20 m'))
    ax.add_patch(Circle(c['mec_center'],c['mec_radius'],fill=False,color=BLUE,label='最小包围圆 R=23.094 m'))
    p=np.array(c['polygon']);ax.scatter(*p.T,c=BLUE,s=30);ax.set(xlim=(-10,50),ylim=(-12,45),xlabel='x (m)',ylabel='y (m)',title='Q1：D≤40 m 仍不足以保证清除')
    ax.set_aspect('equal');ax.legend(loc='lower left');save(fig,'q1_counterexample')
    for mixed in (False,True):
        fig,ax=plt.subplots(figsize=(6,6));nodes=coverage(mixed)
        if not mixed:
            for p in nodes:ax.add_patch(Circle(p,1000,fill=False,color=TEAL,alpha=.35,lw=.8))
        else:
            for x in range(-2100,2101,700):
                ax.plot([x,x],[-2100,2100],color='#DDDDDD',lw=.6)
                ax.plot([-2100,2100],[x,x],color='#DDDDDD',lw=.6)
        ax.add_patch(Circle((0,0),1800,fill=False,color=BLUE,lw=2))
        ax.scatter(*nodes.T,color=BLUE,s=26,label=f'{len(nodes)}个检查点')
        ax.set(xlabel='x (m)',ylabel='y (m)',title='Q4：覆盖任意辐射半平面' if mixed else 'Q3：七点覆盖，连续上界997 m以内')
        ax.set_aspect('equal');ax.legend();save(fig,'q4_coverage' if mixed else 'q3_coverage')
    rows=list(csv.DictReader((BASE/'results/q2_candidates.csv').open(encoding='utf-8-sig')))
    p=np.array([[float(r['x']),float(r['y'])] for r in rows]);z=np.array([float(r['worst_sampled_diameter_m']) for r in rows])
    q2=json.loads((BASE/'results/q2.json').read_text());fig,ax=plt.subplots(figsize=(7,5))
    plot=ax.scatter(*p.T,c=z,s=15,cmap='viridis',vmax=300)
    chosen=np.array(q2['solutions'][1]['point']);ax.scatter(*chosen,marker='*',s=180,c=RED,label='λ=0.2 选点')
    ax.plot([0,1500*np.cos(np.pi/6)],[0,750],color=GRAY,ls='--',lw=1,label='初次30°示向线')
    ax.set(xlabel='x (m)',ylabel='y (m)',title='Q2：保证接收候选点及离散最坏后验直径')
    ax.set_aspect('equal');fig.colorbar(plot,ax=ax,label='直径 (m)');ax.legend();save(fig,'q2_candidates')
    data=list(csv.DictReader((BASE/'results/batch_v2/cases.csv').open(encoding='utf-8-sig')))
    for problem,policies in [(3,['P1','P2','P3']),(4,['P1','P4'])]:
        group=[[float(r['mean_time_per_source_s']) for r in data if r['mixed']==str(problem==4) and r['policy']==policy and r['use_negative']=='True'] for policy in policies]
        fig,ax=plt.subplots(figsize=(6,4));boxes=ax.boxplot(group,labels=policies,patch_artist=True,showfliers=True)
        for i,b in enumerate(boxes['boxes']):b.set_facecolor(BLUE if i==len(group)-1 else '#CFCECE');b.set_alpha(.65)
        ax.set(ylabel='平均定位清除时间 (s/源)',title=f'Q{problem}：100个配对种子 / 每种策略')
        save(fig,f'q{problem}_comparison')
    ab=json.loads((BASE/'results/ablations/summary.json').read_text())
    fig,ax=plt.subplots(figsize=(6,4));labels=['无时间调度','有时间调度'];vals=[ab['scheduling']['False'],ab['scheduling']['True']]
    ax.bar(labels,vals,color=['#CFCECE',BLUE]);ax.set(ylabel='平均定位清除时间 (s/源)',title='只改变调度开关：相同100个种子')
    for i,v in enumerate(vals):ax.text(i,v+4,f'{v:.2f}',ha='center');ax.set_ylim(0,max(vals)*1.15)
    save(fig,'scheduling_ablation')
    case=json.loads((BASE/'results/local_q3_seed0.json').read_text());fig,ax=plt.subplots(figsize=(6,6))
    path=np.array([[0,0]]+[r['position'] for r in case['log']]);ax.plot(*path.T,color=BLUE,lw=.8,alpha=.7,label='机器狗轨迹')
    sources=np.array([s['position'] for s in case['sources'].values()]);ax.scatter(*sources.T,c=RED,marker='x',label='合成源真实位置（仅评估用）')
    ax.add_patch(Circle((0,0),1800,fill=False,color=GRAY));ax.set_aspect('equal');ax.legend(fontsize=8)
    ax.set(xlabel='x (m)',ylabel='y (m)',title='Q3合成案例seed=0：探索与定位穿插');save(fig,'q3_route')
    cards=''.join(f'<section><h2>{p.stem}</h2><a href="{p.name}"><img src="{p.name}"></a><p><a href="{p.stem}.svg">可编辑SVG</a></p></section>' for p in OUT.glob('*.png'))
    (OUT/'index.html').write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><title>B题计算图表</title><style>body{max-width:1000px;margin:40px auto;font:16px sans-serif;background:#f7f8fa;color:#172b3b}section{background:white;padding:24px;margin-bottom:24px}img{max-width:100%}h2{font-size:20px}</style><h1>B题计算图表</h1><p>图表来自本地数值结果。正式测试未执行。</p>'+cards+'</html>',encoding='utf-8')
    print(f'Created {len(list(OUT.glob("*.png")))} SVG/PNG figure pairs')


if __name__=='__main__':main()
