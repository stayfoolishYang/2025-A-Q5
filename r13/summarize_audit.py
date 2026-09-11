from pathlib import Path
import json,gzip,hashlib
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'results/state_audit'
ARCHIVE=Path('J:/2026B_runs/q4_latest_7228633/cpu519_repeat_20260912')
summary=json.loads((OUT/'SUMMARY.json').read_bytes());gaps=pd.read_csv(OUT/'route_gaps.csv')
cases=pd.read_csv(ARCHIVE/'cases.csv');pairs=pd.read_csv(ARCHIVE/'pairs.csv');reg=pairs[pairs.delta_s_per_source>1e-8]
records=[];snapshot_hashes={};states=[]
for p in sorted(OUT.glob('*.json.gz')):
    snapshot_hashes[p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
    r=json.load(gzip.open(p,'rt',encoding='utf-8'))
    for s in r['certified_states']:
        for c in s['certified']:states.append(dict(seed=r['seed'],time_s=s['time_s'],channel=c['channel'],nodes=len(s['nodes']),scan_credit_s=c['scan_credit_s']))
    if r['seed'] not in set(reg.seed):continue
    current=cases[(cases.id==r['seed'])&(cases.variant=='R12')].iloc[0]
    previous=cases[(cases.id==r['seed'])&(cases.variant=='C')].iloc[0]
    with gzip.open(ARCHIVE/'core/traces'/f'R12_{r["seed"]:04d}.json.gz','rt',encoding='utf-8') as f:trace=json.load(f)
    k=r['known16_release'];t=float(current.known16_time_s)
    rec=dict(seed=r['seed'],total=int(current.total),delta_vs_C_s_per_source=float(reg.set_index('seed').loc[r['seed'],'delta_s_per_source']),confirmed16_s=t,completion_s=float(current.virtual_time_s),after_confirmed16_s=float(current.virtual_time_s)-t,remaining_nodes_at_release=len(k[0]['nodes']) if k else 0,remaining_targets_at_release=len(k[0]['targets']) if k else None)
    for stage in ['active_localization','diagnostic','optical_fallback','certified_clear','discovery']:
        rec['post_known16_'+stage+'_s']=sum(a.get('total_s',0) for a in trace['actions'] if a.get('stage')==stage and a['response']['virtual_time_s']>t)
        rec['whole_stage_delta_'+stage+'_s']=float(current['stage_'+stage+'_s']-previous['stage_'+stage+'_s'])
    rec['movement_delta_m']=float(current.distance-previous.distance);rec['diagnostic_count_delta']=int(current.diagnostic_count-previous.diagnostic_count);rec['fallback_count_delta']=int(current.fallback_count-previous.fallback_count)
    records.append(rec)
pd.DataFrame(records).to_csv(ROOT/'R12_16_SOURCE_REGRESSION_AUDIT.csv',index=False,encoding='utf-8-sig')
credits=pd.DataFrame(states).drop_duplicates(['seed','time_s','channel','nodes']);credits.to_csv(OUT/'certified_scan_credit.csv',index=False,encoding='utf-8-sig')
(ROOT/'STATE_SNAPSHOT_HASHES.json').write_text(json.dumps(snapshot_hashes,indent=2),encoding='utf-8')
parts=[]
for kind,g in gaps.groupby('reference_kind'):
    parts.append(f'|{kind}|{len(g)}|{g.gap.mean()*100:.4f}%|{g.gap.quantile(.95)*100:.4f}%|{g.gap.max()*100:.4f}%|')
md=f'''# R13-A开放路线差距审计

519/519案例严格动作回放完成；每次提交位置逐浮点值一致，粒子RNG状态哈希一致，最终虚拟时间一致。无引擎调用、无官方接口。捕获{len(gaps)}次D1刷新，未把初始route混入D1样本。

|参考方法|快照数|平均差距|P95差距|最大差距|
|---|---:|---:|---:|---:|
{chr(10).join(parts)}

整体均值{gaps.gap.mean()*100:.4f}%，中位数{gaps.gap.median()*100:.4f}%，P95={gaps.gap.quantile(.95)*100:.4f}%，P99={gaps.gap.quantile(.99)*100:.4f}%，最大{gaps.gap.max()*100:.4f}%。差距定义(L_R12-L_ref)/L_ref。

小集合<=16使用Held–Karp开放路径DP，n=1..7与穷举排列逐一核对；这是FP64数值最优而非严格舍入区间证书。大集合使用多首节点NN+2-opt至收敛+relocate，保留R12路线，所以参考不比R12长；它不是全局最优值。不同快照相关，不能当13108个独立病例。

## 决定
**PROCEED_R13A_IMPLEMENTATION**。P95明显超过预注册0.5%，不能触发STOP_R13A_ROUTE_SOLVER。尚未实现在线候选，也没有端到端改善结论。所有路线仍必须访问同一节点集合。

不能将重叠快照的节省秒直接相加解释为整局可兑现收益或上界。逐快照saving_s保留供机制分析，在线路线下一次定位后可能立即失效。

## known16与扫描信用状态
68场16源案例中，65场释放时仍有剩余节点，已保存位置、频道、节点及已知未清目标的硬域和最多1024个只读假设。其余3场未捕获非空释放节点；不虚构支持节点。当前16个退步案例的基线分解见R12_16_SOURCE_REGRESSION_AUDIT.csv，目前不含尚未运行的R13候选列。

认证目标状态去重后{len(credits)}条频道记录，future scan credit按真实current-first频道顺序精确计数；这些值仅反映保持未来扫描义务不变时删除单频道的成本差。它们不是已执行节省，不含未知观测导致的后续调度变化。

## 下一阶段
R13A独立实现并冻结；B必须补齐正常主动测量端点与多动作localize的资格区分；C完成独立调度规则；D用已保存状态验证既有continuation estimator；E先定稿尾部估价并核实现实计算预算。新Development/Holdout尚未生成或运行，不得把519当作新开发集调参。
'''
(ROOT/'R13_ROUTE_GAP_AUDIT.md').write_text(md,encoding='utf-8')
(ROOT/'PATH_PLANNING_BASELINE_AUDIT.md').write_text((ROOT/'R13_BASELINE_AUDIT.md').read_text(encoding='utf-8'),encoding='utf-8')
status=dict(stage='BASELINE_AND_D1_ROUTE_GAP_COMPLETE',baseline='7228633',strict_replay_cases=519,d1_snapshots=len(gaps),r13a='PROCEED_TO_IMPLEMENTATION',r13b='NOT_IMPLEMENTED',r13c='NOT_IMPLEMENTED',r13d='NOT_IMPLEMENTED',r13e='NOT_IMPLEMENTED',development_runs=0,holdout_runs=0,official_calls=0,formal_test_count=0,adoption='KEEP_R12_PENDING_CANDIDATE_EVIDENCE',push_status='not_pushed')
(ROOT/'R13_PROGRESS.json').write_text(json.dumps(status,indent=2),encoding='utf-8')
print(json.dumps(status))
