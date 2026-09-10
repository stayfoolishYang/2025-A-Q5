"""Produce paper tables, figures and an evidence-linked numerical report."""
from pathlib import Path
import csv
import html
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'results'; FIG=OUT/'figures'
plt.rcParams.update({'font.family':'Microsoft YaHei','svg.fonttype':'none','axes.spines.top':False,
                     'axes.spines.right':False,'legend.frameon':False,'font.size':10,'axes.unicode_minus':False})
colors=['#0F4D92','#3775BA','#42949E','#9A4D8E','#767676']
figures=[]

def save(fig,name,title):
    fig.tight_layout()
    fig.savefig(FIG/f'{name}.svg',bbox_inches='tight')
    fig.savefig(FIG/f'{name}.png',dpi=300,bbox_inches='tight')
    plt.close(fig);figures.append((name,title))

def table(headers,rows):
    return '| '+' | '.join(headers)+' |\n|'+ '|'.join(['---']*len(headers))+'|\n'+'\n'.join('| '+' | '.join(str(v) for v in row)+' |' for row in rows)+'\n'

def main():
    FIG.mkdir(exist_ok=True)
    meta={q:json.loads((OUT/f'q{q}.json').read_text()) for q in range(1,5)}
    data={q:np.load(OUT/f'q{q}.npz')['data'] for q in range(1,5)}
    ex=json.loads((OUT/'experiments.json').read_text())
    by={r['name']:r for r in ex}
    boundary=np.loadtxt(ROOT/'data'/'boundary.csv',delimiter=',',skiprows=1)
    radius=np.loadtxt(ROOT/'data'/'radius.csv',delimiter=',',skiprows=1)
    fig,axes=plt.subplots(1,2,figsize=(11,4))
    for j,ax in enumerate(axes):
        ax.plot(boundary[:,0]/3600,boundary[:,j+1],color=colors[j]);ax.set(xlabel='时间 / h',ylabel=['烘房温度 / °C','烘房含水率 / (kg/kg)'][j])
    save(fig,'boundary','附件1：时变烘房边界')
    fig,ax=plt.subplots(figsize=(7,4));ax.plot(radius[:,0]/3600,radius[:,1],color=colors[0]);ax.set(xlabel='时间 / h',ylabel='药材半径 / cm');save(fig,'radius','附件2：半径变化')
    for q in (1,2):
        d=data[q];n=meta[q]['n']
        fig,axes=plt.subplots(1,2,figsize=(11,4))
        for ax,start,title in zip(axes,(2,2+n),('温度 / °C','干基含水率 / (kg/kg)')):
            z=d[:,start:start+n]
            im=ax.pcolormesh(d[:,0]/3600,np.linspace(0,2,n),z.T,shading='auto',cmap='viridis',rasterized=True)
            ax.set(xlabel='时间 / h',ylabel='距中心 / cm',title=title);fig.colorbar(im,ax=ax)
        save(fig,f'q{q}_fields',f'问题{q}：径向温湿场')
    for q in (3,4):
        d=data[q];n=meta[q]['n']
        fig,ax=plt.subplots(figsize=(7,4))
        ax.plot(d[:,0]/3600,d[:,2+n],label='中心（同时为全域最大值）',color=colors[0])
        ax.plot(d[:,0]/3600,d[:,-1],label='药材表面',color=colors[2])
        ax.axhline(.15,color='#767676',linestyle='--',label='达标阈值 0.15')
        ax.axvline(meta[q]['event_h'],color=colors[1],linestyle=':')
        ax.set(xlabel='时间 / h',ylabel='干基含水率 / (kg/kg)');ax.legend()
        save(fig,f'q{q}_drying',f'问题{q}：全域达标过程')
    fig,axes=plt.subplots(1,2,figsize=(11,4))
    for q,c in ((3,colors[0]),(4,colors[2])):
        grid=[by[f'q{q}_grid_{n}']['event_h'] for n in (21,41,81)]
        axes[0].plot([21,41,81],(np.asarray(grid)-grid[-1])*3600,'o-',color=c,label=f'Q{q}')
        steps=[by[f'q{q}_dt_{dt:g}']['event_s'] for dt in (4.,2.,1.,.5)]
        axes[1].plot([4,2,1,.5],np.asarray(steps)-steps[-1],'o-',color=c,label=f'Q{q}')
    axes[0].set(xlabel='径向节点数',ylabel='相对81节点的时间差 / s');axes[1].set(xlabel='时间步长 / s',ylabel='相对0.5 s步长的时间差 / s')
    for ax in axes:ax.legend()
    save(fig,'convergence','网格与时间步收敛')
    for q in (3,4):
        fig,ax=plt.subplots(figsize=(7,4))
        base=by[f'q{q}_D_1.0']['event_h']
        for param,color in zip(('D','hm','hT','k'),colors):
            vals=[by[f'q{q}_{param}_{f}']['event_h'] for f in (.8,.9,1.,1.1,1.2)]
            ax.plot([.8,.9,1.,1.1,1.2],100*(np.asarray(vals)/base-1),'o-',label=param,color=color)
        ax.set(xlabel='参数乘数',ylabel='烘干时长变化 / %');ax.legend();save(fig,f'q{q}_sensitivity',f'问题{q}：单参数灵敏度')
    names=['q3_fixed_parameters','q3_oneway','q3_D_1.0','q4_fixed_radius','q4_D_1.0','q4_material_coordinate']
    labels=['附录3全参数冻结','附录3单向耦合','附录3双向耦合','附录4固定半径','附录4收缩ALE','附录4材料坐标']
    fig,ax=plt.subplots(figsize=(8,4));vals=[by[k]['event_h'] for k in names]
    ax.barh(labels,vals,color=colors[0]);ax.invert_yaxis();ax.set_xlabel('烘干时长 / h')
    for y,v in enumerate(vals):ax.text(v+.4,y,f'{v:.2f}',va='center')
    ax.set_xlim(0,max(vals)*1.16);save(fig,'ablation','消融：物性、反馈及收缩假设')
    lines=['# 药材烘干问题数值求解报告','',
           f'主结果：Q3固定半径烘干时间 **{meta[3]["event_h"]:.4f} h**；Q4收缩模型 **{meta[4]["event_h"]:.4f} h**。',
           '','计算条件：附录原公式、PCHIP、81节点、BE步长0.5 s、Picard容差1e-7°C和1e-9 kg/kg。四个Excel均按模板输出四位小数。',
           '', '**外部边界只实测到4 h**。之后保持50.165°C、0.04986 kg/kg。结果是这一假设及一维径向模型下的预测，不是实验测得的烘干时间。',
           '', '## 模型和算法', '', '[模型推导、有限体积离散、边界假设与参考文献](../题目分析报告.md)。Q1热物性固定，Q2/Q3和Q4分别使用附录3和附录4。C是干基含水率，D中的温度使用K。',
           '', '伪代码：读取附件并核对单位 → 插值当前边界和半径 → 按当前T、C更新物性 → 组装热量/水分三对角系统 → Picard迭代至收敛 → 更新几何积分及通量审计 → 若max(C)跨过0.15则二分子步 → 按规定时间及物理半径输出。',
           '', '## 题目要求的表1—表6', '']
    ti=1
    for q in range(1,5):
        d=data[q];n=meta[q]['n']
        times=[100,300,600,900,1200,1500,1800] if q==1 else list(np.arange(1800,10801,1800)) if q==2 else list(np.arange(21600,d[-1,0],21600))+[d[-1,0]]
        for title,start in ([('温度',2),('水分浓度',2+n)] if q<=2 else [('水分浓度',2+n)]):
            rows=[]
            for t in times:
                idx=int(np.argmin(abs(d[:,0]-t)));row=d[idx];R=row[1]*100
                points=np.arange(5)*.5
                val=np.interp(points,np.linspace(0,R,n),row[start:start+n])
                cells=[f'{v:.4f}' if r<=R+1e-10 else '—' for r,v in zip(points,val)]
                if q==4:cells += [f'{row[start+n-1]:.4f}',f'{R:.4f}']
                time_label=f'{t:.0f}' if q==1 else f'{t/3600:.4f}'
                rows.append([time_label]+cells)
            headers=['时间 / '+('s' if q==1 else 'h'),'0 cm','0.5 cm','1 cm','1.5 cm','2 cm']+(['药材表面','半径 / cm'] if q==4 else [])
            lines += [f'### 表{ti}：问题{q}{title}', '',table(headers,rows),'']
            with (OUT/f'table{ti}.csv').open('w',newline='',encoding='utf-8-sig') as f:
                w=csv.writer(f);w.writerow(headers);w.writerows(rows)
            ti+=1
    lines+=['## 误差与守恒','',table(['问题','21节点 / h','41节点 / h','81节点 / h','41→81差 / s'],[[f'Q{q}']+[f'{by[f"q{q}_grid_{n}"]["event_h"]:.6f}' for n in (21,41,81)]+[f'{abs(by[f"q{q}_grid_41"]["event_s"]-by[f"q{q}_grid_81"]["event_s"]):.3f}'] for q in (3,4)]),'',
            table(['问题','dt=4 s / h','dt=2 s / h','dt=1 s / h','dt=0.5 s / h','BDF2 dt=1 s / h'],[[f'Q{q}']+[f'{by[f"q{q}_dt_{dt:g}"]["event_h"]:.6f}' for dt in (4.,2.,1.,.5)]+[f'{by[f"q{q}_bdf2"]["event_h"]:.6f}'] for q in (3,4)]),'',
            '事件二分区间宽0.0625 s；这是定位误差，网格误差和模型假设误差另计。四位小数是题目要求的输出格式，不代表物理预测具有相同精度。', '',
            table(['问题','最大累计几何积分相对残差','最大Picard次数'],[[f'Q{q}',f'{meta[q]["max_cumulative_balance_relative"]:.3e}',meta[q]['max_picard_iterations']] for q in range(1,5)]),'',
            '固定域审计I=∫Crdr与表面通量；移动域额外包含R Rdot Cs扫掠项。该量不是kg单位真实总水量。真实干物质守恒需要额外固体运动和密度假设。解析圆柱Robin特征模态的空间加密误差、Thomas与SciPy求解对比及几何常数场检验见 [tests.json](tests.json)。', '',
            '## 消融与参数影响','',table(['实验','烘干时长 / h'],[[l,f'{by[n]["event_h"]:.4f}'] for n,l in zip(names,labels)]),'',
            'Q3和Q4的物性不同，不能把它们的全部时间差都归因于半径收缩。同附录4参数下固定半径和动半径比较才隔离几何变化。材料坐标对照取消网格对流，代表另一种固体随动假设，主结果仍采用指定的Eulerian坐标变换。', '',
            '将Q1经验式强行延用于全程的对照在240 h时仍未达标，记为右删失，不伪造完成时间。', '',
            table(['问题','末次值平台 / h','末小时均值平台 / h','变化 / min'],[[f'Q{q}',f'{by[f"q{q}_D_1.0"]["event_h"]:.4f}',f'{by[f"q{q}_tail_mean"]["event_h"]:.4f}',f'{(by[f"q{q}_tail_mean"]["event_h"]-by[f"q{q}_D_1.0"]["event_h"])*60:.2f}'] for q in (3,4)]),'']
    lhs=[r['event_h'] for r in ex if r['name'].startswith('lhs_')]
    lines += ['以上消融和单参数实验统一采用41节点、2 s步长。', '',table(['问题','PCHIP / h','线性 / h','差 / s'],[[f'Q{q}',f'{by[f"q{q}_D_1.0"]["event_h"]:.6f}',f'{by[f"q{q}_linear"]["event_h"]:.6f}',f'{by[f"q{q}_linear"]["event_s"]-by[f"q{q}_D_1.0"]["event_s"]:.4f}'] for q in (3,4)]), '',
              '两种插值下的事件时长在本次0.0625 s定位分辨率内相同，不意味着两种插值产生的整个温湿场完全相同。', '',
              f'24组固定种子LHS样本，各参数在0.8—1.2倍区间均匀取样，Q3时长范围为{min(lhs):.3f}—{max(lhs):.3f} h。这是设定扰动区间的情景范围，不是由实测误差估计的置信区间。','',
              '在规定±20%扰动下，扩散系数D对完成时间影响最大，hm次之；hT和k主要改变升温瞬态，影响完成时间较小。图中敏感性是模型内的条件关系，不是额外实测因果证据。','']
    # Bi and Fo at the initial state, plus drying threshold state for diffusion resistance.
    from physics.material import properties
    cap,k,D=properties(np.array([28.,50.165]),np.array([2.55,.15]),2,0,np.ones(4))
    lines += ['## 无量纲解释','',f'Q3初始热Bi=hT R/k={25*.02/k[0]:.3f}，湿Bi=hm R/D={8e-7*.02/D[0]:.3f}；阈值含水率、平台温度下湿Bi={8e-7*.02/D[1]:.3f}。后期扩散变慢，内部阻力上升，必须以全域最大值而非平均值判断完成。初始热Fourier数在1800 s时为{k[0]/cap[0]*1800/.02**2:.3f}。','']
    gpu=OUT/'gpu_worker_0.json'
    if gpu.exists():
        g=json.loads(gpu.read_text());err=np.asarray(g['max_backend_errors']).max(axis=0)
        lines += ['## CUDA实算','',f'{g["device"]}，PyTorch {g["torch"]}，FP64、{len(g["samples"])}条完整Q3轨迹、21节点、dt=60 s。GPU耗时{g["gpu_wall_s"]:.3f} s，CPU同批量同终点耗时{g["cpu_wall_s"]:.3f} s。终态温度最大差{err[0]:.3e}°C、含水率最大差{err[1]:.3e} kg/kg。', '',
                 '此小型一维问题CPU更快，主结果与大规模验证使用CPU。GPU采用现成batched dense solve作为可核对实现，暂未编写自定义CUDA三对角内核。GPU事件表仅线性定位、用于后端验证，不替代四个Excel的高精度CPU事件。8卡按样本分片，每卡一个独立进程；未持有远程服务器访问资料，未声称完成4090/V100或8卡实测。', '']
    lines += ['## 复现与交付','', '[四个Excel与图表导航](index.html)，[运行说明](../README.md)，[实验完整记录](experiments.json)。', '', '边界、物性、坐标假设的不确定性大于二分定位误差。径向模型、末端边界延续、等效Robin驱动力均需在论文假设中明示。']
    (OUT/'求解报告.md').write_text('\n'.join(lines),encoding='utf-8')
    nav=''.join(f'<li><a href="result{q}.xlsx">result{q}.xlsx</a></li>' for q in range(1,5))
    pictures=''.join(f'<section><h2>{html.escape(title)}</h2><a href="figures/{name}.svg"><img src="figures/{name}.png" alt="{html.escape(title)}"></a></section>' for name,title in figures)
    page=f'<!doctype html><html lang="zh"><meta charset="utf-8"><title>药材烘干求解</title><style>body{{max-width:1100px;margin:48px auto;padding:0 24px;font:17px/1.7 "Microsoft YaHei",sans-serif;color:#19344b;background:#fafafa}}h1{{font-size:34px}}h2{{font-size:23px}}section{{margin:48px 0}}img{{max-width:100%;background:white}}a{{color:#0f4d92}}</style><h1>药材烘干问题</h1><p>Q3：{meta[3]["event_h"]:.4f} h　Q4：{meta[4]["event_h"]:.4f} h</p><p>前4小时后保持末次烘房温湿度；详细假设、误差与表1—6见<a href="求解报告.md">求解报告</a>。</p><ul>{nav}</ul>{pictures}</html>'
    (OUT/'index.html').write_text(page,encoding='utf-8')
    summary=[{k:v for k,v in r.items() if k not in ('last_T','last_C','scales','event_bracket_s')} for r in ex]
    with (OUT/'experiments_summary.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=summary[0].keys());w.writeheader();w.writerows(summary)
    print('Report, six paper tables, ten SVG/PNG figures and HTML written.')

if __name__=='__main__':main()
