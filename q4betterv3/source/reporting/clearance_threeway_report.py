"""Audit the segment extension against the two preserved NCCP experiment arms.

Read-only inputs; no solver, replay, simulator or formal-test call is made.
The original 1424 runs are referenced, not regenerated or copied as new runs.
"""
import argparse
import csv
import json
from pathlib import Path
import sys

import numpy as np

from nccp_report import (PHYSICAL, audit_events, digest, evaluate_rows, expected_pairs,
                         physical_summary, read_json, sha256)
from nccp_summary import COHORTS, PROBLEMS, load_complete, require, table, fmt

BASE = Path(__file__).resolve().parents[1]
STAGES = ('discovery', 'active_localization', 'diagnostic', 'optical_fallback', 'certified_clear')
LABELS = {'mec_center': 'MEC', 'nccp': 'NCCP', 'segment_entry': '沿原路提前清除'}


def csv_rows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def verified_pair(folder, summary_file, data_file):
    summary = read_json(folder/summary_file)
    require(summary.get('passed') is True, f'{folder}尚未通过')
    require(summary['plan_sha256'] == sha256(folder/'PLAN.json'), f'{folder}计划哈希不符')
    require(summary['cases_sha256'] == sha256(folder/data_file), f'{folder}案例哈希不符')
    return summary, read_json(folder/'PLAN.json')


