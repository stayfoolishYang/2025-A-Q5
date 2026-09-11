"""Twelve evidence figures. Uses complete samples, no clipping or smoothing."""
from pathlib import Path
import sys,json,gzip
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib import font_manager
sys.path.insert(0,'C:/Users/13578/.codex/skills/matlab-scientific-plotting')
from matlab_sci_style import paper_style,MATLAB_COLORS
ROOT=Path(__file__).resolve().parent;A=ROOT/'analysis';O=ROOT/'figures';O.mkdir(exist_ok=True)
ORDER=['R12','A1','B-lite','C1','C2','D','E-H2','A1+C2','A1+D','C2+D']
LABEL={'R12':'基线 R12','A1':'强路线 A1','B-lite':'端点 B','C1':'扫描平分 C1','C2':'扫描前瞻 C2','D':'软释放 D','E-H2':'两步前瞻 E'}
def lab(m):return LABEL.get(m,m)
def color(m):return MATLAB_COLORS[ORDER.index(m)%7] if m in ORDER else '#444444'
def read(n):return pd.read_csv(A/n)
def loadtrace(cohort,m,i):
    with gzip.open(ROOT/'results'/cohort/'core/traces'/f'{m}_{int(i):04d}.json.gz','rt',encoding='utf-8') as f:return json.load(f)
def ecdf(ax,x,label,c):
    x=np.sort(np.asarray(x));ax.step(x,np.arange(1,len(x)+1)/len(x),where='post',label=label,color=c)
def axes(n=2,h=6):return plt.subplots(1,n,figsize=(10 if n>1 else 7,h/2.54),layout='constrained',squeeze=False)[0:2]
def save(fig,num,name,pdf):
    stem=f'{num:02d}_{name}'
    for ext in ('svg','pdf','png'):fig.savefig(O/f'{stem}.{ext}',dpi=240)
    pdf.savefig(fig);plt.close(fig)

