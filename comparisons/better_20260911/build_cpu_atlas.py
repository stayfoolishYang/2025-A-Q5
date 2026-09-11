"""Source-backed MATLAB-style scientific atlas; reads CPU results only."""
import csv,gzip,hashlib,json,math
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm,TwoSlopeNorm
from matplotlib.collections import LineCollection
from matplotlib.patches import Circle
from matplotlib.backends.backend_pdf import PdfPages

DATA=Path('J:/2026B_runs/better_full519_20260911')
OUT=Path('J:/2026B_runs/CPU_519_科学图谱')
GROUPS=[(3,'A'),(3,'B'),(4,'A'),(4,'B'),(4,'C')]
COL={'A':'#0072BD','B':'#D95319','C':'#77AC30'}
NAMES={(3,'A'):'Q3 A 原路线',(3,'B'):'Q3 B 路线刷新',(4,'A'):'Q4 A D1/45点',(4,'B'):'Q4 B 加16源退出',(4,'C'):'Q4 C 再改37点'}
EDGES=np.arange(-2600,2601,100)
plt.rcParams.update({'font.family':['Microsoft YaHei','DejaVu Sans'],'axes.unicode_minus':False,
    'font.size':10,'axes.titlesize':12,'axes.labelsize':10,'figure.facecolor':'white',
    'axes.facecolor':'white','axes.grid':True,'grid.alpha':.18,'axes.linewidth':.8,
    'xtick.direction':'in','ytick.direction':'in','savefig.dpi':200,'pdf.fonttype':42,'ps.fonttype':42})
catalog=[]

def trace(q,s,v):
    with gzip.open(DATA/'runs'/f'q{q}_{s:04d}_{v}.json.gz','rt',encoding='utf-8') as f:return json.load(f)
def hist(points,weights=None):
    p=np.asarray(points)
    return np.histogram2d(p[:,0],p[:,1],bins=(EDGES,EDGES),weights=weights)[0] if len(p) else np.zeros((52,52))
def prepare():
    OUT.mkdir(parents=True,exist_ok=True)
    for x in ('png','pdf','svg','data'):(OUT/x).mkdir(exist_ok=True)
    plan=json.loads((DATA/'PLAN.json').read_bytes());families={r['seed']:r['family'] for r in plan['seeds']}
    rows=[];spatial={g:{k:np.zeros((52,52)) for k in ('measure','negative','travel','first_sum','first_n')} for g in GROUPS}
    progress={g:[] for g in GROUPS};bins=np.linspace(0,1,101)
    for q,v in GROUPS:
        for seed in range(519):
            p=DATA/'runs'/f'q{q}_{seed:04d}_{v}.json';r=json.loads(p.read_bytes())
            assert r['status']=='FULL_CLEAR' and r['audit']
            scene=json.loads((DATA/'scenes'/f'q{q}_{seed:04d}.json').read_bytes());truth={x['channel']:x for x in scene['jammers']}
            a=trace(q,seed,v);pos=np.zeros(2);t0=0.;dist=0.;cost=np.zeros(4);nmeasure=nnegative=nclear=nswitch=0;first={};clear=[]
            mp=[];neg=[];travelp=[];travelw=[]
            for x in a:
                if x['path'] not in ('/measure','/clear'):continue
                p=np.array(x['position']);d=float(np.linalg.norm(p-pos));dist+=d
                # Midpoint quadrature at <=50m intervals; integrated mass equals segment length.
                n=max(1,int(np.ceil(d/50)))
                if d>0:
                    travelp.extend(pos+(np.arange(n)[:,None]+.5)/n*(p-pos));travelw.extend([d/n]*n)
                cost+=np.array([x['travel_s'],x['measure_s'],x['switch_s'],x['clear_s']]);pos=p
                if x['path']=='/measure':
                    nmeasure+=1;nswitch+=int(x['switch_s']);mp.append(p)
                    if x['response']['measure_result']=='no_signal':nnegative+=1;neg.append(p)
                    else:first.setdefault(x['channel'],x['response']['virtual_time_s'])
                else:
                    nclear+=1
                    if x['response']['clear_result']=='success':clear.append(x['response']['virtual_time_s'])
            assert len(first)==len(truth)==len(clear)==r['total']
            assert abs(sum(cost)-r['virtual_time_s'])<1e-5
            g=spatial[q,v];g['measure']+=hist(mp);g['negative']+=hist(neg);g['travel']+=hist(travelp,travelw)
            tp=[(truth[c]['x_um']/1e6,truth[c]['y_um']/1e6) for c in first]
            g['first_sum']+=hist(tp,list(first.values()));g['first_n']+=hist(tp)
            progress[q,v].append(np.searchsorted(sorted(clear),bins*r['virtual_time_s'],side='right')/len(clear))
            rows.append(dict(problem=q,variant=v,seed=seed,family=families[seed],total=r['total'],
                directional=sum(x['kind']=='directional' for x in truth.values()),score=r['mean_time_per_source_s'],
                time=r['virtual_time_s'],distance=dist,move=cost[0],measure=cost[1],switch=cost[2],clear=cost[3],
                measures=nmeasure,negatives=nnegative,clear_attempts=nclear,switches=nswitch,
                fallback=r['optical_fallbacks'],first=min(first.values()),last=max(first.values()),
                last_clear=max(clear),after_clear=r['virtual_time_s']-max(clear),after_discovery=r['virtual_time_s']-max(first.values())))
        print('Extracted',q,v,flush=True)
    df=pd.DataFrame(rows);df.to_csv(OUT/'data/case_features.csv',index=False,encoding='utf-8-sig')
    np.savez_compressed(OUT/'data/spatial_grids.npz',edges=EDGES,**{f'q{q}_{v}_{k}':x for (q,v),d in spatial.items() for k,x in d.items()})
    np.savez_compressed(OUT/'data/clearance_progress.npz',fraction=bins,**{f'q{q}_{v}':x for (q,v),x in progress.items()})
    return df,spatial,progress

