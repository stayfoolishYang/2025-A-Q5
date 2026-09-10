"""Assemble engineering results from saved experiments; no simulator access."""
import csv
import json
from pathlib import Path

BASE=Path(__file__).resolve().parent


def table(rows):
    return '\n'.join(['|'+'|'.join(map(str,rows[0]))+'|','|'+'|'.join(['---']*len(rows[0]))+'|']+
                     ['|'+'|'.join(map(str,r))+'|' for r in rows[1:]])


def main():
    root=BASE/'results/diagnostic'
    small=json.loads((root/'paired20/summary.json').read_text())
    big=json.loads((root/'paired100/summary.json').read_text())
    tail=json.loads((root/'paired100/tail_analysis.json').read_text())
    with (root/'paired100/cases.csv').open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
    names=['P4_current','P4_route_only','P4_diagnostic_v1','P4_diagnostic_v2']
    metrics=['mean','median','P90','P95','P99','max']
    b,v=big[names[0]],big[names[2]]
    report=['# Q4诊断恢复：ACCEPT（推荐v1）',
        '推荐以显式配置启用v1作为Q4的替代候选；默认构造器仍保持旧基线，未合并main，未启动任何官方测试。v2保留作实验版本，不优先推荐：它减少少量兜底，但100种子P95/P99未优于v1且计算更慢。',
        '## 改动与保证',
        '`solver.py`仅在原网格触发点增加可关闭诊断入口和目标轨迹。`directional/diagnostic_candidates.py`产生长轴、短轴与侧向候选；`diagnostic_recovery.py`作受限深度1/2/3前瞻及代价门控；`fallback_cost.py`估计兜底代价并对全部原网格点作蛇形排序。`particles.py`只增加可选显存适配分块，原默认路径不变。',
        '覆盖节点、角域裁剪、直径和MEC实现均未修改。真实观测仍通过原FP64几何更新；预测分支不写入真实可行域，粒子只评分。诊断最多3次，失败后完整原网格仍在，因此发现结构与清除证书不变。有限官方时间预算下的普遍完成保证并非本轮实验证明。',
        '`paired_q4.py`保存同种子配置、硬件及源哈希，并由evaluator逐次核对真实目标包含性；`failure_mining.py`保存最差10例；`paired_multi_gpu.py`按独立GPU分配连续种子，独立写盘后合并。详见DIAGNOSTIC_README.md。',
        '## 验证',
        '六项单元测试全部通过：预测不裁剪真实几何/粒子、历史约束重放、网格覆盖不减、CUDA边界与CPU复核排序、关闭诊断复现旧结果、实际触发诊断的同种子确定性。100个基线案例与原batch_v2逐例时间差最大为0。',
        '20种子为0–19，100种子为0–99，均以seed%4分配随机、边界向外、固定极端误差和聚簇场景。每种子四组配置，分别80与400次完整运行；两阶段种子重叠，不能称为120个独立场景。参数在20种子后保持不变，没有进行大范围调参。',
        '## 20种子对照（秒/源）',
        table([['策略','全清除','mean','median','P90','P95','P99','max']]+[[n,f"{small[n]['all_clear']}/20",*[f'{small[n][k]:.2f}' for k in metrics]] for n in names]),
        '## 100种子对照（秒/源）',
        table([['策略','全清除','mean','median','P90','P95','P99','max']]+[[n,f"{big[n]['all_clear']}/100",*[f'{big[n][k]:.2f}' for k in metrics]] for n in names]),
        f"v1相对基线：mean下降{(1-v['mean']/b['mean'])*100:.2f}%，P95下降{(1-v['P95']/b['P95'])*100:.2f}%，P99下降{(1-v['P99']/b['P99'])*100:.2f}%。100种子中有{v['paired_wins']}例更快、{v['paired_losses']}例更慢、{100-v['paired_wins']-v['paired_losses']}例相同，个别退化没有删除。",
        'v1最大退化为seed 3（聚簇）：718.77→847.17秒/源，执行5次诊断检测且仍有1次兜底。随后为seed 83：675.31→718.70，seed 39：666.76→698.91。门控比较的是完整网格代价，无法知道旧顺序是否很早碰到真实目标，因此不保证逐例更快。',
        '## 路程、兜底与动作',
        table([['策略','平均路程km','P95路程km','有兜底案例比例','兜底总次数','每例平均网格点数','光学clear尝试','全部clear尝试','诊断检测','全部检测','换频']]+
            [[n,f"{big[n]['mean_distance']/1000:.2f}",f"{big[n]['P95_distance']/1000:.2f}",f"{big[n]['fallback_rate']:.0%}",big[n]['fallback_count'],f"{big[n]['mean_fallback_grid_points']:.2f}",*[big[n][k] for k in ('optical_clear_attempts','clear_attempts','diagnostic_count','detect_count','switch_count')]] for n in names]),
        '计数为100个案例累计；网格点数是实际进入兜底时生成的全部候选点数，clear尝试数是停止前真正执行次数。两者不混用。',
        '仅改顺序已大幅降低路程和长尾，不能把全部收益归给诊断。与route-only相比，v1进一步减少clear尝试10078→1860、兜底131→9，P95从1209.33降到1169.16秒/源。诊断的最明显增益是降低兜底触发与盲扫次数。',
        '## 保留种子及不确定性',
        f"对未参与20种子检查的80例（20–99），基线P95={tail['comparisons']['P4_diagnostic_v1']['heldout_20plus']['baseline_P95']:.2f}，v1 P95={tail['comparisons']['P4_diagnostic_v1']['heldout_20plus']['variant_P95']:.2f}。",
        f"2000次同种子配对重采样所得v1减基线P95差的95%区间为{tail['comparisons']['P4_diagnostic_v1']['paired_bootstrap_P95_difference_95_interval']}秒/源。它只刻画这组合成场景的经验波动，不代表官方分布或连续场景的统计保证。",
        '## 基线最差10例逐例核查',
        '下表按基线耗时排序，不删除失败或退化。关键频道为该基线案例中移动最长的目标；诊断/兜底次数按全案例计。详细前三个高路程目标在tail_analysis.json，各策略原始记录在worst10_traces。']
    worstrows=[['seed/场景','基线s/源','v1s/源','v2s/源','关键频道/原触发原因','基线→v1兜底次数','基线→v1clear尝试']]
    for case in tail['worst10']:
        variants={r['metrics']['variant']:r for r in case['variants']}
        old=variants['P4_current'];one=variants['P4_diagnostic_v1'];two=variants['P4_diagnostic_v2']
        t=old['largest_travel_targets'][0]
        worstrows.append([f"{case['seed']}/{case['stress']}",*[f"{float(r['metrics']['mean_time_per_source']):.2f}" for r in (old,one,two)],
            str(t['channel'])+'/'+','.join(t['fallback_trigger_reason']),
            old['metrics']['fallback_count']+'→'+one['metrics']['fallback_count'],
            old['metrics']['clear_attempts']+'→'+one['metrics']['clear_attempts']])
    report.append(table(worstrows))
    report.append('基线最差10例的最大路程目标均出现连续无信号触发；这说明恢复接收几何值得优先处理。新序列降低进入网格的频率，蛇形顺序降低仍需盲扫时的折返。seed 17在v1下仍有142次clear尝试，是后续可关注的残余难例；没有继续针对它调参。')
    report.extend(['## 极端事件与运行代价',table([['策略','超过100km的案例','超过100次clear的案例','平均/最大程序墙钟秒']]+
        [[n,sum(float(r['distance'])>100000 for r in rows if r['variant']==n),sum(int(r['clear_attempts'])>100 for r in rows if r['variant']==n),
          f"{sum(float(r['runtime']) for r in rows if r['variant']==n)/100:.3f}/{max(float(r['runtime']) for r in rows if r['variant']==n):.3f}"] for n in names]),
        '程序墙钟来自同一次四进程运行，且部分阶段与CUDA实验并行，属于运行预算记录，不能据此声称独占机器下的严格加速比。',
        '## CUDA与服务器',
        '本机RTX 4060 Laptop GPU经独立worker完成20种子×3配置共60个完整案例，均全清除；各例虚拟耗时、路程、兜底、clear、检测、换频计数与CPU一致。诊断评分在GPU FP32计数后由CPU FP64复核，几何不迁移到GPU。',
        '8卡4090/V100的独立worker代码已提供，使用通用PyTorch FP32操作；未连接这两类服务器，未运行1000+种子服务器实验，不宣称目标硬件已部署成功。',
        '## 版本及结论',
        '20种子运行提交53b7d4e；100种子与CUDA运行提交2f517ed。完整提交号、配置哈希、源文件哈希、Torch/CUDA版本在各manifest。后续提交仅补强测试和汇总交付，求解行为未改。',
        '**ACCEPT：推荐v1替代Q4基线配置。** 保持本次全部案例清除及原几何保证，P95/P99在20种子、100种子及80例保留子集上均有明确改善。v2作为可选对照保留，不因均值小幅更好就升级为推荐默认。未进行新的官方演练，也没有任何正式测试。'])
    (BASE/'DIAGNOSTIC_RESULTS.md').write_text('\n\n'.join(report)+'\n',encoding='utf-8')
    print('Wrote DIAGNOSTIC_RESULTS.md')


if __name__=='__main__':main()