def prerequisites(root, parents):
    replay_dir, snapshot_dir = root/'amendment_replay', root/'snapshot_audit'
    replay, replay_plan = verified_pair(replay_dir, 'AUDIT.json', 'cases.jsonl')
    require(replay['expected'] == replay['completed'] == 1424 and not replay['failures']
            and replay['source_unchanged'] is True, '修订后历史动作回放未完整通过')
    replay_rows = [json.loads(line) for line in (replay_dir/'cases.jsonl').read_text(encoding='utf-8').splitlines()]
    identity = lambda row: (row['cohort'], int(row['problem']), int(row['seed']), row['variant'])
    expected = {(cohort, int(q), seed['seed'], cfg['name'])
                for cohort, parent in parents.items() for q in PROBLEMS
                for seed in parent['manifest']['seeds'] for cfg in parent['manifest']['configs'][q]}
    require(len(replay_rows) == len(expected) and {identity(row) for row in replay_rows} == expected,
            '回放行缺失或重复')
    require(len(replay_plan['jobs']) == len(expected)
            and {identity(row) for row in replay_plan['jobs']} == expected, '回放计划不匹配')
    for job in replay_plan['jobs']:
        cohort, q, seed, variant = identity(job)
        original = parents[cohort]['manifest']
        config = next(cfg for cfg in original['configs'][str(q)] if cfg['name'] == variant)
        path = root/cohort/f'q{q}/traces/{variant}_{seed:04d}.json.gz'
        require(job['config'] == config and Path(job['trace']).resolve() == path.resolve(),
                '回放计划配置或输入路径与本批不符')
    for row in replay_rows:
        cohort, q, seed, variant = identity(row)
        path = root/cohort/f'q{q}/traces/{variant}_{seed:04d}.json.gz'
        require(row.get('passed') is True and Path(row['trace']).resolve() == path.resolve()
                and row['trace_sha256'] == sha256(path), '回放引用的原始轨迹不匹配')
    snapshot, snapshot_plan = verified_pair(snapshot_dir, 'SUMMARY.json', 'cases.csv')
    snapshots = csv_rows(snapshot_dir/'cases.csv')
    count = sum(parent['audit']['problems'][q]['baseline_metrics']['polygon_certified_count']
                for parent in parents.values() for q in PROBLEMS)
    require(snapshot['n'] == len(snapshots) == count, '固定快照未涵盖全部旧基线证书')
    keys = {(r['cohort'], int(r['problem']), int(r['seed']), int(r['channel']), int(r['ordinal'])) for r in snapshots}
    require(len(keys) == len(snapshots), '快照重复')
    expected_inputs = {str((root/cohort/f'q{q}/traces/{parent["manifest"]["configs"][q][0]["name"]}_{seed["seed"]:04d}.json.gz').resolve())
                       for cohort, parent in parents.items() for q in PROBLEMS for seed in parent['manifest']['seeds']}
    actual_inputs = {str(Path(p).resolve()): value for p, value in snapshot_plan['inputs_sha256'].items()}
    require(set(actual_inputs) == expected_inputs, '快照输入集合不匹配')
    require(all(sha256(path) == value for path, value in actual_inputs.items()), '快照输入哈希失配')
    # Bind each snapshot to an actual preserved certificate event; a passed
    # producer flag alone does not establish that it audited the right inputs.
    expected_events = {}
    for cohort, parent in parents.items():
        for q in PROBLEMS:
            config = parent['manifest']['configs'][q][0]
            require(config.get('clearance_point', 'mec_center') == 'mec_center', '快照原方案不是MEC基线')
            for seed in parent['manifest']['seeds']:
                path = root/cohort/f'q{q}/traces/{config["name"]}_{seed["seed"]:04d}.json.gz'
                trace = read_json(path)
                require(trace['row']['seed'] == seed['seed'] and trace['row']['seed_hex'] == seed['seed_hex']
                        and trace['row']['problem'] == int(q) and trace['row']['variant'] == config['name'],
                        '快照输入trace身份不匹配')
                actions = trace['actions']
                for target in trace['targets']:
                    for ordinal, event in enumerate(target.get('certified_clearance_events', [])):
                        matches = [i for i,a in enumerate(actions) if a['path'] == '/clear'
                            and a['channel'] == target['channel'] and a['position'] == event['point']
                            and a['response']['virtual_time_s'] == event['time_after']]
                        require(len(matches) == 1 and event['selector'] == 'mec_center', '快照原证书与clear动作不唯一匹配')
                        index = matches[0]
                        following = next((a for a in actions[index+1:] if a.get('position') is not None), None)
                        key = cohort,int(q),seed['seed'],target['channel'],ordinal
                        expected_events[key] = dict(action_index=index, total=trace['row']['total'],
                            vertex_count=len(event['polygon']), mec_radius_stored=event['mec_radius'],
                            baseline_terminal_distance_m=float(np.linalg.norm(np.array(event['start'])-event['mec_center'])),
                            next_action=following)
    require(keys == set(expected_events), '快照与原trace证书事件集合不一致')
    for row in snapshots:
        require(row['cohort'] in COHORTS and row['problem'] in PROBLEMS
                and 0 <= int(row['seed']) < len(parents[row['cohort']]['manifest']['seeds']), '快照身份错误')
        event = expected_events[row['cohort'],int(row['problem']),int(row['seed']),int(row['channel']),int(row['ordinal'])]
        require(all(int(row[field]) == event[field] for field in ('action_index','total','vertex_count'))
                and float(row['mec_radius_stored']) == event['mec_radius_stored']
                and float(row['baseline_terminal_distance_m']) == event['baseline_terminal_distance_m']
                and (json.loads(row['next_action']) if row['next_action'] else None) == event['next_action'],
                '快照行没有绑定相同原证书/下一动作')
        for mode in ('nccp', 'segment'):
            require(float(row[mode+'_rho_m']) <= 19.999 and float(row[mode+'_saving_s']) >= 0.,
                    '快照覆盖或局部非负条件失败')
        twoleg = row['segment_fixed_next_twoleg_delta_m']
        require(not twoleg or float(twoleg) <= 1e-9, 'segment 固定下一站两段校验失败')
    next_counts = {}
    for q in PROBLEMS:
        group = [row for row in snapshots if row['problem'] == q]
        next_counts[q] = sum(bool(row['next_action']) for row in group)
        saved = snapshot['problems'][q]
        require(saved['n'] == len(group), '快照分题数量不符')
        for field, stats in saved['metrics'].items():
            values = np.array([float(row[field]) for row in group])
            require(np.isfinite(values).all(), '快照含非有限指标')
            observed = dict(mean=float(values.mean()), p50=float(np.median(values)),
                            p95=float(np.percentile(values,95)), maximum=float(values.max()))
            require(all(np.isclose(stats[key], value, rtol=1e-10, atol=1e-10)
                        for key,value in observed.items()), '快照统计与原CSV不符')
        for mode in ('nccp', 'segment'):
            require(saved[mode+'_fixed_next_regressions'] == sum(bool(row[mode+'_fixed_next_twoleg_delta_m'])
                    and float(row[mode+'_fixed_next_twoleg_delta_m']) > 1e-9 for row in group)
                    and saved[mode+'_fallbacks'] == sum(row[mode+'_fallback'] == 'True' for row in group),
                    '快照下一转场或回退计数不符')
            require(sum(bool(row[mode+'_fixed_next_twoleg_delta_m']) for row in group) == next_counts[q],
                    '两段指标分母与实际下一动作数不一致')
    snapshot = dict(snapshot, fixed_next_denominators_from_csv=next_counts)
    return replay, replay_plan, snapshot, snapshot_plan