def sub(df,q,v):return df[(df.problem==q)&(df.variant==v)].sort_values('seed').reset_index(drop=True)
def paired(df,q,ref,v):
    a=sub(df,q,ref);b=sub(df,q,v);assert a.seed.equals(b.seed)
    return a,b,b.score.to_numpy()-a.score.to_numpy()
def finish(fig,title,meaning,readout,limit,source='data/case_features.csv'):
    i=len(catalog)+1;stem=f'{i:02d}'
    fig.get_layout_engine().set(rect=(0,.035,1,.965))
    fig.suptitle(f'图 {i:02d}  {title}',fontsize=16)
    fig.text(.01,.007,'CPU · 固定519种子回归集 · 非官方成绩 · 同案例配对；负差值代表候选更快',fontsize=8,color='#555555')
    fig.savefig(OUT/'png'/f'{stem}.png',bbox_inches='tight');fig.savefig(OUT/'pdf'/f'{stem}.pdf',bbox_inches='tight');fig.savefig(OUT/'svg'/f'{stem}.svg',bbox_inches='tight')
    BOOK.savefig(fig,bbox_inches='tight');plt.close(fig)
    catalog.append(dict(id=stem,title=title,meaning=meaning,readout=readout,limit=limit,source=source))
    print('Figure',stem,title,flush=True)
def layout(rows=1,cols=2):return plt.subplots(rows,cols,figsize=(7*cols,4.5*rows),layout='constrained',squeeze=False)
def circular(ax,limit=2600):
    ax.add_patch(Circle((0,0),1800,fill=False,color='#222222',lw=1.3,ls='--'))
    ax.set(xlim=(-limit,limit),ylim=(-limit,limit),xlabel='x / m',ylabel='y / m');ax.set_aspect('equal')

