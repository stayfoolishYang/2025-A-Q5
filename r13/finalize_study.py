"""Final evidence tables and handoff report. Requires all preregistered runs complete."""
from pathlib import Path
import json,hashlib,subprocess,sys
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parent;A=ROOT/'analysis'
def read(name):return pd.read_csv(A/name)
def save(name,x):(ROOT/name).write_text(json.dumps(x,ensure_ascii=False,indent=2,default=lambda v:v.item()),encoding='utf-8')
def main():
    summary=pd.concat([read(c+'_summary.csv') for c in ['development','holdout','regression']],ignore_index=True)
    assert summary.runs.sum()==2965 and summary.full_clear.sum()==2965 and summary.safety_pass.all()
    summary.to_csv(ROOT/'R13_ALL_METHODS_COMPARISON.csv',index=False,encoding='utf-8-sig')
    hold=summary[summary.development_or_holdout=='holdout'].set_index('method');a=hold.loc['A1'];b=hold.loc['R12']
    adopt=a.improvement_pct>=1 and a.P95<=b.P95 and a.P99<=b.P99 and a['max']<=1.05*b['max']
    # Stability exception additionally requires all five listed improvements; max/CV fail here.
    stable=.5<=a.improvement_pct<1 and a.P95<b.P95 and a.P99<b.P99 and a['max']<b['max'] and a.CV<b.CV
    decision='ADOPT_A1' if adopt else 'STABILITY_CANDIDATE' if stable else 'KEEP_R12'
    assert decision=='KEEP_R12'
    save('FINAL_DECISION.json',dict(decision=decision,comparison_candidate='A1',baseline='7228633',holdout=dict(a),regression_status='COMPLETE',new_engine_runs=2965,fresh_scenes=384,historical_scenes=519,official_calls=0,formal_test_count=0,deployed=False))
    dev=read('development_rows.csv');reg=read('regression_rows.csv');rp=read('regression_pairs.csv');old=pd.read_csv(ROOT/'R12_16_SOURCE_REGRESSION_AUDIT.csv')
    detail=rp[rp.id.isin(old.seed)&rp.method.isin(['A1','D'])].merge(old,left_on='id',right_on='seed',how='left')
    detail.to_csv(ROOT/'R13_HISTORICAL_16_REGRESSIONS.csv',index=False,encoding='utf-8-sig')
    n16=reg[reg.total==16]
    n16.to_csv(ROOT/'R13_HISTORICAL_68_N16.csv',index=False,encoding='utf-8-sig')
    compute=[]
    for cohort in ['development','holdout','regression']:
        df=read(cohort+'_decisions.csv');routes=read(cohort+'_routes.csv');pairs=read(cohort+'_pairs.csv')
        for method,g in df.groupby('method'):
            x=g.decision_ms.to_numpy();rr=routes[routes.method==method].route_ms.to_numpy();paired=pairs[pairs.method==method].set_index('id')
            changed=g[g.disagrees]
            compute.append(dict(cohort=cohort,method=method,decisions=len(g),disagreement_rate=g.disagrees.mean(),decision_P50=np.quantile(x,.5),decision_P95=np.quantile(x,.95),decision_P99=np.quantile(x,.99),decision_max=x.max(),route_P50=np.quantile(rr,.5),route_P95=np.quantile(rr,.95),route_P99=np.quantile(rr,.99),route_max=rr.max(),
                changed_decisions_in_faster_scenes=int(sum(paired.loc[i].delta_s<-1e-6 for i in changed.id)),changed_decisions_in_slower_scenes=int(sum(paired.loc[i].delta_s>1e-6 for i in changed.id))))
    pd.DataFrame(compute).to_csv(ROOT/'R13_COMPUTE_AND_DISAGREEMENT.csv',index=False,encoding='utf-8-sig')
    hashes={}
    for cohort in ['development','holdout','regression']:
        for p in (ROOT/'results'/cohort).rglob('*'):
            if p.is_file():hashes[p.relative_to(ROOT).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    save('RESULT_HASHES.json',hashes)
    configs={}
    for c in ['development','holdout','regression']:
        m=json.loads((ROOT/'results'/c/'manifest.json').read_bytes())
        configs[c]={cfg['name']:hashlib.sha256(json.dumps(cfg,sort_keys=True,separators=(',',':')).encode()).hexdigest() for cfg in m['configs']}
    save('CONFIG_HASHES.json',configs)
    command=['git','-c','safe.directory=J:/2026B_experiments/q4-r13-routing-study']
    commits=subprocess.check_output(command+['log','--reverse','--format=%h %s','344b455..HEAD','--','r13'],cwd=ROOT.parent,text=True,encoding='utf-8')
    (ROOT/'COMMIT_MAP.md').write_text('# R13阶段提交\n\n审计锚点344b455；下列为生成报告时已完成提交。最终交付提交见交付目录DELIVERY_STATE.json。\n\n```text\n'+commits+'```\n',encoding='utf-8')
    dr=read('development_routes.csv');ar=dr[dr.method=='A1'];dd=read('development_decisions.csv');ee=dd[dd.method=='E-H2'];de=dev[dev.variant=='D'];d0=dev[dev.variant=='R12'];n16delta=de[de.total==16].mean_time_per_source.mean()-d0[d0.total==16].mean_time_per_source.mean()
    rd=rp[(rp.method=='D')&(rp.N==16)];ra=rp[rp.method=='A1']
    table='|集合|方案|全清|均值 s/源|改善%|P95|P99|最大值|归一化方差|CV|\n|---|---|---:|---:|---:|---:|---:|---:|---:|---:|\n'
    for _,v in summary.iterrows():table+=f'|{v.development_or_holdout}|{v.method}|{v.full_clear}/{v.runs}|{v.mean_s_per_source:.3f}|{v.improvement_pct:.3f}|{v.P95:.3f}|{v.P99:.3f}|{v["max"]:.3f}|{v.normalized_variance:.6f}|{v.CV:.6f}|\n'
    text=f'''# Q4 R13路径与外层调度研究：最终交付

**最终决定：KEEP_R12。正式默认仍为7228633的R12。** 本轮没有接入官方接口，也没有启动演练或正式测试。A1保留为独立研究候选，B/C/D/E保留为负结果；未修改Q1–Q3、certified25、误差约束、硬可行域、MEC证书、诊断v1、光学回退和no_signal语义。

## 证据规模和结论

开发128场×7方案=896次；新验证256场×2方案=512次；历史519场×3方案=1557次。合计**2965次本地Engine运行，2965次全清且审计通过**。开发与验证共384个新场景；历史519只能作回归，不能并入新验证平均。已核查可访问散装清单/场景与26个历史压缩包内5550份记录；未发现新集重合。未导出官方真值和嵌套压缩包存在审计范围限制，不宣称与全部不可见历史数据绝对不重合。

A1开发均值改善2.109%，新验证仅{a.improvement_pct:.3f}%。新验证均值差候选减基线为{a.mean_delta:.3f} s/源，场景成对bootstrap 95%区间[{a.mean_delta_ci_low:.3f}, {a.mean_delta_ci_high:.3f}]，跨越0。A1为{int(a.wins)}胜、{int(a.ties)}平、{int(a.losses)}负；最大逐场回退{a.max_regression:.3f} s/源。最大值由{b['max']:.3f}升至{a['max']:.3f} s/源，CV由{b.CV:.6f}升至{a.CV:.6f}。因此既没有达到1%主方案门槛，也不满足0.5%–1%稳定性例外。不能把点估计0.8%写成已证实泛化提速。

{table}

## 对研究问题的逐项回答

1. **静态open-route还有空间。** 既有13108个D1快照的参考gap均值2.1601%、中位0.1141%、P95 8.7683%、最大24.5246%；n≤16是浮点Held–Karp数值最优，大集合只是更强启发式，不是全局证明。A1保留实际R12路线作为候选，逐次断言相同节点集合且不返回更长路线。没有宣称整局不劣。
2. **静态缩短只有部分机会兑现。** 新开发A1的{len(ar)}次路线生成记录中，{100*(ar.route_survival_nodes==0).mean():.2f}%在执行发现节点前就被打断；平均执行计划路程比例{100*ar.fraction_of_planned_route_executed.mean():.2f}%。每发现节点后代码会重新生成路线，所以每份计划执行0或1个节点是该实现的结构。不能把相关快照差距相加、或除以实际整局收益制造“兑现率”。不同策略分叉后不处于相同后验，图03是描述关联，不是因果识别。
3. **确定结束点的B-lite这次不值得采用。** 只在R12最佳local已认证时比较真实清除位置与下一发现节点的尾部路线；其余局部定位保留R12。开发均值反而慢6.08%，并增加移动和测量。证据否定的是这版尾部代理，不是所有end-state方法。
4. **扫描抵扣成立，但接入方式未带来收益。** 8053条历史认证状态复用真实频道顺序、5秒测量、1秒切换，clear不换频道。C1在128场与R12逐动作相同，无信息增益；C2开发慢6.47%。局部确定的扫描义务节省无法代表因发现顺序、清除时机和后验变化产生的整局净效应。
5. **不能认定known16硬释放是退化主因。** 原68个16源场景有65个释放时仍剩节点，说明存在支持测点机会；它本身不是因果证明。D的新开发N16平均变化为{n16delta:+.3f} s/源，整体也未改善，因此当前估计器下的soft release不支持替换。
6. **D的作用范围已严格隔离。** 开发128场中，N<16的D逐动作等于R12；N16确认上限之前的动作前缀也完全相同。历史68个N16场景，D相对R12为{int((rd.delta_s<-1e-6).sum())}胜/{int((abs(rd.delta_s)<=1e-6).sum())}平/{int((rd.delta_s>1e-6).sum())}负，平均差{rd.delta_s.mean():+.3f} s/源。详表单列原16个历史退化案例，不针对它们修参。剩余节点只作可选单次补测，使用后移除，没有强制巡完。
7. **这版两步前瞻不值得计算开销。** E固定K6/H2，普通测量只用当前预测站位，未知诊断/回退终点退回R12；前瞻没有读取隐藏真值或未来实际反馈。开发慢14.00%，决策P95 {ee.decision_ms.quantile(.95):.2f} ms，决策分歧率{100*ee.disagrees.mean():.2f}%。其前缀不包含未来信息增益，尾部代理也不是完整剩余任务价值。不同决策所在场景的胜负已保存，不能把场景胜负分摊为每个不同决策的因果收益。
8. **独立贡献最大的是A1，但未充分泛化。** 它是唯一开发强候选；新验证均值区间仍跨0。历史519中平均差{ra.delta_s.mean():+.3f} s/源仅作回归信息，不改变独立验证决定。
9. **本轮没有有据可用的组合。** 只有A1达到开发门槛，故不组合已STOP的代理。B/C/E有重叠future-cost成分，不把它们堆叠。计价表逐项列出每个成本出现的位置。
10. **确有均值更快但尾部/波动更差。** 新验证A1的P95/P99略好，但max和归一化CV更差；最差成对案例完整轨迹与阶段分解已交付。
11. **不替换7228633 R12。** 后续若继续研究，需要新机制理由和新开发/验证划分；不能根据本次holdout调A1参数再复用这个holdout报泛化成绩。

## 实现与统计口径

A1使用multi-start NN、收敛2-opt和relocate，无在线DP；B-lite/C1/C2/D/E各为独立模块、独立提交。未增加A2、B-full、D-extra、H3或X，因为本轮没有跨过其证据入口。D采用既有诊断分支与fallback估计、1024粒子规划上限；不替代全量真实后验。E是冻结信息的有限前瞻，不是完整POMDP。

源数按10–16分层；仅保留原生生成器中的全向/定向混合场景，没有把人为边缘、聚类压力案例伪装成生成器类别。归一化采用z=(T/N)/同集合均值，样本方差ddof=1，CV=sd(T/N)/mean(T/N)；源数层内另有独立归一化表。所有百分位使用NumPy线性插值；bootstrap以场景为单位，2000次、种子20260912。墙钟由8个CPU进程负载下采集，不加到模拟虚拟时间里。

COMPUTE_COLD_WARM.json另给固定0号案例的新进程首次回放与同进程第二次回放。它不是多个独立冷启动样本，未清空OS/Numba磁盘缓存。官方真实决策截止时间尚未核实，不能据此宣称正式实时部署合格。

## 审计、失败挖掘与图表

每次真实观测和清除继续进行真值包含性审计（仅审计钩子可见真值，策略不可见）、独立动作账本、频道顺序与保证节点义务检查。开发C1/D隔离复核、历史519的R12原始动作/RNG/反馈完全一致性复核均有JSON记录。失败不剔除、不重写。

每个候选的10个最大改善和10个最大回退见各集合extremes.csv；每个最差案例有两套完整轨迹、阶段成本、诊断与回退次数、首次发现时间、known16时间、路线刷新和存活记录。历史16个退化案例见R13_HISTORICAL_16_REGRESSIONS.csv，全部68个N16见R13_HISTORICAL_68_N16.csv。

13张图提供SVG、PDF、PNG及合并PDF。中文宋体，英文数字Times New Roman，字体已嵌入PDF；同一对比图使用一致尺度。图01–12覆盖单模块效果、ECDF、路线兑现、存活、分层、动作权衡、扫描抵扣、known16、计算、路径、回退和证据矩阵；图13突出开发与新验证的差异。每张图的论文位置、用途、为何采用及解释边界见FIGURE_GUIDE.md。最佳展示案例为holdout62，最大回退案例为holdout19，不假称随机代表案例。

## 交付索引

- R13_ALL_METHODS_COMPARISON.csv：全部方案/集合主表；analysis/*_strata.csv：N分层。
- results/development、holdout、regression：冻结场景、完整动作轨迹、每场结果。
- baseline/q4better：7228633冻结源码；strong_route.py、endpoint_cost.py、scan_credit.py、soft_release.py、short_rollout.py：独立研究模块。
- run_study.py：只使用本地Engine的不可覆盖批处理；verify_study.py、check_action_invariance.py：一致性复核。
- R13_PREREGISTRATION_V2.md、R13_COMBINATION_PLAN.md、R13_COST_ACCOUNTING_AUDIT.md：事前规则与计价。
- CONFIG_HASHES.json、RESULT_HASHES.json、各MANIFEST：可复现指纹；COMMIT_MAP.md与交付目录DELIVERY_STATE.json：提交和最终Git状态。

当前分支codex/q4-r13-routing-study；没有推送远端，没有改正式默认配置。最终Git清洁状态由交付快照记录。

**official_calls=0；formal_test_count=0。**
'''
    (ROOT/'R13_FINAL_HANDOFF.md').write_text(text,encoding='utf-8')
    save('R13_PROGRESS.json',dict(stage='COMPLETE',baseline='7228633',development_runs=896,holdout_runs=512,regression_runs=1557,total_local_runs=2965,adoption=decision,official_calls=0,formal_test_count=0,push_status='not_pushed'))
    print(decision,'2965 full/audited',flush=True)
if __name__=='__main__':main()