def load_runs(root, parents, replay_plan, snapshot_plan):
    extension = root/'segment_extension'
    prepared = read_json(extension/'PREPARED.json')
    runs, summaries, evidence, details = [], {}, [], []
    source = None
    for name, parent in parents.items():
        folder = extension/name
        manifest = read_json(folder/'manifest.json')
        prior = parent['manifest']
        require(prepared['cohorts'][name]['manifest_sha256'] == sha256(folder/'manifest.json')
                and manifest['parent_manifest_sha256'] == sha256(root/name/'manifest.json'), '扩展与父清单哈希不符')
        require(manifest['seeds'] == prior['seeds'] and manifest['scene_hashes'] == prior['scene_hashes'],
                '第三方案改变了种子或场景')
        require(manifest['plan_hash'] == digest({key: manifest[key] for key in
                ('seeds', 'configs', 'source_hashes', 'parent_manifest_sha256')}), '第三方案计划哈希错误')
        n = len(manifest['seeds'])
        require(read_json(folder/'completion.json')['completed_jobs'] == n*2, '第三方案运行未齐')
        require(manifest.get('formal_tests') == 0, '第三方案证据范围不符')
        if source is None:
            source = manifest['source_hashes']
        require(source == manifest['source_hashes'], '第三方案两cohort核心不同')
        replay_sources = {key.replace('\\','/'): value for key,value in replay_plan['source_hashes'].items()}
        require(all(replay_sources.get(key.removeprefix('solver/')) == value
                    for key, value in source.items() if key.startswith('solver/')), '回放与新方案核心指纹不同')
        require(all(prior['source_hashes'].get(key) == value for key, value in source.items()
                    if key.startswith('engine/')), '新方案改变了模拟器')
        require(snapshot_plan['source_hashes'][str(BASE/'geometry.py')] == source['solver/geometry.py'],
                '快照与新方案几何版本不同')
        evidence.extend([folder/'manifest.json', folder/'completion.json'])
        for q in PROBLEMS:
            configs = manifest['configs'][q]
            old = prior['configs'][q][0]
            require(len(configs) == 1 and configs[0] == dict(old, name=old['name']+'_segment_entry',
                    clearance_point='segment_entry'), 'segment 修改了站位以外配置')
            for origin, config, frozen in [(root/name, c, prior) for c in prior['configs'][q]] + [(folder, configs[0], manifest)]:
                variant = config['name']
                selector = config.get('clearance_point', 'mec_center')
                rows, certs = [], {}
                expected_files = {f'{variant}_{seed:04d}.json' for seed in range(n)}
                require({p.name for p in (origin/f'q{q}/rows').glob(variant+'_[0-9][0-9][0-9][0-9].json')} == expected_files,
                        f'{name} Q{q} {variant}行集合错误')
                require({p.name for p in (origin/f'q{q}/traces').glob(variant+'_[0-9][0-9][0-9][0-9].json.gz')}
                        == {p[:-5]+'.json.gz' for p in expected_files}, '轨迹文件集合错误')
                for seed in range(n):
                    row_path = origin/f'q{q}/rows/{variant}_{seed:04d}.json'
                    trace_path = origin/f'q{q}/traces/{variant}_{seed:04d}.json.gz'
                    row, trace = read_json(row_path), read_json(trace_path)
                    scene_name = f'q{q}_{seed:04d}.json'
                    scene = read_json(origin/'scenes'/scene_name)
                    identity = dict(seed=seed, problem=int(q), variant=variant,
                        seed_hex=frozen['seeds'][seed]['seed_hex'], config_hash=digest(config),
                        scene_hash=digest(scene), source_hash=digest(frozen['source_hashes']), total=len(scene['jammers']))
                    require(all(row.get(key) == value for key, value in identity.items())
                            and all(key in row for key in PHYSICAL) and trace['row'] == row, '行/轨迹身份或内容错误')
                    require(digest(scene) == frozen['scene_hashes'][scene_name]
                            and scene['generator_seed_hex'] == row['seed_hex'] and scene['problem_no'] == int(q), '场景哈希或身份错误')
                    cert = audit_events(trace, row, selector)
                    require(cert['passed'], f'{name} Q{q} {seed} {selector}证书失败：{cert["failures"]}')
                    certs[seed, variant] = cert
                    rows.append(row)
                    details.append(dict(cohort=name, problem=q, seed=seed, selector=selector, certificate=cert))
                    runs.append(dict(cohort=name, selector=selector, source_seed=frozen['seeds'][seed].get('source_seed'),
                        origin='new_segment_run' if selector == 'segment_entry' else 'preserved_original_run',
                        row_path=str(row_path.resolve()), row_sha256=sha256(row_path),
                        trace_path=str(trace_path.resolve()), trace_sha256=sha256(trace_path), **row))
                metrics = physical_summary(rows, certs, n)
                require(metrics['full_clear_count'] == n and not any(metrics[field] for field in
                        ('exception_count', 'protocol_count', 'timeout_count', 'invalid_evidence_count')), '方案未全清除或存在失败')
                summaries[name, q, selector] = metrics
                if selector == 'segment_entry':
                    acceptance = read_json(origin/f'q{q}/acceptance.json')
                    evaluated = evaluate_rows(rows, expected_pairs(range(n), [variant]), variant)['acceptance']
                    require(acceptance == evaluated and acceptance['accept'] is True, '第三方案 acceptance 未通过或过期')
                    saved = csv_rows(origin/f'q{q}/cases.csv')
                    mapped = {(int(r['seed']), r['variant']): r for r in saved}
                    require(len(saved) == len(mapped) == n and all(all(mapped.get((r['seed'],r['variant']),{}).get(k)
                        == ('' if v is None else str(v)) for k,v in r.items()) for r in rows), '第三方案 cases.csv 不匹配原row')
                    evidence.extend([origin/f'q{q}'/file for file in ('acceptance.json','cases.csv','summary.json','stage_profile.json')])
    return runs, summaries, details, evidence