def aggregate(df,spatial,progress):
    fig,axs=layout(2,2)
    for j,q in enumerate((3,4)):
        vs='AB' if q==3 else 'ABC'
        for v in vs:
            x=np.sort(sub(df,q,v).score);axs[0,j].plot(x,np.arange(1,520)/519,label=v,color=COL[v]);axs[1,j].plot(np.arange(1,520)/519,x,label=v,color=COL[v])
        axs[0,j].set(title=f'Q{q} 累积分布',xlabel='秒/源',ylabel='案例累积比例');axs[0,j].legend()
        axs[1,j].set(title=f'Q{q} 分位数曲线（完整尾部）',xlabel='分位数',ylabel='秒/源');axs[1,j].legend()
    finish(fig,'整体性能分布：主体与尾部同时保留','分离典型成绩与最慢案例，避免均值掩盖长尾。','Q3候选的主体左移，但最大值更高；Q4 C分布整体改善。','固定回归集经验分布，不是总体概率预测。')
    fig,axs=layout(1,3)
    for ax,(q,ref,v) in zip(axs[0],[(3,'A','B'),(4,'A','C'),(4,'B','C')]):
        a,b,d=paired(df,q,ref,v);im=ax.scatter(a.score,b.score,c=a.total,cmap='viridis',s=16,alpha=.65)
        lim=max(a.score.max(),b.score.max())*1.03;ax.plot([0,lim],[0,lim],'k--',lw=1);ax.set(xlabel=f'{ref} 秒/源',ylabel=f'{v} 秒/源',title=f'Q{q} {v} 对 {ref}\n胜/平/负={sum(d<-1e-8)}/{sum(abs(d)<=1e-8)}/{sum(d>1e-8)}');fig.colorbar(im,ax=ax,label='源数')
    finish(fig,'逐例配对散点：收益是否一致','每个点对应同一seed的两种算法，虚线下方表示候选更快。','Q4 C对A全部点在下方；C对B仍存在退步；Q3退步更分散。','颜色只标记源数，不表示场景难度的充分解释。')
    fig,axs=layout(1,3)
    for ax,(q,ref,v) in zip(axs[0],[(3,'A','B'),(4,'A','C'),(4,'B','C')]):
        a,b,d=paired(df,q,ref,v);d=np.sort(d);ax.fill_between(range(519),0,d,where=d<=0,color=COL['A'],alpha=.7);ax.fill_between(range(519),0,d,where=d>0,color=COL['B'],alpha=.8);ax.axhline(0,color='black',lw=.8);ax.set(title=f'Q{q} {v}−{ref}',xlabel='按配对差排序的案例秩',ylabel='Δ 秒/源')
    finish(fig,'完整配对差谱','同时呈现收益幅度、退步比例和极端退步，不只报告胜率。','Q3少量巨大正差会抵消许多中小幅节省。','横轴是排序秩，不是时间、seed数值或试验执行顺序。')
    fig,axs=layout(1,2)
    for ax,q in zip(axs[0],(3,4)):
        vs='AB' if q==3 else 'ABC';x=np.arange(len(vs));bottom=np.zeros(len(vs))
        for k,color in zip(['move','measure','switch','clear'],['#0072BD','#EDB120','#7E2F8E','#77AC30']):
            y=[sub(df,q,v)[k].mean() for v in vs];ax.bar(x,y,bottom=bottom,label={'move':'移动','measure':'测量','switch':'切频','clear':'清除'}[k],color=color);bottom+=y
        ax.set(xticks=x,xticklabels=list(vs),ylabel='平均每局耗时 / s',title=f'Q{q} 完整账本');ax.legend()
    finish(fig,'四类动作成本的可加分解','用严格可相加的成本定位主要节省来源，每局平均而不是每源平均。','移动通常占主要成本；切频和测量不能与移动重复计时。','原日志stage没有细分，故本图不声称发现/诊断/主动定位的互斥耗时。')
    fig,axs=layout(1,3)
    for ax,(q,ref,v) in zip(axs[0],[(3,'A','B'),(4,'A','B'),(4,'B','C')]):
        a,b,d=paired(df,q,ref,v);names=['move','measure','switch','clear'];y=[(b[k]-a[k]).mean() for k in names]
        ax.bar(['移动','测量','切频','清除'],y,color=[COL['A'] if t<=0 else COL['B'] for t in y]);ax.axhline(0,c='k',lw=.8);ax.set(title=f'Q{q} {v}−{ref}，合计{sum(y):.1f}s',ylabel='每局配对成本变化 / s')
        for i,t in enumerate(y):ax.annotate(f'{t:+.1f}',(i,t),xytext=(0,5 if t>=0 else -14),textcoords='offset points',ha='center')
    finish(fig,'收益来自哪种动作','动作成本变化合计严格等于整局时间变化，负柱为节省。','Q3清除成本可能上升；Q4节点减少主要影响移动与测量。','此为账本归因，不等于隔离因果机制的单因素实验。')
    fig,axs=layout(1,2)
    for ax,q in zip(axs[0],(3,4)):
        for v in ('AB' if q==3 else 'ABC'):
            g=sub(df,q,v).groupby('total').score;ax.plot(g.mean().index,g.mean(),'-o',label=v,color=COL[v]);ax.fill_between(g.mean().index,g.quantile(.25),g.quantile(.75),color=COL[v],alpha=.12)
        counts=sub(df,q,'A').groupby('total').size();ax.set(xticks=counts.index,xticklabels=[f'{n}\nn={counts[n]}' for n in counts.index],xlabel='源数与组内案例数',ylabel='秒/源：均值及四分位带',title=f'Q{q} 源数分层');ax.legend()
    finish(fig,'源数分层：归一化成绩的结构','展示不同源数的均值和组内离散度，识别固定覆盖成本的摊薄效应。','Q4 B只在16源组产生停止收益，不能推广到10–15源。','阴影为25%–75%案例分位范围，不是置信区间。')
    fig,axs=layout(1,2)
    for ax,(ref,v) in zip(axs[0],[('A','C'),('B','C')]):
        a,b,d=paired(df,4,ref,v);a=a.copy();a['delta']=d;a['fraction']=pd.cut(a.directional/a.total,[0,.25,.5,.75,1],include_lowest=True,labels=['≤25%','25–50%','50–75%','75–100%'])
        m=a.pivot_table(index='fraction',columns='total',values='delta',aggfunc='mean',observed=False);n=a.pivot_table(index='fraction',columns='total',values='delta',aggfunc='count',observed=False).fillna(0);bound=max(abs(m.min().min()),abs(m.max().max()));im=ax.imshow(m,cmap='coolwarm',vmin=-bound,vmax=bound,aspect='auto');ax.set(xticks=range(len(m.columns)),xticklabels=m.columns,yticks=range(len(m.index)),yticklabels=m.index,xlabel='源数',ylabel='定向源比例',title=f'Q4 {v}−{ref} 平均秒/源');fig.colorbar(im,ax=ax)
        for i in range(len(m)):
            for j in range(len(m.columns)):
                if n.iloc[i,j]:ax.text(j,i,f'{m.iloc[i,j]:.0f}\n(n={n.iloc[i,j]:.0f})',ha='center',va='center',fontsize=8)
    finish(fig,'源数×定向比例的收益矩阵','二维分层揭示均值背后场景构成，每格同时给出样本量。','16源且不同方向构成下，C相对B的收益可能不同。','分层是事后评价；在线策略没有访问真实类型和源数。')
    fig,axs=layout(1,2);a,b,d=paired(df,3,'A','B')
    axs[0,0].scatter(b.fallback-a.fallback,d,s=18,alpha=.6,color=COL['B']);axs[0,0].axhline(0,c='k',lw=.8);axs[0,0].set(xlabel='兜底次数变化 B−A',ylabel='Δ 秒/源',title='Q3：兜底与性能变化')
    for v in 'AB':
        g=sub(df,3,v);axs[0,1].scatter(g.clear_attempts,g.score,s=16,alpha=.5,label=v,color=COL[v])
    axs[0,1].set(xlabel='清除尝试总次数',ylabel='秒/源（对数轴）',yscale='log',title='Q3：清除尝试与长尾');axs[0,1].legend()
    finish(fig,'Q3长尾与兜底关联','把平均收益与恢复代价放在同一视图，检查清除尝试是否伴随慢例。','全量中B兜底总次数高于A；少数慢例值得优先复盘。','相关性不能单独证明兜底是全部退步的原因。')
    fig,axs=layout(1,2)
    for ax,q in zip(axs[0],(3,4)):
        for v in ('AB' if q==3 else 'ABC'):
            g=sub(df,q,v);ax.scatter(g['last'],g.time,s=14,alpha=.4,label=v,color=COL[v])
        ax.set(xlabel='最后一个真实源首次发现时间 / s',ylabel='整局完成时间 / s',title=f'Q{q} 发现与完成的关系');ax.legend()
    finish(fig,'发现瓶颈：最后首次发现与结束时间','首次发现从合法direction/near反馈重建，结束时间包含剩余定位和扫描。','点与y=x之间的垂直差体现最后发现后的剩余工作。','真实源集合只用于确认最后一个源的身份；此指标不是策略可用的终止条件。')
    fig,axs=layout(1,2)
    for v in 'ABC':
        g=sub(df,4,v);x=np.sort(g.after_clear);axs[0,0].plot(x,np.arange(1,520)/519,label=v,color=COL[v])
    axs[0,0].set(xlabel='全清后仍执行的时间 / s',ylabel='累积案例比例',title='Q4：全清后的扫描尾部');axs[0,0].legend()
    a,b,d=paired(df,4,'A','B');axs[0,1].scatter(a.after_clear,a.time-b.time,c=a.total,cmap='viridis',s=20);axs[0,1].set(xlabel='A全清后剩余耗时 / s',ylabel='B相对A整局节省 / s',title='16源停止的可解释收益')
    finish(fig,'全清后残余扫描与公开上限停止','区分全清时刻和程序退出时刻，说明停止优化省掉了什么。','B只在16个不同频道成功清除后停止；10–15源仍必须完成原扫描义务。','离线知道全清时刻不意味着在线可以提前读取真实源数。')
    for key,title,unit in [('measure','测量点热力：重复驻点与覆盖结构','每案例每100m网格测量次数'),('negative','无信号比例：测量资源花在哪里','网格内无信号次数 / 测量次数'),('travel','路径经过热力：移动成本的空间集中','每案例每100m网格累计路径长度 / m')]:
        fig,axs=layout(2,3);values=[]
        for g in GROUPS:
            z=spatial[g][key]/519
            if key=='negative':z=np.divide(spatial[g]['negative'],spatial[g]['measure'],out=np.full_like(z,np.nan),where=spatial[g]['measure']>=50)
            values.append(z)
        norm=None if key=='negative' else LogNorm(vmin=min(z[z>0].min() for z in values),vmax=max(np.nanmax(z) for z in values))
        for ax,g,z in zip(axs.flat,GROUPS,values):
            im=ax.pcolormesh(EDGES,EDGES,np.ma.masked_invalid(z.T) if key=='negative' else np.ma.masked_less_equal(z.T,0),cmap='viridis',norm=norm,**({'vmin':0,'vmax':1} if key=='negative' else {}));circular(ax);ax.set_title(NAMES[g])
        axs.flat[-1].axis('off');fig.colorbar(im,ax=list(axs.flat[:-1]),label=unit,shrink=.7)
        finish(fig,title,'所有519案例叠加，统一色标；虚线圆为源所在目标域，域外机器人动作仍保留。','规则发现节点与局部定位访问可以形成不同热点；可直接比较同题不同方案。','无信号比例只显示累计≥50次测量的网格；路径热力按≤50m线段中点采样分配长度，非精确线格求交。','data/spatial_grids.npz')
    fig,axs=layout(2,2);gs=[(3,'A'),(3,'B'),(4,'A'),(4,'C')];zs=[]
    for g in gs:
        n=spatial[g]['first_n'];zs.append(np.divide(spatial[g]['first_sum'],n,out=np.full_like(n,np.nan),where=n>=5))
    for ax,g,z in zip(axs.flat,gs,zs):
        im=ax.pcolormesh(EDGES,EDGES,np.ma.masked_invalid(z.T),cmap='viridis',vmin=0,vmax=max(np.nanmax(t) for t in zs));circular(ax,2000);ax.set_title(NAMES[g])
    fig.colorbar(im,ax=list(axs.flat),label='源位网格平均首次发现时间 / s',shrink=.7)
    finish(fig,'圆域内的源首次发现延迟','把首次发现事件归到真实源坐标，寻找空间上的迟发现区域。','热点表示源在这些区域时平均被更晚发现，而非该处测量更多。','每格至少5个源事件；多个源来自同一案例，不是独立样本。真实源坐标仅用于事后图示。','data/spatial_grids.npz')
    fig,axs=layout(1,2)
    for ax,q in zip(axs[0],(3,4)):
        for v in ('AB' if q==3 else 'ABC'):
            p=np.array(progress[q,v]);x=np.linspace(0,1,101);ax.plot(x,p.mean(axis=0),color=COL[v],label=v);ax.fill_between(x,np.quantile(p,.25,axis=0),np.quantile(p,.75,axis=0),color=COL[v],alpha=.12)
        ax.set(xlabel='各案例归一化任务时间 t/T',ylabel='已清除源比例',title=f'Q{q} 清除进程均值与四分位带');ax.legend()
    finish(fig,'清除进程曲线','各局时间归一化后，比较清除集中在早期还是晚期以及中间停滞。','曲线接近1后仍有横向尾部，反映全清到退出的剩余工作。','归一化时间不能比较绝对速度；阴影为案例分位带，不是均值置信区间。','data/clearance_progress.npz')
    fig,axs=layout(1,2)
    for ax,q in zip(axs[0],(3,4)):
        v='B' if q==3 else 'C';a,b,d=paired(df,q,'A',v);a=a.copy();a['delta']=d;g=a.groupby('family').delta;means=g.mean().sort_values();ax.barh(range(len(means)),means,color=COL[v]);ax.set(yticks=range(len(means)),yticklabels=[f'{k} (n={g.size()[k]})' for k in means.index],xlabel='平均配对差 / 秒每源',title=f'Q{q} {v}−A');ax.axvline(0,c='k',lw=.8)
    finish(fig,'种子族敏感性','按固定集合的生成方式分组，检查结论是否由特定种子族支配。','一位扰动、哈希设计、字节模式与单个fixture须区分。','seed数值本身不是物理解释；小组样本少，不作显著性宣称。')
    fig,axs=layout(1,2)
    for ax,(q,ref,v) in zip(axs[0],[(3,'A','B'),(4,'B','C')]):
        a,b,d=paired(df,q,ref,v);ix=np.argsort(d)[-10:];ax.barh(range(10),d[ix],color=COL['B']);ax.set(yticks=range(10),yticklabels=[f'seed {int(a.seed.iloc[i])} · N={int(a.total.iloc[i])}' for i in ix],xlabel='候选减参照 / 秒每源',title=f'Q{q} {v}−{ref} 最大10个退步');ax.axvline(0,c='k',lw=.8)
    finish(fig,'反例优先级：最值得复盘的10个案例','用逐例退步排序形成后续研发清单，而不是只展示好看的成功案例。','Q3极端退步远大于其均值收益；Q4 C相对B也有明确反例。','本图是有意选择极端案例，不能代表随机案例频率。')