def main():
    font_manager.findfont('SimSun',fallback_to_default=False);font_manager.findfont('Times New Roman',fallback_to_default=False)
    d=read('development_summary.csv');p=read('development_pairs.csv');r=read('development_routes.csv');st=read('development_strata.csv');dc=read('development_decisions.csv');rows=read('development_rows.csv')
    methods=[m for m in ORDER if m in set(d.method) and m!='R12']
    selected=json.loads((ROOT/'FINAL_DECISION.json').read_bytes());candidate=selected['comparison_candidate'];cohort='holdout' if (A/'holdout_pairs.csv').exists() and candidate in set(read('holdout_pairs.csv').method) else 'development'
    cp=read(f'{cohort}_pairs.csv');cg=cp[cp.method==candidate]
    with paper_style(font='Times New Roman',overrides={'font.family':['Times New Roman','SimSun'],'font.size':9,'axes.labelsize':9,'xtick.labelsize':8,'ytick.labelsize':8,'legend.fontsize':8,'axes.unicode_minus':False}),PdfPages(O/'R13_12张机制与效果图谱.pdf') as pdf:
        fig,aa=axes(3,10);aa=aa[0]
        for ax,metric in zip(aa,['mean','P95','P99']):
            for i,m in enumerate(methods):
                v=d[d.method==m].iloc[0];value=v.improvement_pct if metric=='mean' else -v[metric+'_change_pct'];lo=v[metric+'_improvement_ci_low'];hi=v[metric+'_improvement_ci_high']
                ax.plot([lo,hi],[i,i],color=color(m));ax.scatter(value,i,color=color(m),s=24)
            ax.axvline(0,color='.5',lw=.7);ax.set_yticks(range(len(methods)),[lab(m) for m in methods]);ax.set_xlabel({'mean':'均值','P95':'95% 分位数','P99':'99% 分位数'}[metric]+'改善 (%)')
        save(fig,1,'单模块效果与成对区间',pdf)
        fig,aa=axes(2,9);aa=aa[0]
        for m in methods:
            g=p[p.method==m];ecdf(aa[0],g.delta_s,lab(m),color(m));ecdf(aa[1],g.improvement_pct,lab(m),color(m))
        for ax in aa:ax.axvline(0,color='.5',lw=.7);ax.set_ylabel('累计场景比例')
        aa[0].set_xlabel('相对基线耗时差 (s/源)');aa[1].set_xlabel('逐场改善 (%)');aa[0].legend(fontsize=7,ncol=2)
        save(fig,2,'同场景收益分布',pdf)
        fig,aa=axes(2,9);aa=aa[0];ar=r[r.method=='A1'];by=ar.groupby('id').agg(gap=('gap','mean'),survival=('fraction_of_planned_route_executed','mean'));ap=p[p.method=='A1'].set_index('id').join(by)
        c=aa[0].scatter(ap.gap*100,ap.improvement_pct,c=ap.N,cmap='viridis',s=22);fig.colorbar(c,ax=aa[0],label='源数');aa[0].set_xlabel('场景内路线平均差距 (%)');aa[0].set_ylabel('整局改善 (%)');aa[0].axhline(0,color='.5',lw=.7)
        aa[1].scatter(ar.gap*100,ar.fraction_of_planned_route_executed,s=5,alpha=.2,color=color('A1'));aa[1].set_xlabel('单次路线差距 (%)');aa[1].set_ylabel('计划路程实际执行比例')
        save(fig,3,'静态路线收益兑现',pdf)
        fig,aa=axes(3,9);aa=aa[0]
        for m in ['R12','A1']:
            g=r[r.method==m]
            for ax,key in zip(aa,['route_survival_nodes','route_survival_time','fraction_of_planned_route_executed']):ecdf(ax,g[key],lab(m),color(m));ax.set_ylabel('路线记录累计比例')
        for ax,label in zip(aa,['执行节点数','执行时间 (s)','执行路程比例']):ax.set_xlabel(label)
        aa[0].legend();save(fig,4,'计划路线存活',pdf)
        fig,aa=axes(2,9);aa=aa[0]
        for m in methods:
            g=st[st.method==m];aa[0].plot(g.N,g.improvement_pct,'o-',color=color(m),label=lab(m));aa[1].plot(g.N,g.CV,'o-',color=color(m))
        aa[0].axhline(0,color='.5',lw=.7);aa[0].set_ylabel('分层均值改善 (%)');aa[1].set_ylabel('归一化耗时变异系数')
        for ax in aa:ax.set_xlabel('源数');ax.set_xticks(range(10,17))
        aa[0].legend(fontsize=6,ncol=2);save(fig,5,'源数分层与波动',pdf)
        fig,aa=axes(2,9);aa=aa[0]
        for m in methods:
            g=p[p.method==m];aa[0].scatter(g.distance_delta_m/1000,g.measure_delta,s=10,alpha=.4,color=color(m),label=lab(m));aa[1].scatter(g.distance_delta_m.mean()/1000,g.measure_delta.mean(),s=45,color=color(m),label=lab(m))
        for ax in aa:ax.axhline(0,color='.5',lw=.7);ax.axvline(0,color='.5',lw=.7);ax.set_xlabel('路程差 (km)');ax.set_ylabel('测量次数差')
        aa[1].legend(fontsize=7);save(fig,6,'移动与测量权衡',pdf)
        fig,aa=axes(3,9);aa=aa[0];c=read('archived_certified_credit.csv')
        for key,g in c.groupby('next_action'):ecdf(aa[0],g.scan_credit_s,{'certified_clear':'保证清除','discovery':'发现扫描','active_localization':'主动定位','diagnostic':'诊断'}.get(key,key),'#555555' if key=='discovery' else color('C2'))
        aa[0].set_xlabel('局部反事实扫描抵扣 (s)');aa[0].set_ylabel('状态累计比例');aa[0].legend(fontsize=6)
        aa[1].scatter(c.nodes,c.scan_credit_s,s=5,alpha=.15);aa[1].set_xlabel('剩余保证节点数');aa[1].set_ylabel('扫描抵扣 (s)')
        aa[2].scatter(c.current_channel,c.scan_credit_s,s=5,alpha=.15,color=color('C2'));aa[2].set_xlabel('当前测量频道');aa[2].set_ylabel('扫描抵扣 (s)');save(fig,7,'认证清除的扫描抵扣',pdf)
        fig,aa=axes(2,9);aa=aa[0]
        for m in ['R12','D']:
            g=rows[(rows.variant==m)&(rows.total==16)];ecdf(aa[0],g.post_known16_s,lab(m),color(m))
        aa[0].set_xlabel('确认16源至完成 (s)');aa[0].set_ylabel('场景累计比例');aa[0].legend()
        g=p[(p.method=='D')&(p.N==16)];aa[1].scatter(g.baseline_post_known16_s,g.post_known16_s,c=g.delta_s,cmap='coolwarm',s=30);lim=max(g.baseline_post_known16_s.max(),g.post_known16_s.max());aa[1].plot([0,lim],[0,lim],color='.5',lw=.8);aa[1].set_xlabel('基线剩余时间 (s)');aa[1].set_ylabel('软释放剩余时间 (s)');save(fig,8,'确认上限后的完成效率',pdf)
        fig,aa=axes(2,9);aa=aa[0]
        for m in methods:
            g=dc[dc.method==m];ecdf(aa[0],g.decision_ms,lab(m),color(m));q=g.groupby('id').decision_ms.quantile(.95);ecdf(aa[1],q,lab(m),color(m))
        for ax in aa:ax.set_xscale('symlog',linthresh=1);ax.set_ylabel('累计比例')
        aa[0].set_xlabel('单次决策墙钟 (ms)');aa[1].set_xlabel('每场决策95%分位数 (ms)');aa[0].legend(fontsize=6,ncol=2);save(fig,9,'决策计算开销',pdf)
        fig,aa=axes(2,15);aa=aa[0];case=int(cg.loc[cg.delta_s.idxmin(),'id'])
        for ax,m in zip(aa,['R12',candidate]):
            tr=loadtrace(cohort,m,case);pts=np.array([a['position'] for a in tr['actions'] if a['position'] is not None]);ax.plot(pts[:,0],pts[:,1],color=color(m),lw=.65,alpha=.8,label=lab(m));ax.add_patch(Circle((0,0),1800,fill=False,edgecolor='.3',lw=.7));nodes=np.array(tr['route_events'][0]['nodes']);ax.scatter(nodes[:,0],nodes[:,1],marker='s',s=12,facecolors='none',edgecolors='.4',label='保证节点');ax.scatter(pts[:,0],pts[:,1],c=np.arange(len(pts)),s=6,cmap='viridis',alpha=.6);ax.set_aspect('equal');ax.set_xlabel('横坐标 (m)');ax.set_ylabel('纵坐标 (m)');ax.legend(fontsize=7);ax.set_xlim(-2300,2300);ax.set_ylim(-2300,2300)
        save(fig,10,'候选与基线典型路径',pdf)
        fig,aa=axes(2,10);aa=aa[0];case=int(cg.loc[cg.delta_s.idxmax(),'id']);t=loadtrace(cohort,candidate,case);b=loadtrace(cohort,'R12',case)
        keys=['discovery','active_localization','diagnostic','optical_fallback','certified_clear'];labels=['发现','主动定位','诊断','光学回退','保证清除'];values=np.array([t['stages'][k]['total_s']-b['stages'][k]['total_s'] for k in keys]);starts=np.r_[0,np.cumsum(values)[:-1]]
        aa[0].bar(labels,values,bottom=starts,color=['#b64747' if x>0 else '#357f68' for x in values]);aa[0].axhline(0,color='.5',lw=.7);aa[0].set_ylabel('累计阶段耗时差 (s)')
        keys2=['travel_s','measure_s','switch_s','clear_s'];v=[sum(t['stages'][k][x]-b['stages'][k][x] for k in keys) for x in keys2];aa[1].bar(['移动','测量','换频','清除'],v,color=['#b64747' if x>0 else '#357f68' for x in v]);aa[1].axhline(0,color='.5',lw=.7);aa[1].set_ylabel('动作耗时差 (s)');save(fig,11,'最大回退的代价分解',pdf)
        fig,aa=axes(1,11);ax=aa[0,0];metrics=['improvement_pct','P95_change_pct','P99_change_pct','max_change_pct'];matrix=d.set_index('method').loc[methods,metrics].to_numpy();matrix[:,1:]*=-1;vmax=max(abs(matrix).max(),1);im=ax.imshow(matrix,cmap='RdBu',vmin=-vmax,vmax=vmax,aspect='auto');ax.set_yticks(range(len(methods)),[lab(m) for m in methods]);ax.set_xticks(range(4),['均值','95%分位','99%分位','最大值']);fig.colorbar(im,ax=ax,label='相对基线改善 (%)');save(fig,12,'单模块证据矩阵',pdf)
    (O/'PLOT_METADATA.json').write_text(json.dumps(dict(fonts=['Times New Roman','SimSun'],cohort_for_paths=cohort,candidate=candidate,path_best_case=int(cg.loc[cg.delta_s.idxmin(),'id']),path_worst_case=int(cg.loc[cg.delta_s.idxmax(),'id']),svg_text='editable; fonts required',samples='all, no clipping',interval='paired scene bootstrap 2000 replicates',official_calls=0),ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main()