def paired(runs):
    by_key = {(r['cohort'],str(r['problem']),r['seed'],r['selector']): r for r in runs}
    pairs = []
    for cohort in COHORTS:
        for q in PROBLEMS:
            seeds = sorted({r['seed'] for r in runs if r['cohort']==cohort and str(r['problem'])==q})
            for seed in seeds:
                for baseline, candidate in [('mec_center','nccp'),('mec_center','segment_entry'),('nccp','segment_entry')]:
                    a,b = by_key[cohort,q,seed,baseline],by_key[cohort,q,seed,candidate]
                    difference = b['mean_time_per_source']-a['mean_time_per_source']
                    pairs.append(dict(cohort=cohort, problem=q, seed=seed, seed_hex=a['seed_hex'],
                        baseline=baseline, candidate=candidate, baseline_s_per_source=a['mean_time_per_source'],
                        candidate_s_per_source=b['mean_time_per_source'], delta_s_per_source=difference,
                        comparison='win' if difference < -1e-6 else 'loss' if difference > 1e-6 else 'tie',
                        total_time_delta_s=b['virtual_time_s']-a['virtual_time_s'], distance_delta_m=b['distance']-a['distance'],
                        certificate_travel_delta_m=b['polygon_clear_travel_m']-a['polygon_clear_travel_m'],
                        **{stage+'_delta_s':b['stage_'+stage+'_s']-a['stage_'+stage+'_s'] for stage in STAGES}))
    return pairs


