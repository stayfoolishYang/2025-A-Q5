"""Current report; legacy Eulerian diagnostics are retained only as history."""
from pathlib import Path
import csv,html,json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from validation.q4_contract import load_current_q4
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'results';FIG=OUT/'figures'
plt.rcParams.update({'font.family':'Microsoft YaHei','svg.fonttype':'none','axes.spines.top':False,
    'axes.spines.right':False,'legend.frameon':False,'axes.unicode_minus':False})

def table(headers,rows):
    return '| '+' | '.join(headers)+' |\n|'+'|'.join(['---']*len(headers))+'|\n'+'\n'.join('| '+' | '.join(str(v) for v in row)+' |' for row in rows)+'\n'

def main():
    load_current_q4()
    meta={q:json.loads((OUT/f'q{q}.json').read_text()) for q in range(1,5)}
    data={q:np.load(OUT/f'q{q}.npz')['data'] for q in range(1,5)}
    records=json.loads((OUT/'q4_release_experiments.json').read_text());by={r['name']:r for r in records}
    if by['material_mean']['event_s']!=meta[4]['event_s']:
        raise ValueError('Current Q4 ablation and primary event disagree')
    if not np.array_equal(data[4],np.load(OUT/'q4_scenarios/material_mean.npz')['data']):
        raise ValueError('Current Q4 scenario and primary trajectories disagree')
    validation=json.loads((OUT/'q4_validation.json').read_text());vby={r['name']:r for r in validation}
    for r in validation:
        if r['model']!=4 or r['moving'] is not True or r['ale'] is not False or r['tail']!='mean':
            raise ValueError('Current Q4 validation must use material coordinates and mean tail')
    if vby['dt_0.5']['event_s']!=meta[4]['event_s']:
        raise ValueError('Current Q4 validation and primary event disagree')
    endface=json.loads((OUT/'endface_summary.json').read_text(encoding='utf-8'))
    figures=[]
    def save(fig,name,title):
        fig.tight_layout()
        for ext in ('png','svg'):fig.savefig(FIG/f'{name}.{ext}',dpi=240,bbox_inches='tight')
        plt.close(fig);figures.append((name,title))
    for q in (3,4):
        d=data[q];n=meta[q]['n'];fig,ax=plt.subplots(figsize=(8,4.5))
        ax.plot(d[:,0]/3600,d[:,2+n:].max(1),label='全域最大含水率',color='#0f4d92')
        ax.plot(d[:,0]/3600,d[:,-1],label='表面含水率',color='#42949e')
        ax.axhline(.15,c='gray',ls='--',label='阈值 0.15');ax.axvline(meta[q]['event_h'],c='#9a4d8e',ls=':')
        title=f'Q{q} '+('材料坐标，均值平台' if q==4 else '固定半径，末值平台（保留）')
        ax.set(xlabel='时间 / h',ylabel='干基含水率 / (kg/kg)',title=f'{title}：{meta[q]["event_h"]:.4f} h');ax.legend()
        save(fig,f'q{q}_drying',title)
    labels={'material_mean':'均值平台（推荐）','material_last':'末值平台','material_nominal':'名义平台'}
    fig,axes=plt.subplots(1,2,figsize=(12,4.5))
    for name,label in labels.items():
        d=np.load(OUT/'q4_scenarios'/f'{name}.npz')['data'];n=by[name]['n']
        for ax in axes:ax.plot(d[:,0]/3600,d[:,2+n:].max(1),label=f'{label}：{by[name]["event_h"]:.4f} h')
    for ax in axes:ax.axhline(.15,c='gray',ls='--');ax.set(xlabel='时间 / h',ylabel='全域最大含水率 / (kg/kg)')
    axes[0].legend();axes[1].set(xlim=(49.5,51.8),ylim=(.146,.157),title='阈值附近放大')
    save(fig,'q4_scenarios','Q4材料坐标：三种后4 h平台情景')
    keys=['fixed_mean','material_mean','eulerian_mean'];names=['固定半径','移动材料坐标（主模型）','移动Eulerian（对照）']
    vals=[by[k]['event_h'] for k in keys];fig,ax=plt.subplots(figsize=(9,4))
    bars=ax.barh(names,vals,color=['#767676','#0f4d92','#42949e']);ax.bar_label(bars,fmt='%.4f h',padding=5);ax.invert_yaxis()
    ax.set(xlabel='烘干时长 / h',xlim=(0,max(vals)*1.18),title='Q4严格消融：同附录4物性、均值平台、81节点、0.5 s')
    save(fig,'ablation','Q4严格消融（均值平台）')
    from physics.boundary import Boundary
    times=np.linspace(0,60*3600,2401);fig,axes=plt.subplots(1,2,figsize=(12,4))
    for tail,label in [('mean','末小时均值（推荐）'),('last','末值'),('nominal','名义平台')]:
        ambient=Boundary(tail=tail).ambient(times)
        for j,ax in enumerate(axes):ax.plot(times/3600,ambient[:,j],label=label,alpha=.8)
    for j,ax in enumerate(axes):ax.axvline(4,c='gray',ls=':');ax.set(xlabel='时间 / h',ylabel=['温度 / °C','边界水分变量 / (kg/kg)'][j]);ax.legend()
    save(fig,'q4_boundary','Q4边界情景：前4 h共用实测插值')
    fig,axes=plt.subplots(1,2,figsize=(12,4.3))
    nodes=[41,81,161];events=[vby[f'grid_{n}']['event_s'] for n in nodes]
    axes[0].plot(nodes,np.asarray(events)-events[-1],'o-',color='#0f4d92')
    steps=[4.,2.,1.,.5];events=[vby['grid_81' if dt==1 else f'dt_{dt:g}']['event_s'] for dt in steps]
    axes[1].plot(steps,np.asarray(events)-events[-1],'o-',color='#42949e')
    axes[0].set(xlabel='径向节点数（BE，dt=1 s）',ylabel='相对161节点的时长差 / s')
    axes[1].set(xlabel='时间步长 / s（81节点）',ylabel='相对0.5 s的时长差 / s')
    fig.suptitle('Q4随体归一化坐标、均值平台：本版收敛实验')
    save(fig,'convergence','Q4材料均值模型：空间与时间收敛')
    fig,axes=plt.subplots(1,2,figsize=(12,4.3));factors=[.8,.9,1.,1.1,1.2]
    base=vby['grid_81']['event_h']
    for j,param in enumerate(('D','hm','hT','k')):
        values=np.array([base if f==1 else vby[f'{param}_{f:g}']['event_h'] for f in factors])
        ax=axes[0 if j<2 else 1]
        y=100*(values/base-1) if j<2 else 60*(values-base)
        ax.plot(factors,y,'o-',label=param)
    axes[0].set(ylabel='时长变化 / %');axes[1].set(ylabel='时长变化 / min')
    for ax in axes:ax.set_xlabel('参数乘数');ax.legend();ax.axhline(0,c='gray',lw=.5)
    fig.suptitle('Q4材料均值模型：81节点、BE dt=1 s，单参数变化')
    save(fig,'q4_sensitivity','Q4当前模型的D、hm、hT、k敏感性')
    lines=['# 药材烘干问题：Q4材料坐标冻结版','',
        f'Q4推荐主结果：**{meta[4]["event_h"]:.4f} h**（{meta[4]["event_s"]:.4f} s）。材料坐标、后4 h末一小时均值平台。', '',
        f'Q1—Q3保留原结果，Q3固定半径/末值平台为{meta[3]["event_h"]:.4f} h。本轮仅切换Q4，不能将Q3与Q4的全部差值解释为收缩效应。','',
        '## 冻结模型与假设','','采用ξ=r/R(t)，均匀径向收缩、固定长度、v=w，质量方程干密度s(t)=s₀(R₀/R)²。材料坐标下无相对网格输运：','',
        '$$U_t=\\frac{1}{R^2\\xi}\\partial_\\xi(\\xi D U_\\xi).$$','',
        '附录4动态物性原公式保持，ρ_eff(C) cp(C)作为有效体积热容，不再将ρ_eff/(1+C)同时当作守恒干密度。温度方程也采用材料导数。本版采用“规定移动边界下的随体归一化坐标模型”；冻结的是条件模型版本，不代表新增物理实验验证。','',
        '水分Robin条件写为 −D∂C/∂r=hm(Cs−Ceq)。Ceq是等效表面平衡含水变量；题目未给吸附等温线，因此取Ceq=Cair作为有效经验映射。空气和干药材的kg/kg基准不同，不能声称二者本来就是同一物理量。','',
        '0—4 h为附件1 PCHIP；之后推荐49.9989344262°C、0.049987540984 kg/kg（3—4 h含两端61点均值）。保留末值50.165°C/0.04986及名义50°C/0.05情景，均为延续假设。','',
        f'{meta[4]["n"]}节点、{meta[4]["scheme"].upper()}步长{meta[4]["dt"]} s、{meta[4]["interpolation"].upper()}、Picard容差1e-7°C/1e-9 kg/kg。每60 s及最终事件输出；max(C)≤0.15首次跨越时二分定位，Excel四位小数。显示0.1500不意味着全精度未达标。','',
        '## Q4严格消融与边界情景','',table(['同均值平台对照','时长 / h'],[[l,f'{by[k]["event_h"]:.6f}'] for k,l in zip(keys,names)]),'',
        f'固定→材料坐标缩短{by["fixed_mean"]["event_h"]-by["material_mean"]["event_h"]:.6f} h；原Eulerian输运增加{by["eulerian_mean"]["event_h"]-by["material_mean"]["event_h"]:.6f} h。','',
        table(['材料坐标平台情景','时长 / h'],[[l,f'{by[k]["event_h"]:.6f}'] for k,l in labels.items()]),'',
        '[完整Q4消融表](q4_ablation.csv) · [计算记录](q4_release_experiments.json)','',
        '## 本版数值核验','',table(['设置','时长 / h'],[[k,f'{vby[k]["event_h"]:.9f}'] for k in ['grid_41','grid_81','grid_161','dt_4','dt_2','dt_0.5','bdf2','linear']]),'',
        f'统一dt=1 s时81→161节点改变{(vby["grid_81"]["event_s"]-vby["grid_161"]["event_s"]):.4f} s；81节点下1→0.5 s改变{(vby["grid_81"]["event_s"]-vby["dt_0.5"]["event_s"]):.4f} s，BE与BDF2 dt=1 s相差{(vby["grid_81"]["event_s"]-vby["bdf2"]["event_s"]):.4f} s。无需继续极端加密以掩盖模型结构问题。','',
        f'主模型材料参考积分累计相对残差{meta[4]["max_cumulative_balance_relative"]:.3e}，内部预算不含最后二分子步。事件括区宽0.0625 s不是总预测精度。','',
        '[导出核验](export_validation.json) · [求解器测试](tests.json) · [本版收敛表](q4_convergence.csv) · [敏感性表](q4_sensitivity.csv) · [24条完整实验记录](q4_validation.json)。新convergence/q4_sensitivity图已覆盖旧图；旧图可从Git历史取得，experiments.json与audit/仍是明确的历史证据。','',
        '## 当前模型的单参数敏感性','',table(['参数','×0.8 / h','×0.9 / h','×1.0 / h','×1.1 / h','×1.2 / h'],[[p]+[f'{(base if f==1 else vby[f"{p}_{f:g}"]["event_h"]):.6f}' for f in factors] for p in ('D','hm','hT','k')]),'',
        '各项均为81节点、BE dt=1 s、材料坐标、均值平台，单位倍率共用同一完整基准轨迹。没有把旧Eulerian敏感性用于新模型，也没有执行GPU或Monte Carlo。参数区间是指定情景，不是统计置信区间。','',
        ]
    lines += ['## 轴对称端面对照','',
        '在轴向半域0—0.125 m上解r-z材料坐标模型，端面与侧面使用相同hm/hT及Ceq映射作为对照假设；没有将端面系数当作新实测数据。', '',
        table(['对照','径向×轴向节点','dt / s','1D / h','2D / h','配对时差 / s','2D终态平均C'],
            [[r['label'],f'{r["nr"]}×{r["nz"]}',r['dt_s'],f'{r["event_1d_h"]:.9f}',f'{r["event_2d_h"]:.9f}',f'{r["event_difference_s"]:.6f}',f'{r["final_mean_C_2d"]:.8f}'] for r in endface['rows']]),'',
        '关闭端面交换的二维模型通过逐场退化检查。两个端面开放算例须分别与同径向网格/步长的一维解配对，不能把其粗时间步的绝对时长与0.5 s主结果直接相减当作端面误差。', '',
        table(['细级代表时刻 / h','1D最大C','2D最大C','1D平均C','2D平均C'],
            [[f'{p["time_s"]/3600:.4f}',f'{p["max_C_1d"]:.8f}',f'{p["max_C_2d"]:.8f}',f'{p["mean_C_1d"]:.8f}',f'{p["mean_C_2d"]:.8f}'] for p in endface['representative_time_pairs']['fine'] if p['time_s']>0]),'',
        '本benchmark对达标时间与平均含水率/端部剖面给出不同结论；在数值定位分辨率内未分辨出的事件变化，不是连续模型误差的严格上界，也不能推广为整个1D温湿场端面效应可忽略。初始8%面积比不是误差上界。不对模型结构、边界、端面和离散误差作未经量化的统一排序。', '',
        '[二维方程、质量分母及验证解释](../validation/端面验证.md) · [配对数值证据](endface_summary.json) · [端面图](endface_comparison.png)', '',
        '## 题目表1—表6（当前主结果）','']
    ti=1
    for q in range(1,5):
        d=data[q];n=meta[q]['n']
        times=[100,300,600,900,1200,1500,1800] if q==1 else list(np.arange(1800,10801,1800)) if q==2 else list(np.arange(21600,d[-1,0],21600))+[d[-1,0]]
        for title,start in ([('温度',2),('水分浓度',2+n)] if q<=2 else [('水分浓度',2+n)]):
            rows=[]
            for t in times:
                row=d[int(np.argmin(abs(d[:,0]-t)))];R=row[1]*100;points=np.arange(5)*.5
                vals=np.interp(points,np.linspace(0,R,n),row[start:start+n])
                cells=[f'{v:.4f}' if r<=R+1e-10 else '—' for r,v in zip(points,vals)]
                if q==4:cells += [f'{row[start+n-1]:.4f}',f'{R:.4f}']
                rows.append([f'{t:.0f}' if q==1 else f'{t/3600:.4f}']+cells)
            headers=['时间 / '+('s' if q==1 else 'h'),'0 cm','0.5 cm','1 cm','1.5 cm','2 cm']+(['药材表面','半径 / cm'] if q==4 else [])
            lines += [f'### 表{ti}：问题{q}{title}','',table(headers,rows),'']
            with (OUT/f'table{ti}.csv').open('w',newline='',encoding='utf-8-sig') as f:
                w=csv.writer(f);w.writerow(headers);w.writerows(rows)
            ti+=1
    lines += ['## 冻结与追溯','','[冻结说明](../Q4_FREEZE.md) · [SHA-256清单](q4_freeze_manifest.json) · [历史物理审计](../audit/审计报告.md)。未启动8卡UQ。','']
    (OUT/'求解报告.md').write_text('\n'.join(lines),encoding='utf-8')
    nav=''.join(f'<li><a href="result{q}.xlsx">result{q}.xlsx</a></li>' for q in range(1,5))
    pics=''.join(f'<section><h2>{html.escape(title)}</h2><a href="figures/{name}.svg"><img src="figures/{name}.png"></a></section>' for name,title in figures)
    pics+='<section><h2>Q4轴对称端面对照</h2><a href="endface_comparison.svg"><img src="endface_comparison.png"></a></section>'
    page=f'<!doctype html><html lang="zh"><meta charset="utf-8"><title>Q4材料坐标冻结版</title><style>body{{max-width:1100px;margin:48px auto;padding:0 24px;font:17px/1.7 "Microsoft YaHei",sans-serif;color:#19344b}}img{{max-width:100%}}section{{margin:40px 0}}</style><h1>Q4材料坐标冻结版</h1><p>推荐均值平台：{meta[4]["event_h"]:.4f} h。Q1—Q3保留原结果。</p><p><a href="求解报告.md">当前报告</a> · <a href="q4_ablation.csv">Q4消融表</a> · <a href="../Q4_FREEZE.md">冻结说明</a></p><ul>{nav}</ul>{pics}</html>'
    (OUT/'index.html').write_text(page,encoding='utf-8')
    print('Current report, tables and Q4 figures generated.')

if __name__=='__main__':main()
