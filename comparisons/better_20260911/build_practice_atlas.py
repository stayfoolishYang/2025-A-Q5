"""Standalone MATLAB-style figures from frozen practice and local CPU evidence."""
import csv
import gzip
import hashlib
import html
import json
import re
import shutil
from collections import Counter
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import LogNorm
from matplotlib.patches import Circle
from matplotlib.backends.backend_pdf import PdfPages
from run_practice_matched import BASE, OUT as ROOT, SNAP, ROOTS

OUT=ROOT/'科学图谱'
GROUPS=['official','local','reference']
LABEL={'official':'官方演练','local':'本轮本地重跑','reference':'历史本地519'}
COLOR={'official':'#0072BD','local':'#D95319','reference':'#777777'}
STAGES=['discovery','active_localization','diagnostic','optical_fallback','certified_clear']
STAGE_NAMES=['发现','主动定位','诊断','光学兜底','保证清除']
EDGES=np.arange(-2600,2601,200)
plt.rcParams.update({'font.family':['Microsoft YaHei','DejaVu Sans'], 'axes.unicode_minus':False,
 'font.size':10,'axes.titlesize':12,'axes.labelsize':10,'figure.facecolor':'white',
 'axes.facecolor':'white','axes.grid':True,'grid.alpha':.17,'axes.linewidth':.8,
 'xtick.direction':'in','ytick.direction':'in','savefig.dpi':220,'pdf.fonttype':42,
 'svg.fonttype':'none','legend.frameon':False})
CAT=[]; TRACES={}; TARGETS={}; SOURCES={}; HASHES={}

def read(p):
    p=Path(p); b=p.read_bytes(); HASHES[str(p)]=hashlib.sha256(b).hexdigest()
    return json.loads(b)

def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')

def analyze(q,group,case,total,result,actions,truth=None,directional=None):
    pos=np.zeros(2); previous_time=0.; channel=1
    costs=np.zeros(4); distance=0.; events=[]; first={}; cleared={}; stages=Counter()
    max_movement_residual=0.; negatives=0; measures=0; failed=0
    for a in actions:
        response=a['response']; assert response.get('accepted') is True,(case,a)
        t=float(response['virtual_time_s'])
        if a['path'] not in ('/measure','/clear'):
            assert abs(t-previous_time)<1e-5
            continue
        req=a.get('request',a); p=req['position']
        p=np.array([p['x'],p['y']] if isinstance(p,dict) else p,float)
        c=req['channel']; d=float(np.linalg.norm(p-pos)); dt=t-previous_time
        measure=5. if a['path']=='/measure' else 0.
        switch=float(a['path']=='/measure' and c!=channel)
        clear=(5. if response['clear_result']=='success' else 3.) if a['path']=='/clear' else 0.
        move=dt-measure-switch-clear
        max_movement_residual=max(max_movement_residual,abs(move-d/5))
        assert abs(move-d/5)<2e-5,(case,move,d/5)
        assert move>=-1e-7
        costs+=np.array([move,measure,switch,clear]); distance+=d
        outcome=response.get('measure_result',response.get('clear_result'))
        if measure:
            channel=c; measures+=1; negatives+=int(outcome=='no_signal')
            if outcome in ('direction','near'):first.setdefault(c,(t,p.tolist()))
        else:
            if outcome=='success':
                assert c not in cleared
                cleared[c]=(t,p.tolist())
            else:failed+=1
        stage=a.get('stage')
        if stage is not None:stages[stage]+=dt
        events.append(dict(problem=q,group=group,case=case,action=len(events)+1,path=a['path'],
             channel=c,x=p[0],y=p[1],time=t,delta=dt,distance=d,move=move,measure=measure,
             switch=switch,clear=clear,outcome=outcome,stage=stage))
        pos=p; previous_time=t
    assert len(cleared)==len(first)==total,(case,len(cleared),len(first),total)
    T=float(result['virtual_time_s']); assert abs(T-sum(costs))<1e-5
    key=f'q{q}_{group}_{case}'
    if group!='reference':
        TRACES[key]=events
        TARGETS[key]=[dict(channel=c,first=t[0],clear=cleared[c][0],
            first_position=t[1],clear_position=cleared[c][1]) for c,t in first.items()]
        if truth is not None:SOURCES[key]=truth
    last=max(t[0] for t in first.values()); last_clear=max(t[0] for t in cleared.values())
    row=dict(problem=q,group=group,case=case,key=key,total=total,directional=directional,
       score=T/total,time=T,distance=distance,move=costs[0],measure=costs[1],switch=costs[2],clear=costs[3],
       measures=measures,negatives=negatives,negative_fraction=negatives/measures,
       clear_attempts=total+failed,failed_clears=failed,last_seen=last,last_clear=last_clear,
       after_discovery=last_clear-last,after_clear=T-last_clear,
       fallback=result.get('optical_fallbacks',result.get('fallback_count')),
       movement_residual_max_s=max_movement_residual)
    for stage in STAGES:row['stage_'+stage]=stages.get(stage,np.nan if group=='official' else 0.)
    if group!='official':assert abs(sum(stages.values())-T)<1e-5
    return row