def markdown(root, summaries, pairs, snapshot, shadow):
    lines = ['# 三种保证清除站位：Q4 为主，Q3 对照',
        '原 MEC/NCCP 两方案 1424 次运行沿用原始冻结证据；本轮只新跑 segment_entry 712 次。修订后核心的 1424 条旧动作精确回放用来检查兼容性，不算新场景成绩。固定证书快照是纯几何计算，不算完整案例。',
        '开发 100 与原留出 256 分开统计。第三方案是在看到 NCCP 结果后增加，后者对第三方案只是复用的固定评测集，不能称为新的独立留出验证。全程本地恢复演练引擎，无官方正式测试。',
        '本报告通过的门禁仅允许描述现有性能，不自动授予本地研发 ACCEPT。测试、shadow 行为不变与冻结边界仍须完整验收。']
    for q in PROBLEMS:
        lines.append(f'## Q{q} 完整案例')
        rows=[]
        for cohort in COHORTS:
            for mode in LABELS:
                s=summaries[cohort,q,mode]
                rows.append([cohort,LABELS[mode],f'{s["n"]}/{s["planned_count"]}',
                    *[fmt(s[k]) for k in ('mean','P50','P95','P99','max')],s['exception_count'],s['protocol_count']])
        lines.append(table(['队列','方案','全清除','均值s/源','P50','P95','P99','最大','异常','协议失败'],rows))
        rows=[]
        for cohort in COHORTS:
            for a,b in [('mec_center','nccp'),('mec_center','segment_entry'),('nccp','segment_entry')]:
                group=[r for r in pairs if r['cohort']==cohort and r['problem']==q and r['baseline']==a and r['candidate']==b]
                worst=max(group,key=lambda r:r['delta_s_per_source'])
                rows.append([cohort,f'{LABELS[b]}−{LABELS[a]}',fmt(np.mean([r['delta_s_per_source'] for r in group]),signed=True),
                    '/'.join(str(sum(r['comparison']==label for r in group)) for label in ('win','tie','loss')),
                    fmt(max(0.,worst['delta_s_per_source'])),worst['seed'] if worst['delta_s_per_source']>0 else '无正回退'])
        lines.append(table(['队列','配对差','平均Δs/源','胜/平/负','最大回退s/源','回退seed'],rows))
        rows=[]
        for cohort in COHORTS:
            for mode in LABELS:
                s=summaries[cohort,q,mode]
                rows.append([cohort,LABELS[mode],*[fmt(s[k]) for k in ('total_observed_virtual_time_s','total_observed_distance_m',
                    'total_polygon_clear_travel_m','mean_polygon_clear_travel_m_per_source','same_state_counterfactual_saving_m')]])
        lines.append(table(['队列','方案','总虚拟秒','全程总米','证书段总米','证书段均米/源','自身状态局部节省米'],rows))
        rows=[]
        for cohort in COHORTS:
            for mode in LABELS:
                s=summaries[cohort,q,mode]
                rows.append([cohort,LABELS[mode],*[int(s[k]) for k in ('current_position_certified_case_count',
                    'current_position_certified_count','near_certified_count','polygon_zero_move_count','zero_move_clear_count','nccp_fallback_count')]])
        lines.append(table(['队列','方案','已原地安全案例','对应事件','near零移动','多边形零移动','总零移动','选择器回退MEC'],rows))
    lines += ['## 同一证书快照：直接收益、计算费用与下一转场',
        '快照全部来自原 MEC 基线，固定 polygon、机器狗位置和原轨迹下一动作；开发/256集合在此合并只统计几何状态，不作为整局效果。精确有理数支持圆用于证明给定 FP64 顶点的真实 MEC；平方根界为数值显示，另加旧浮点圆心相对精确圆心的误差。CPU 毫秒是本机单次墙钟，包含精确认证、不含支持圆审计，未隔离系统负载，不当作稳定设备加速比。']
    for q in PROBLEMS:
        s=snapshot['problems'][q]
        eligible = snapshot['fixed_next_denominators_from_csv'][q]
        nccp_rate = f'{100*s["nccp_fixed_next_regressions"]/eligible:.4f}%' if eligible else '不适用'
        segment_rate = f'{100*s["segment_fixed_next_regressions"]/eligible:.4f}%' if eligible else '不适用'
        lines.append(f'Q{q} 共 {s["n"]} 个固定快照，其中 {eligible} 个确有下一动作。NCCP 两段变长 {s["nccp_fixed_next_regressions"]} 个（{nccp_rate}）；segment 为 {s["segment_fixed_next_regressions"]} 个（{segment_rate}）。两段回退率分母仅为有下一动作的快照，数值门槛1e-9 m不放宽19.999 m安全认证。')
        lines.append(table(['指标','均值','P50','P95','最大'],[[key,*[fmt(value[k],precision=6) for k in ('mean','p50','p95','maximum')]] for key,value in s['metrics'].items()]))
    lines += ['## 如何使用结果',
        'NCCP 理想投影只最小化当前目标的最后移动；浮点实现保证安全和相对 MEC 局部不劣，可保守回退。segment 沿原线段提前停下，精确几何下对同一个固定下一站还有两段不劣性质；自由重调度仍无整局保证。',
        '实际两方案证书段差、自身状态反事实局部节省与全程路程差是不同账本。局部直接节时最多3.9998秒的理论界以精确MEC为前提；更紧界还需精确半径与支持点。均值改善不能掩盖尾部分位数或最大配对回退。原Q4 seed210与Q3 seed7的完整案例解释见父目录HOLDOUT_CASE_NOTES.md。',
        '原NCCP默认不开启，不因小幅均值改善自动改主配置。三方案的数值及所有回退保留于CSV，采取与否应结合全清除完整性、尾部、现实计算开销与完整验收，不对这些固定种子继续调参。',
        '## Shadow 与验收状态',
        ('提供的 shadow SUMMARY 门禁通过；其覆盖范围是预先选定的回放案例及捕获状态，不能外推为全部未来调用。' if shadow else '本报告未提供通过的 shadow SUMMARY，动作不变验收待补。'),
        '完整本地研发 ACCEPT 由主任务结合测试、恢复行为、覆盖/v1冻结和正式测试零次等证据单独判定，本脚本不自动签发。',
        f'原始证据根目录：`{root}`。`AUDIT.json`记录三个输入门禁及逐事件证书；`EVIDENCE_MANIFEST.json`记录输入路径和SHA256；`THREEWAY_CASES.csv`含引用的原row/trace路径与哈希，`THREEWAY_PAIRS.csv`含三组配对及五阶段差。']
    return '\n\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--shadow-summary',type=Path)
    args=parser.parse_args()
    root=args.root.resolve(); output=(args.output or root/'threeway').resolve()
    try:
        require(not output.exists(), '输出目录已存在，拒绝覆盖旧报告')
        parents=load_complete(root)
        replay,replay_plan,snapshot,snapshot_plan=prerequisites(root,parents)
        runs,summaries,details,evidence=load_runs(root,parents,replay_plan,snapshot_plan)
        require(len(runs)==2136 and sum(r['origin']=='new_segment_run' for r in runs)==712,'三方案计数不符')
        comparisons=paired(runs)
        shadow=read_json(args.shadow_summary) if args.shadow_summary else None
        if shadow:
            require(shadow.get('passed') is True and shadow.get('all_replays_exact') is True
                    and shadow.get('all_states_captured') is True and shadow.get('source_unchanged') is True,
                    '提供的shadow证据尚未通过')
        content=markdown(root,summaries,comparisons,snapshot,shadow)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(f'未生成三方案最终结果：{exc}',file=sys.stderr); return 2
    output.mkdir(parents=True,exist_ok=False)
    def write_json(path,value):
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    for filename,rows in [('THREEWAY_CASES.csv',runs),('THREEWAY_PAIRS.csv',comparisons)]:
        with (output/filename).open('x',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(dict.fromkeys(k for row in rows for k in row)))
            writer.writeheader();writer.writerows(rows)
    write_json(output/'AUDIT.json',dict(passed=True,scope='performance evidence only; not local R&D ACCEPT',
        original_runs_referenced=1424,new_segment_runs=712,formal_runs=0,
        replay_gate=replay,snapshot_gate=snapshot,shadow_gate=shadow,
        summaries={'/'.join(key):value for key,value in summaries.items()},certificates=details))
    (output/'NCCP_RESULTS.md').write_text(content,encoding='utf-8')
    evidence += [root/'segment_extension/PREPARED.json',root/'amendment_replay/AUDIT.json',root/'amendment_replay/PLAN.json',
                 root/'amendment_replay/cases.jsonl',root/'snapshot_audit/SUMMARY.json',root/'snapshot_audit/PLAN.json',root/'snapshot_audit/cases.csv']
    for cohort in parents.values():evidence.extend(cohort['evidence'])
    evidence += [root/file for file in ('DEVELOPMENT_CASE_NOTES.md','HOLDOUT_CASE_NOTES.md','CLEARANCE_SHADOW_AUDIT.md') if (root/file).is_file()]
    if args.shadow_summary:evidence.append(args.shadow_summary.resolve())
    write_json(output/'EVIDENCE_MANIFEST.json',dict(script_sha256=sha256(__file__),input_root=str(root),
        files=[dict(path=str(p.resolve()),sha256=sha256(p),bytes=p.stat().st_size) for p in sorted(set(evidence))]))
    write_json(output/'ARTIFACT_MANIFEST.json',dict(files=[dict(path=p.name,sha256=sha256(p),bytes=p.stat().st_size)
        for p in sorted(output.iterdir()) if p.is_file()],solver_runs_started=0))
    print(output/'NCCP_RESULTS.md');return 0


if __name__=='__main__':
    raise SystemExit(main())
