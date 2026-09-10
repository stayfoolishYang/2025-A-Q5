"""Current report; legacy Eulerian diagnostics are retained only as history."""
from pathlib import Path
import csv,html,json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'results';FIG=OUT/'figures'
plt.rcParams.update({'font.family':'Microsoft YaHei','svg.fonttype':'none','axes.spines.top':False,
    'axes.spines.right':False,'legend.frameon':False,'axes.unicode_minus':False})

def table(headers,rows):
    return '| '+' | '.join(headers)+' |\n|'+'|'.join(['---']*len(headers))+'|\n'+'\n'.join('| '+' | '.join(str(v) for v in row)+' |' for row in rows)+'\n'

def main():
    meta={q:json.loads((OUT/f'q{q}.json').read_text()) for q in range(1,5)}
    data={q:np.load(OUT/f'q{q}.npz')['data'] for q in range(1,5)}
    records=json.loads((OUT/'q4_release_experiments.json').read_text());by={r['name']:r for r in records}
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
    lines=['# 药材烘干问题：Q4材料坐标冻结版','',
        f'Q4推荐主结果：**{meta[4]["event_h"]:.4f} h**（{meta[4]["event_s"]:.4f} s）。材料坐标、后4 h末一小时均值平台。', '',
        f'Q1—Q3保留原结果，Q3固定半径/末值平台为{meta[3]["event_h"]:.4f} h。本轮仅切换Q4，不能将Q3与Q4的全部差值解释为收缩效应。','',
        '## 冻结模型与假设','','采用ξ=r/R(t)，均匀径向收缩、固定长度、v=w，质量方程干密度s(t)=s₀(R₀/R)²。材料坐标下无相对网格输运：','',
        '$$U_t=\\frac{1}{R^2\\xi}\\partial_\\xi(\\xi D U_\\xi).$$','',
        '附录4动态物性原公式保持，ρ作为热方程有效经验系数，不再将ρ/(1+C)同时当作守恒干密度。温度方程也采用材料导数。Robin驱动力保留题给变量的有效经验解释。冻结的是这套明确的条件模型，不代表新增物理实验验证。','',
        '0—4 h为附件1 PCHIP；之后推荐49.9989344262°C、0.049987540984 kg/kg（3—4 h含两端61点均值）。保留末值50.165°C/0.04986及名义50°C/0.05情景，均为延续假设。','',
        '81节点、BE步长0.5 s、Picard容差1e-7°C/1e-9 kg/kg。每60 s及最终事件输出；max(C)≤0.15首次跨越时二分定位，Excel四位小数。显示0.1500不意味着全精度未达标。','',
        '## Q4严格消融与边界情景','',table(['同均值平台对照','时长 / h'],[[l,f'{by[k]["event_h"]:.6f}'] for k,l in zip(keys,names)]),'',
        f'固定→材料坐标缩短{by["fixed_mean"]["event_h"]-by["material_mean"]["event_h"]:.6f} h；原Eulerian输运增加{by["eulerian_mean"]["event_h"]-by["material_mean"]["event_h"]:.6f} h。','',
        table(['材料坐标平台情景','时长 / h'],[[l,f'{by[k]["event_h"]:.6f}'] for k,l in labels.items()]),'',
        '[完整Q4消融表](q4_ablation.csv) · [计算记录](q4_release_experiments.json)','',
        '## 本版数值核验','',table(['设置','时长 / h'],[[k,f'{by[k]["event_h"]:.6f}'] for k in ['material_mean_grid41','material_mean_dt1','material_mean']]),'',
        f'主模型材料参考积分累计相对残差{meta[4]["max_cumulative_balance_relative"]:.3e}，内部预算不含最后二分子步。事件括区宽0.0625 s不是总预测精度。','',
        '[导出核验](export_validation.json) · [求解器测试](tests.json)。旧experiments.json、旧收敛/灵敏度图及audit/保留为历史记录，不作为本冻结模型验证。','',
        '## 题目表1—表6','']
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
    page=f'<!doctype html><html lang="zh"><meta charset="utf-8"><title>Q4材料坐标冻结版</title><style>body{{max-width:1100px;margin:48px auto;padding:0 24px;font:17px/1.7 "Microsoft YaHei",sans-serif;color:#19344b}}img{{max-width:100%}}section{{margin:40px 0}}</style><h1>Q4材料坐标冻结版</h1><p>推荐均值平台：{meta[4]["event_h"]:.4f} h。Q1—Q3保留原结果。</p><p><a href="求解报告.md">当前报告</a> · <a href="q4_ablation.csv">Q4消融表</a> · <a href="../Q4_FREEZE.md">冻结说明</a></p><ul>{nav}</ul>{pics}</html>'
    (OUT/'index.html').write_text(page,encoding='utf-8')
    print('Current report, tables and Q4 figures generated.')

if __name__=='__main__':main()