def prepare():
    for d in ['png','pdf','svg','data','evidence']:(OUT/d).mkdir(parents=True,exist_ok=True)
    rows=[]; sessions=read(SNAP/'sessions.json')
    for r in sessions:
        q=r['problem']; p=BASE/'official_latest'/f'q{q}_{r["case"]}'
        assert read(p/'resident_verification.json')==r and r['status']=='FULL_CLEAR'
        manifest=read(p/'manifest.json')
        expected='79766ecf0d2577289f814edba310327f55424111' if q==3 else '7228633906262bb035f4ea1d859792e9f4484d20'
        assert manifest['commit']==expected
        result=read(p/'result.json'); wire=(p/'wire.jsonl').read_bytes()
        HASHES[str(p/'wire.jsonl')]=hashlib.sha256(wire).hexdigest()
        acts=[json.loads(line) for line in wire.splitlines() if line.strip()]
        after=(p/'after.txt').read_text(encoding='utf-8-sig')
        found=re.search(r'共\s*(\d+)\s*个[，,]\s*全向\s*(\d+)\s*个[，,]\s*定向\s*(\d+)\s*个',after)
        assert found and int(found[1])==r['total']
        row=analyze(q,'official',r['case'],r['total'],result,acts,directional=int(found[3]))
        assert abs(row['score']-r['score'])<1e-8
        rows.append(row)
    for q in (3,4):
        for group in ['local','reference']:
            root=ROOT/f'local_q{q}' if group=='local' else ROOTS[q]/'cpu519'
            selected=read(root/'PLAN.json')['selected'] if group=='local' else list(range(519))
            if group=='local':
                completion=read(root/'COMPLETION.json')
                assert completion['full_clear']==completion['audited']==len(selected)
                shutil.copy2(root/'COMPLETION.json',OUT/'evidence'/f'q{q}_local_completion.json')
                shutil.copy2(root/'PLAN.json',OUT/'evidence'/f'q{q}_local_plan.json')
            for seed in selected:
                rel=Path('runs')/f'q3_{seed:04d}_D' if q==3 else Path('core/rows')/f'R12_{seed:04d}'
                result=read(root/(str(rel)+'.json'))
                assert result.get('status',result.get('run_status'))=='FULL_CLEAR'
                assert result.get('audit',result.get('audit_passed')) is True
                trace=root/(str(rel)+'.json.gz') if q==3 else root/'core/traces'/f'R12_{seed:04d}.json.gz'
                with gzip.open(trace,'rt',encoding='utf-8') as f:raw=json.load(f)
                acts=raw if q==3 else raw['actions']
                scene=read(root/'scenes'/f'q{q}_{seed:04d}.json')['jammers']
                truth=[dict(channel=j['channel'],x=j['x_um']/1e6,y=j['y_um']/1e6,kind=j['kind']) for j in scene]
                rows.append(analyze(q,group,str(seed),len(scene),result,acts,truth,
                    sum(j['kind']=='directional' for j in scene)))
            print('Loaded',q,group,len(selected),flush=True)
    df=pd.DataFrame(rows)
    df['normalized_score']=df.score/df.groupby(['problem','group']).score.transform('mean')
    df.to_csv(OUT/'data/cases.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame([e for a in TRACES.values() for e in a]).to_csv(OUT/'data/actions.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame([dict(key=k,**r) for k,v in TARGETS.items() for r in v]).to_csv(OUT/'data/targets.csv',index=False,encoding='utf-8-sig')
    save(OUT/'data/traces.json',TRACES);save(OUT/'data/local_truth.json',SOURCES)
    save(OUT/'data/targets.json',TARGETS)
    return df

def sub(df,q,g):return df[(df.problem==q)&(df.group==g)]
def summarize(df):
    output={}; simulations={}; rng=np.random.default_rng(20260911)
    for q in (3,4):
        output[str(q)]={}
        for g in GROUPS:
            a=sub(df,q,g); x=a.score.to_numpy()
            output[str(q)][g]=dict(n=len(x),full_clear=len(x),mean=float(x.mean()),
                median=float(np.median(x)),p95=float(np.quantile(x,.95)),maximum=float(x.max()),
                normalized_variance=float(np.var(x/x.mean(),ddof=1)),cv=float(np.std(x/x.mean(),ddof=1)),
                total_sources=int(a.total.sum()),directional_fraction=float(a.directional.sum()/a.total.sum()),
                mean_distance_per_source_m=float((a.distance/a.total).mean()))
        official=sub(df,q,'official'); ref=sub(df,q,'reference')
        ncounts=Counter(official.total); samples=[]
        for _ in range(5000):
            samples.append(np.concatenate([rng.choice(ref[ref.total==n].score.to_numpy(),size=count,replace=False) for n,count in sorted(ncounts.items())]))
        x=np.array(samples); means=x.mean(1); variances=np.var(x/means[:,None],axis=1,ddof=1)
        simulations[q]=dict(mean=means,variance=variances)
        for name,arr in simulations[q].items():
            output[str(q)]['reference_resampling_'+name]=dict(iterations=5000,
                lower=float(np.quantile(arr,.025)),median=float(np.median(arr)),upper=float(np.quantile(arr,.975)),
                interpretation='2.5–97.5% empirical range of N-matched subsets of fixed519; not population CI')
        assert Counter(sub(df,q,'local').total)==ncounts
    save(OUT/'SUMMARY.json',output)
    np.savez_compressed(OUT/'data/reference_resampling.npz',**{f'q{q}_{k}':v for q,d in simulations.items() for k,v in d.items()})
    return output,simulations

def layout():return plt.subplots(1,2,figsize=(13.8,5.8),layout='constrained')
def finish(fig,title,question,reading,limit,source='data/cases.csv'):
    stem=f'{len(CAT)+1:02d}'
    fig.get_layout_engine().set(rect=(0,.055,1,.94))
    fig.suptitle(f'{stem}  {title}',fontsize=16)
    fig.text(.015,.012,'冻结 Q3 D / Q4 R12  |  官方仅演练  |  本地同源数匹配，非同场景配对  |  2026-09-11',fontsize=9,color='#555555')
    for ext in ['png','pdf','svg']:fig.savefig(OUT/ext/f'{stem}.{ext}',bbox_inches='tight')
    BOOK.savefig(fig,bbox_inches='tight');plt.close(fig)
    CAT.append(dict(id=stem,title=title,question=question,reading=reading,limit=limit,source=source))
    print('Figure',stem,title,flush=True)

def circular(ax):
    ax.add_patch(Circle((0,0),1800,fill=False,color='#222222',lw=1.3,ls='--'))
    ax.set(xlim=(-2600,2600),ylim=(-2600,2600),xlabel='x / m',ylabel='y / m')
    ax.set_aspect('equal');ax.plot(0,0,'+',color='black',ms=9)

def aggregates(df,summary,sims):
    fig,axs=layout()
    for ax,q in zip(axs,(3,4)):
        for g in GROUPS:
            x=np.sort(sub(df,q,g).score);ax.step(x,np.arange(1,len(x)+1)/len(x),where='post',label=f'{LABEL[g]} n={len(x)}',color=COLOR[g],ls='--' if g=='reference' else '-')
        ax.set(title=f'Q{q} 成绩经验分布',xlabel='虚拟时间 / 秒每源',ylabel='累计案例比例');ax.legend()
    finish(fig,'绝对成绩与完整尾部','当前官方成绩是否处在本地同一量级？','曲线越靠左表示该样本整体较快；尾部保留至最大值，避免只看平均数。','不同场景，不能据此宣称策略改进或模拟器偏差。')
    fig,axs=layout();rng=np.random.default_rng(3)
    for ax,q in zip(axs,(3,4)):
        for i,g in enumerate(GROUPS):
            x=sub(df,q,g).normalized_score.to_numpy()
            ax.boxplot([x],positions=[i],widths=.5,showfliers=False,medianprops=dict(color='black'))
            ax.scatter(i+rng.uniform(-.17,.17,len(x)),x,s=13 if g!='reference' else 5,alpha=.65 if g!='reference' else .2,color=COLOR[g])
            ax.text(i,ax.get_ylim()[1],f'Var={np.var(x,ddof=1):.4f}',ha='center',va='bottom',fontsize=9)
        ax.axhline(1,color='#333333',ls='--');ax.set(title=f'Q{q} 组内归一化',xticks=range(3),xticklabels=[LABEL[g] for g in GROUPS],ylabel='z = 每局秒/源 ÷ 本组均值');ax.margins(y=.13)
    finish(fig,'归一化波动与全部案例','排除量纲后，离散程度有多大？','箱线为中位数和四分位；点为每局；方差使用n−1分母。','各组独立除以自身均值，均值被强制为1，不能用此图比较绝对效率。')
    for metric,title in [('mean','均值'),('variance','归一化方差')]:
        fig,axs=layout()
        for ax,q in zip(axs,(3,4)):
            x=sims[q][metric];ax.hist(x,bins=32,color='#BBBBBB',edgecolor='white',density=True,label='固定库等量子集')
            for g in ['official','local']:
                value=summary[str(q)][g]['mean' if metric=='mean' else 'normalized_variance']
                ax.axvline(value,color=COLOR[g],lw=2,label=f'{LABEL[g]} {value:.4f}')
            lo,hi=np.quantile(x,[.025,.975]);ax.axvspan(lo,hi,color='#0072BD',alpha=.07,label='子集95%经验范围')
            ax.set(title=f'Q{q}：按官方源数构成抽取5000次',xlabel='秒/源' if metric=='mean' else '无量纲样本方差',ylabel='经验密度');ax.legend(fontsize=9)
        finish(fig,f'同样本量的{title}参照范围',f'少量场次的{title}能在固定本地库中波动多少？','每次按官方N结构从519库无放回抽取同样多案例；展示5000个子集的统计量。','这是固定库的子集分布，不是独立新增跑测，也不是官方总体置信区间。','data/reference_resampling.npz')
    fig,axs=layout()
    for ax,q in zip(axs,(3,4)):
        for i,g in enumerate(GROUPS):
            a=sub(df,q,g);counts=a.total.value_counts().reindex(range(10,17),fill_value=0)
            ax.bar(np.arange(7)+(i-1)*.25,counts/len(a),width=.24,color=COLOR[g],label=f'{LABEL[g]} n={len(a)}')
        ax.set(title=f'Q{q} 源数量构成',xticks=range(7),xticklabels=range(10,17),xlabel='每局源数 N',ylabel='案例占比');ax.legend()
    finish(fig,'源数匹配检查','两批小样本的源数构成是否相同？','蓝橙柱逐项相等是本轮匹配成立的直接证据；灰柱展示519库原始构成。','只匹配N，不保证坐标、方向比例、接收半径或噪声难度匹配。')
    fig,axs=layout()
    for ax,q in zip(axs,(3,4)):
        for off,g in [(-.12,'official'),(.12,'local')]:
            a=sub(df,q,g);ax.scatter(a.total+off,a.score,label=LABEL[g],c=COLOR[g],s=30,alpha=.65)
        ref=sub(df,q,'reference').groupby('total').score
        ax.plot(ref.mean().index,ref.mean(),color=COLOR['reference'],marker='s',ls='--',label='历史库组均值')
        n=Counter(sub(df,q,'official').total);ax.set(title=f'Q{q} 源数分层',xticks=range(10,17),xticklabels=[f'{i}\nn={n[i]}' for i in range(10,17)],xlabel='N；n为每个小样本组案例数',ylabel='秒/源');ax.legend()
    finish(fig,'源数分层的逐局表现','总体差异是否可能来自固定扫描成本的摊薄？','同一N内看蓝橙散点和历史库均值；不是把N当作完整难度指标。','部分N仅少量场次；不拟合高阶曲线或做分层显著性断言。')
    for q in (3,4):
        fig,axs=layout();x=sub(df,q,'official').score.to_numpy();n=np.arange(1,len(x)+1)
        axs[0].plot(n,x,'o',alpha=.35,color=COLOR['official'],label='单场');axs[0].plot(n,np.cumsum(x)/n,color=COLOR['official'],lw=2,label='累计均值')
        axs[0].axhline(summary[str(q)]['reference']['mean'],color='#777777',ls='--',label='历史519均值')
        axs[0].set(xlabel='官方接入顺序',ylabel='秒/源',title='均值随样本累计');axs[0].legend()
        v=[np.var(x[:i]/x[:i].mean(),ddof=1) for i in n[1:]];axs[1].plot(n[1:],v,'-o',color=COLOR['official'])
        axs[1].set(xlabel='已完成场数',ylabel='归一化样本方差',title=f'每个前缀单独归一化；最终 {v[-1]:.6f}')
        finish(fig,f'Q{q} 样本累计与波动估计','只看早期几场是否容易误判？','左图显示单场与累计均值；右图对每个前缀重新计算z和方差，首场不计算。','顺序是接入顺序，不是算法学习过程；曲线变平不等于统计保证。')
    fig,axs=layout();costs=['move','measure','switch','clear'];colors=['#0072BD','#EDB120','#7E2F8E','#77AC30']
    for ax,q in zip(axs,(3,4)):
        bottom=np.zeros(3)
        for k,c,label in zip(costs,colors,['移动','测量','切频','清除']):
            y=np.array([(sub(df,q,g)[k]/sub(df,q,g).total).mean() for g in GROUPS]);ax.bar(range(3),y,bottom=bottom,color=c,label=label);bottom+=y
        for i,t in enumerate(bottom):ax.text(i,t+5,f'{t:.2f}',ha='center')
        ax.set(title=f'Q{q} 可加动作账本',xticks=range(3),xticklabels=[LABEL[g] for g in GROUPS],ylabel='平均秒/源');ax.legend()
    finish(fig,'总时间到底花在哪里','两边时间差主要表现为哪种动作成本？','四项严格相加为每局秒/源再取平均；移动按官方虚拟时间差扣除动作成本并用距离/5交叉核验。','这是动作账本，不能把移动全称为发现阶段。')
    for field,xlabel,title in [('distance','路径长度 / m每源','路径长度与完成时间'),('negative_fraction','无信号次数 / 全部测量次数','无信号观测负担')]:
        fig,axs=layout()
        for ax,q in zip(axs,(3,4)):
            for g in reversed(GROUPS):
                a=sub(df,q,g);xx=a[field]/a.total if field=='distance' else a[field]
                ax.scatter(xx,a.score,label=LABEL[g],c=COLOR[g],s=30 if g!='reference' else 8,alpha=.65 if g!='reference' else .17,marker='o' if g!='local' else '^')
            ax.set(title=f'Q{q}',xlabel=xlabel,ylabel='秒/源');ax.legend()
        finish(fig,title,'哪些可观测成本伴随慢例？','每点是一局；灰色为历史库背景，蓝橙为两批同量级样本。','路程与时间存在机械关系；无信号比例不是漏检率，也不能单独证明策略失效。')
    fig,axs=layout()
    for ax,q in zip(axs,(3,4)):
        bottom=np.zeros(3)
        for k,c,label in zip(['last_seen','after_discovery','after_clear'],['#0072BD','#D95319','#7E2F8E'],['最后首次接收前','随后至最后清除','全清后到退出']):
            y=np.array([(sub(df,q,g)[k]/sub(df,q,g).total).mean() for g in GROUPS]);ax.bar(range(3),y,bottom=bottom,color=c,label=label);bottom+=y
        ax.set(title=f'Q{q} 三个互斥时间区间',xticks=range(3),xticklabels=[LABEL[g] for g in GROUPS],ylabel='平均秒/源');ax.legend()
    finish(fig,'最后发现、最后清除与退出','瓶颈发生在何种任务里程碑之前或之后？','由每个实际成功频道的第一次direction/near与成功clear重建；三段覆盖整个虚拟时间。','第一段可能包含其他源的定位和清除，不能等同算法discovery阶段。')
    fig,axs=layout();grid=np.linspace(0,1,101)
    for ax,q in zip(axs,(3,4)):
        for g in ['official','local']:
            curves=[]
            for _,r in sub(df,q,g).iterrows():
                times=sorted(t['clear'] for t in TARGETS[r.key]);curves.append(np.searchsorted(times,grid*r.time,side='right')/r.total)
            curves=np.array(curves);ax.plot(grid,np.median(curves,axis=0),color=COLOR[g],label=LABEL[g]);ax.fill_between(grid,np.quantile(curves,.25,axis=0),np.quantile(curves,.75,axis=0),color=COLOR[g],alpha=.13)
        ax.set(title=f'Q{q} 中位数与案例四分位带',xlabel='已耗虚拟时间 / 本局最终时间',ylabel='已清除源数 / 本局总源数');ax.legend()
    finish(fig,'清除进度形态','慢局是清除推进慢，还是清除后仍有扫描？','按各局最终时间归一化，对齐任务进程；曲线提前到1反映退出前已全清。','时间归一化抹去了绝对快慢；阴影为案例IQR，不是置信带。','data/targets.csv')

def spatial(df):
    grids={}
    def hist(p,w=None):
        if not len(p):return np.zeros((len(EDGES)-1,len(EDGES)-1))
        p=np.asarray(p);assert np.max(np.abs(p))<EDGES[-1]
        return np.histogram2d(p[:,0],p[:,1],bins=(EDGES,EDGES),weights=w)[0]
    for q in (3,4):
        for g in ['official','local']:
            mp=[];negative=[];tp=[];tw=[]
            for _,r in sub(df,q,g).iterrows():
                pos=np.zeros(2)
                for a in TRACES[r.key]:
                    p=np.array([a['x'],a['y']]);d=a['distance']
                    if a['path']=='/measure':
                        mp.append(p)
                        if a['outcome']=='no_signal':negative.append(p)
                    if d>0:
                        n=max(1,int(np.ceil(d/50)))
                        tp.extend(pos+(np.arange(n)[:,None]+.5)/n*(p-pos));tw.extend([d/n]*n)
                    pos=p
            n=len(sub(df,q,g));travel=hist(tp,tw)
            assert abs(travel.sum()-sub(df,q,g).distance.sum())<1e-5
            grids[q,g]=dict(measure=hist(mp),negative=hist(negative),travel=travel,n=n)
    np.savez_compressed(OUT/'data/spatial_grids.npz',edges=EDGES,**{f'q{q}_{g}_{k}':v for (q,g),d in grids.items() for k,v in d.items()})
    for kind,title in [('measure','测量位置强度'),('negative','格内无信号占比'),('travel','移动路径空间负担')]:
        for q in (3,4):
            fig,axs=layout();maps=[]
            for g in ['official','local']:
                d=grids[q,g]
                if kind=='negative':
                    a=np.divide(d['negative'],d['measure'],out=np.zeros_like(d['measure']),where=d['measure']>0)
                    a=np.ma.masked_where(d['measure']<5,a)
                else:a=np.ma.masked_where(d[kind]==0,d[kind]/d['n'])
                maps.append(a)
            vmax=max(float(a.max()) for a in maps)
            for ax,g,a in zip(axs,['official','local'],maps):
                norm=LogNorm(vmin=min(float(x.min()) for x in maps),vmax=vmax) if kind!='negative' else None
                im=ax.pcolormesh(EDGES,EDGES,a.T,cmap='viridis',norm=norm,vmin=0 if kind=='negative' else None,vmax=1 if kind=='negative' else None,shading='flat')
                circular(ax);ax.set_title(f'{LABEL[g]} n={len(sub(df,q,g))}')
                fig.colorbar(im,ax=ax,shrink=.8,label={'measure':'测量次数 / 局 / 网格（对数色标）','negative':'无信号 / 测量（≥5次）','travel':'米 / 局 / 网格（对数色标）'}[kind])
            finish(fig,f'Q{q} 圆域{title}','空间上的高负担区域在哪里？',
                '两图统一200m网格与色标；虚线是真实任务圆域R=1800m，显示圆外机器人动作。'+('路径按不超过50m的分段中点累积，所有网格长度与实际总路程核对相等。' if kind=='travel' else '次数强度按每局平均。' if kind=='measure' else '每格分母是该格全部测量次数；低于5次留白。'),
                '颜色表示机器人行为，不能当作干扰源密度。无信号比例只在已访问测点上成立；留白不是零风险。','data/spatial_grids.npz; data/actions.csv')
    fig,axs=layout()
    for ax,q in zip(axs,(3,4)):
        p=[];colors=[]
        for _,r in sub(df,q,'official').iterrows():
            for t in TARGETS[r.key]:p.append(t['first_position']);colors.append(t['first']/r.time)
        p=np.array(p);im=ax.scatter(p[:,0],p[:,1],c=colors,cmap='viridis',vmin=0,vmax=1,s=24,alpha=.7)
        circular(ax);ax.set_title(f'Q{q} 官方首次成功接收测点 · {len(p)}个源');fig.colorbar(im,ax=ax,shrink=.8,label='首次接收时刻 / 本局完成时间')
    finish(fig,'首次发现发生在哪些测点','哪个位置承担了较晚的首次发现？','每个成功清除频道只取第一次direction/near测点；颜色是相对完成时间，点重合说明共同扫描站位。','点是机器人接收位置，不是干扰源坐标；重叠点数量需结合动作CSV。','data/targets.csv')

def local_diagnostics(df):
    fig,axs=layout()
    for ax,q in zip(axs,(3,4)):
        bottom=np.zeros(2)
        for stage,label,c in zip(STAGES,STAGE_NAMES,['#0072BD','#D95319','#EDB120','#7E2F8E','#77AC30']):
            y=np.array([(sub(df,q,g)['stage_'+stage]/sub(df,q,g).total).mean() for g in ['local','reference']]);ax.bar(range(2),y,bottom=bottom,label=label,color=c);bottom+=y
        ax.set(title=f'Q{q} 仅本地可靠stage标签',xticks=[0,1],xticklabels=['本轮本地','历史519'],ylabel='平均秒/源');ax.legend()
    finish(fig,'本地算法阶段账本','本地真正的discovery负担占多少？','直接使用求解器记录的互斥stage累计时间，审核所有阶段相加等于整局时间。','官方无线日志没有stage字段，不外推为官方阶段百分比。')
    fig,axs=layout();bins=np.linspace(0,1,6)
    for g in GROUPS:
        a=sub(df,4,g);frac=a.directional/a.total
        axs[0].hist(frac,bins=bins,weights=np.ones(len(a))/len(a),histtype='step',lw=2,color=COLOR[g],label=LABEL[g])
        axs[1].scatter(frac,a.score,s=28 if g!='reference' else 8,alpha=.6 if g!='reference' else .18,color=COLOR[g],label=LABEL[g],marker='^' if g=='local' else 'o')
    axs[0].set(xlabel='定向源 / 全部源',ylabel='案例占比',title='Q4 定向比例构成');axs[0].legend()
    axs[1].set(xlabel='定向源 / 全部源',ylabel='秒/源',title='Q4 定向比例与成绩');axs[1].legend()
    finish(fig,'Q4方向构成是剩余混杂因素','仅匹配源数是否已足够？','官方定向数量取结束界面；本地取场景文件。左图比较构成，右图展示个体差异。','类型数量不是在线策略额外输入；本轮没有匹配接收半径、几何布局或定向比例。')
    fig,axs=layout()
    for ax,q in zip(axs,(3,4)):
        a=sub(df,q,'local').merge(sub(df,q,'reference'),on='case',suffixes=('_new','_old'))
        delta=a.time_new-a.time_old
        ax.stem(a.case.astype(int),delta,linefmt='C0-',markerfmt='C0o',basefmt='k-')
        ax.set(title=f'Q{q} {len(a)}场；最大绝对差 {abs(delta).max():.6f}s',xlabel='原库seed编号',ylabel='新运行−历史总虚拟时间 / s',ylim=(-1,1))
    finish(fig,'本轮重跑的确定性复现','本地此次执行是否复现历史同策略？','逐seed比较相同冻结源码、场景与CPU后端的总虚拟时间。','零差验证复现，不证明本地引擎与官方在任意场景完全等价。')

def case_figures(df):
    for q in (3,4):
        for g in ['official','local']:
            a=sub(df,q,g).sort_values(['score','case']).reset_index(drop=True)
            for name,index in [('最快',0),('中位附近',len(a)//2),('最慢',len(a)-1)]:
                r=a.iloc[index];events=TRACES[r.key];targets=sorted(TARGETS[r.key],key=lambda x:x['first'])
                fig,axs=layout();ax=axs[0]
                p=np.array([[0.,0.]]+[[e['x'],e['y']] for e in events]);times=np.array([e['time']/r.time for e in events])
                seg=np.stack([p[:-1],p[1:]],axis=1);lc=LineCollection(seg,cmap='viridis',norm=plt.Normalize(0,1),linewidth=1.1,alpha=.8);lc.set_array(times);ax.add_collection(lc)
                m=[e for e in events if e['path']=='/measure'];ax.scatter([e['x'] for e in m],[e['y'] for e in m],s=10,c='#777777',alpha=.4,label='测量点')
                cp=np.array([t['clear_position'] for t in targets]);ax.scatter(cp[:,0],cp[:,1],marker='x',s=45,c='#D95319',label='成功清除点')
                for t in targets:ax.annotate(str(t['channel']),t['clear_position'],xytext=(4,3),textcoords='offset points',fontsize=8,color='#994015')
                if r.key in SOURCES:
                    truth=SOURCES[r.key];ax.scatter([t['x'] for t in truth],[t['y'] for t in truth],marker='o',s=45,facecolors='none',edgecolors='black',lw=.8,label='本地真值（事后）')
                circular(ax);ax.legend(loc='lower left',fontsize=8);ax.set_title(f'圆域轨迹：{r.distance/1000:.2f} km，{int(r.measures)}次测量')
                fig.colorbar(lc,ax=ax,shrink=.75,label='动作完成时间 / 本局时间')
                ax=axs[1]
                for j,t in enumerate(targets):
                    ax.plot([t['first'],t['clear']],[j,j],color=COLOR[g],lw=2)
                    ax.scatter(t['first'],j,marker='o',s=23,c=COLOR[g]);ax.scatter(t['clear'],j,marker='x',s=32,c='#D95319')
                ax.axvline(r.time,color='#333333',ls='--',label='退出')
                ax.set(yticks=range(len(targets)),yticklabels=[f'频道{t["channel"]}' for t in targets],xlabel='虚拟时间 / s',title=f'首次接收○ → 成功清除×；N={r.total}')
                ax.legend();ax.invert_yaxis()
                finish(fig,f'Q{q} {LABEL[g]}{name}案例：{r.case}',
                    '具体路径如何形成该局成绩？',
                    f'该局{r.score:.3f}秒/源，{r.time:.3f}秒，{r.distance/1000:.3f}km；无信号{int(r.negatives)}/{int(r.measures)}。轨迹颜色随虚拟时间推进；时间线按首次接收排序，长度包含等待调度及后续定位。',
                    '最快/中位附近/最慢按本批成绩预定规则选取，非随机代表；直线段只连接指令目标点。官方清除点不是精确源坐标，时间线长度也不是纯定位计算时间。',
                    f'data/traces.json → {r.key}; data/targets.json')

def deliver(df,summary):
    save(OUT/'CATALOG.json',CAT)
    md='# 官方演练与本地恢复案例对照图谱\n\n'
    md+='本轮新增本地CPU重跑57场：Q3 D 30场，Q4 R12 27场，全部全清并通过审计；逐场虚拟时间与旧库同seed一致。官方为前一轮固定快照57场，本轮未调用官方接口。历史519/题仅为已有背景数据。\n\n'
    md+='|题目|数据组|场数|平均秒/源|P95|最大值|归一化样本方差|CV|\n|---|---|---:|---:|---:|---:|---:|---:|\n'
    for q in (3,4):
        for g in GROUPS:
            r=summary[str(q)][g];md+=f'|Q{q}|{LABEL[g]}|{r["n"]}|{r["mean"]:.3f}|{r["p95"]:.3f}|{r["maximum"]:.3f}|{r["normalized_variance"]:.6f}|{r["cv"]:.2%}|\n'
    md+='\n归一化：每局x=T/N，分题、分数据组计算z=x/mean(x)，样本方差使用n−1分母；不是z-score标准化，不把方差强制为1。每局等权，不能与总时间/总源数混用。\n\n'
    for q in (3,4):
        a,b=summary[str(q)]['official'],summary[str(q)]['local'];rg=summary[str(q)]['reference_resampling_mean']
        md+=f'Q{q}：官方与本轮本地均值差为{a["mean"]-b["mean"]:+.3f}秒/源（相对本地{a["mean"]/b["mean"]-1:+.2%}）。固定519库按官方N构成等量抽取5000次，均值中央95%经验范围为[{rg["lower"]:.3f}, {rg["upper"]:.3f}]秒/源；官方均值'+('在' if rg['lower']<=a['mean']<=rg['upper'] else '不在')+'这个范围内。该范围仅描述固定回归库的子集，不是官方总体置信区间。\n\n'
    md+='限制：N匹配但不配对同一场景；定向比例、几何和噪声未完全匹配。既有519是结构化回归种子族，不是IID总体样本。无法从本对照证明官方引擎有偏差或算法有改进。官方没有真实位置与stage标签；空间图表示机器人行为，阶段图只用本地。\n\n'
    md+='数据核验：所有接收动作均accepted；逐局清除唯一频道数等于已公布源数；四项动作成本与总时间相等；每动作移动耗时与距离/5最大残差小于0.00002秒；本地stage合计核对；热力图路径长度守恒；两批小样本N直方图一致。\n\n'
    md+='图包：35张主图，全部PNG/PDF/SVG；合订PDF；CSV原始数值；去掉队号/请求标识的动作记录；逐源里程碑；网格数据及5000次子集统计。\n'
    (OUT/'阅读指南.md').write_text(md,encoding='utf-8')
    notes='# 逐图分析意义与读取说明\n\n'
    for c in CAT:
        notes+=f'## {c["id"]} {c["title"]}\n\n问题：{c["question"]}\n\n读法与实测信息：{c["reading"]}\n\n边界：{c["limit"]}\n\n数据：{c["source"]}\n\n![图{c["id"]}](png/{c["id"]}.png)\n\n'
    (OUT/'逐图详解.md').write_text(notes,encoding='utf-8')
    # Static image contact sheet; no dashboard runtime or remote dependencies.
    cards=''.join(f'<section id="f{c["id"]}"><h2>{c["id"]} {html.escape(c["title"])}</h2><img loading="lazy" src="png/{c["id"]}.png" alt="{html.escape(c["title"])}"><p><b>问题：</b>{html.escape(c["question"])}</p><p>{html.escape(c["reading"])}</p><p class="note">{html.escape(c["limit"])}</p><a href="svg/{c["id"]}.svg">SVG</a> · <a href="pdf/{c["id"]}.pdf">PDF</a> · <a href="png/{c["id"]}.png">PNG</a><p class="note">数据：{html.escape(c["source"])}</p></section>' for c in CAT)
    nav=''.join(f'<a href="#f{c["id"]}">{c["id"]} {html.escape(c["title"])}</a>' for c in CAT)
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>官方演练 × 本地恢复案例 图谱</title><style>body{font:16px/1.7 "Microsoft YaHei",sans-serif;color:#20252a;background:#f5f6f8;margin:0}header,main{max-width:1200px;margin:auto;padding:24px}header{border-bottom:3px solid #0072bd}section{background:white;padding:24px;margin:24px 0}img{width:100%;height:auto}a{color:#0072bd}nav{columns:2;font-size:14px}nav a{display:block;margin:6px 0}.note{color:#656a70;font-size:14px}h1{font-size:28px}h2{font-size:21px}@media(max-width:700px){nav{columns:1}header,main,section{padding:12px}}</style><header><h1>官方演练 × 本地恢复案例</h1><p>Q3 D / Q4 R12 · 官方30/27场 · 新增本地30/27场 · 519/题历史背景</p><p>35张 MATLAB 风格独立科研图；每图附解释与证据。不同场景对照，非同种子算法A/B。</p><p><a href="图谱合订.pdf">合订PDF</a> · <a href="阅读指南.md">统计报告</a> · <a href="data/cases.csv">逐局数据</a></p><nav>'+nav+'</nav></header><main>'+cards+'</main></html>'
    (OUT/'index.html').write_text(page,encoding='utf-8')
    shutil.copy2(Path(__file__).with_name('PRACTICE_ATLAS_PLAN.md'),OUT/'图表设计.md')
    shutil.copy2(Path(__file__),OUT/'evidence'/Path(__file__).name)
    shutil.copy2(Path(__file__).with_name('run_practice_matched.py'),OUT/'evidence/run_practice_matched.py')
    save(OUT/'SOURCE_HASHES.json',HASHES)
    save(OUT/'VALIDATION.json',dict(figures=len(CAT),case_rows=len(df),fresh_local_runs=57,
        official_snapshot_rows=57,previous_reference_rows=1038,official_calls_this_task=0,
        normalized_variance_ddof=1,movement_residual_max_s=float(df.movement_residual_max_s.max()),
        unique_cases=not df.duplicated(['problem','group','case']).any(),notes='Full-clear, additive accounting, stage totals, spatial mass, N matching asserted in builder'))
    print(json.dumps(summary,ensure_ascii=False),flush=True)

def main():
    global BOOK
    df=prepare();summary,sims=summarize(df)
    with PdfPages(OUT/'图谱合订.pdf') as BOOK:
        aggregates(df,summary,sims);spatial(df);local_diagnostics(df);case_figures(df)
    assert len(CAT)==35,len(CAT)
    deliver(df,summary)

if __name__=='__main__':main()