def cases(df):
    selected=[]
    for q,ref,v in [(3,'A','B'),(4,'B','C')]:
        a,b,d=paired(df,q,ref,v)
        for why,idx in [('最大退步',int(np.argmax(d))),('最大节省',int(np.argmin(d))),('配对差中位附近',int(np.argmin(abs(d-np.median(d)))) )]:
            seed=int(a.seed.iloc[idx]);selected.append(dict(problem=q,seed=seed,reference=ref,candidate=v,selection=why,delta=float(d[idx])))
            vs='AB' if q==3 else 'ABC';fig,axs=layout(2,len(vs));scene=json.loads((DATA/'scenes'/f'q{q}_{seed:04d}.json').read_bytes());tr={vv:trace(q,seed,vv) for vv in vs};limit=max(2300,max(abs(c) for vv in vs for x in tr[vv] if x['position'] is not None for c in x['position'])+100)
            maxt=max(sub(df,q,vv).set_index('seed').loc[seed,'time'] for vv in vs)
            for col,vv in enumerate(vs):
                rows=[x for x in tr[vv] if x['position'] is not None];p=np.array([[0.,0.]]+[x['position'] for x in rows]);times=np.array([x['response']['virtual_time_s'] for x in rows]);ax=axs[0,col]
                lc=LineCollection(np.stack([p[:-1],p[1:]],axis=1),cmap='viridis',norm=plt.Normalize(0,1),linewidth=.9,alpha=.7);lc.set_array(times/times[-1]);ax.add_collection(lc)
                mp=np.array([x['position'] for x in rows if x['path']=='/measure']);u,n=np.unique(np.round(mp,3),axis=0,return_counts=True);ax.scatter(u[:,0],u[:,1],s=8+12*np.sqrt(n),facecolors='none',edgecolors='#D95319',linewidths=.7,label='测量驻点，面积随次数增加')
                for j in scene['jammers']:
                    x,y=j['x_um']/1e6,j['y_um']/1e6;ax.scatter(x,y,s=28,marker='^' if j['kind']=='directional' else 'o',c='black')
                    if j['kind']=='directional':
                        angle=np.deg2rad(j['direction_udeg']/1e6);ax.arrow(x,y,150*np.cos(angle),150*np.sin(angle),head_width=45,color='black',length_includes_head=True)
                ax.scatter(0,0,marker='*',s=90,c='#EDB120',edgecolor='black',zorder=5);ax.scatter(*p[-1],marker='s',s=40,c='#7E2F8E',zorder=5);circular(ax,limit)
                r=sub(df,q,vv).set_index('seed').loc[seed];ax.set_title(f'{vv} · {r.score:.1f}s/源 · {r.distance/1000:.1f}km\n测量{r.measures}次 · 兜底{r.fallback}次');fig.colorbar(lc,ax=ax,label='任务进度 t/T',shrink=.65)
                ax=axs[1,col];first={};cleared=[];steps=[];count=[]
                for x in rows:
                    t=x['response']['virtual_time_s'];c=x['channel']
                    if x['path']=='/measure' and x['response']['measure_result']!='no_signal':first.setdefault(c,t)
                    if x['path']=='/clear' and x['response']['clear_result']=='success':cleared.append(t)
                    steps.append(t);count.append(len(first))
                ax.step([0]+steps,[0]+count,where='post',label='累计首次发现',color=COL['A']);ax.step([0]+cleared+[maxt],[0]+list(range(1,len(cleared)+1))+[len(cleared)],where='post',label='累计清除',color=COL['B']);ax.set(xlim=(0,maxt),ylim=(0,r.total+1),xlabel='绝对虚拟时间 / s',ylabel='源数',title='同一场景、统一时间轴');ax.legend()
            finish(fig,f'Q{q} seed {seed}：{why}',f'选择规则：{v}−{ref}的{why}；上排比较真实圆域路径，下排比较发现和清除事件。',f'配对差 {d[idx]:+.3f} 秒/源。黑点/三角为真实源，箭头为定向朝向；星形起点、紫方块终点；空心橙点大小表示测量重复次数。','路径以动作顺序连线，未做平滑；真实源仅用于离线评价。任务进度着色按各局归一化，绝对速度请看下排。',f'runs/q{q}_{seed:04d}_*.json.gz; scenes/q{q}_{seed:04d}.json')
    (OUT/'data/selected_cases.json').write_text(json.dumps(selected,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    global BOOK
    df,spatial,progress=prepare()
    for q,v in GROUPS:
        a=sub(df,q,v);g=spatial[q,v]
        assert g['measure'].sum()==a.measures.sum()
        assert g['negative'].sum()==a.negatives.sum()
        assert np.isclose(g['travel'].sum(),a.distance.sum(),rtol=1e-10)
        assert g['first_n'].sum()==a.total.sum()
    with PdfPages(OUT/'CPU519_完整科学图谱.pdf') as BOOK:
        aggregate(df,spatial,progress);cases(df)
    (OUT/'CATALOG.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf-8')
    intro='# CPU 519种子科学图谱\n\n共2595次完整本地运行；每个方案519场。Q3 A/B均为grid_v1，B增加定位后刷新。Q4 A=D1/45点，B再加16源退出，C再加37点。固定回归集，不是官方分布或新留出集。所有图为CPU数据，未混入CUDA或实机成绩。\n\n'
    sections=[]
    for c in catalog:
        sections.append(f'## 图{c["id"]} {c["title"]}\n\n![图{c["id"]}](png/{c["id"]}.png)\n\n**研究意义：** {c["meaning"]}\n\n**阅读与解释：** {c["readout"]}\n\n**边界：** {c["limit"]}\n\n**数据：** `{c["source"]}`。矢量版本：`pdf/{c["id"]}.pdf`、`svg/{c["id"]}.svg`。\n')
    (OUT/'图表详解.md').write_text(intro+'\n'.join(sections),encoding='utf-8')
    manifest={str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.rglob('*') if p.is_file() and p.name!='MANIFEST.json'}
    manifest['SOURCE_PLAN_SHA256']=hashlib.sha256((DATA/'PLAN.json').read_bytes()).hexdigest()
    (OUT/'MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('DONE',len(catalog),'figures',OUT,flush=True)

if __name__=='__main__':main()
