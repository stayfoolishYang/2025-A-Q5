"""Audit the frozen Q4 workload 3-way experiment; saved evidence only, no solver."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np

from discovery_report import (NODES, STAGES, audit_source_archive, audit_trace, previous_development_gate,
                              quantiles, require, table, write_csv)
from nccp_report import (PHYSICAL, audit_events, classify_run, compare_reference, digest, evaluate_rows,
                         expected_pairs, physical_summary, read_json, sha256)

COHORTS = {'development32': 32, 'holdout128': 128, 'known_counterexamples2': 2}
COHORT_LABELS = {'development32': '新开发集：32 seeds', 'holdout128': '新留出集：128 seeds',
                 'known_counterexamples2': '已知反例：旧 discovery 留出 seed 42、107（单列）'}
ROUTES = ('legacy', 'refresh_after_localize', 'workload_after_localize')
MODES = ('D0', 'D1', 'D2')
LABELS = {'D0': 'D0 原调度', 'D1': 'D1 路程刷新', 'D2': 'D2 workload 刷新'}
PREFIX = '2026B-workload-refresh-20260911:'
ADOPTION = dict(minimum_mean_reduction_fraction=.01, P95_must_not_increase=True,
                P99_must_not_increase=True, all_integrity_checks_must_pass=True, last_discovery_is_auxiliary=True)
METRICS = ('mean_time_per_source', 'virtual_time_s', 'last_source_first_seen_s',
           'last_source_first_seen_per_source_s', 'detect_count', 'switch_count',
           'discovery_measures', 'discovery_travel_s', 'discovery_measure_s', 'discovery_switch_s',
           'final_discovery_measure_s', 'post_last_seen_discovery_s', 'post_all_cleared_discovery_s',
           'distance', *('stage_'+stage+'_s' for stage in STAGES))


def audit_workload_events(trace, mode):
    """Recompute saved route costs and first-hit histograms, not hidden particles."""
    events = [event for target in trace['targets'] for event in target.get('discovery_refresh_events', [])]
    failures, switches = [], 0
    if mode != 'D2' and events:
        failures.append('Non-D2 trace has workload refresh events')
    for ordinal, event in enumerate(events):
        try:
            points, start = np.asarray(event['cached_nodes'], dtype=float), np.asarray(event['start'], dtype=float)
            require(points.ndim == 2 and points.shape[1] == 2 and 1 <= len(points) <= 45
                    and start.shape == (2,) and np.isfinite(points).all() and np.isfinite(start).all(), 'Invalid route coordinates')
            n = len(points)
            require(len(set(map(tuple, points))) == n and set(map(tuple, points)) <= NODES, 'Changed discovery nodes')
            order = event['refreshed_order']
            require(all(type(i) is int for i in order) and sorted(order) == list(range(n)), 'Invalid refreshed permutation')
            movement_m = np.array([np.linalg.norm(p[0]-start)+np.linalg.norm(np.diff(p, axis=0), axis=1).sum()
                                   for p in (points, points[order])])
            workload = np.zeros(2)
            channels = []
            for support in event['supports']:
                channel, count = support['channel'], support['particle_count']
                require(type(channel) is int and 1 <= channel <= 20 and type(count) is int and count > 0,
                        'Invalid support channel/count')
                channels.append(channel)
                fingerprint = support['particle_sha256']
                require(isinstance(fingerprint, str) and len(fingerprint) == 64
                        and all(c in '0123456789abcdef' for c in fingerprint), 'Invalid particle fingerprint')
                histograms = support['first_hit_counts']
                require(len(histograms) == 2, 'Need both first-hit histograms')
                for i, histogram in enumerate(histograms):
                    require(len(histogram) == n+1 and all(type(k) is int and k >= 0 for k in histogram)
                            and sum(histogram) == count, 'Invalid first-hit histogram')
                    workload[i] += 6*float(sum(k*min(j+1, n) for j, k in enumerate(histogram)))/count
            require(channels == sorted(set(channels)), 'Repeated or unstable support channels')
            scores = movement_m/5+workload
            for key, expected in (('movement_s', movement_m/5), ('workload_s', workload), ('score_s', scores)):
                stored = np.asarray(event[key], dtype=float)
                require(stored.shape == (2,) and np.isfinite(stored).all()
                        and np.max(np.abs(stored-expected)) <= 1e-8, 'Incorrect '+key)
            distance_choice = int(movement_m[1] < movement_m[0]-1e-8)
            other = 1-distance_choice
            selected = other if workload[other] < workload[distance_choice]-1e-8 and scores[other] < scores[distance_choice]-1e-8 else distance_choice
            require(type(event['distance_choice']) is int and type(event['selected_choice']) is int
                    and event['distance_choice'] == distance_choice and event['selected_choice'] == selected,
                    'Incorrect distance/score selection')
            switches += int(selected != distance_choice)
        except (KeyError, TypeError, ValueError, ArithmeticError, IndexError) as error:
            failures.append(f'event[{ordinal}]: {error}')
    return dict(passed=not failures, failures=failures, events=len(events), changed_from_D1=switches,
                scope='Saved candidate coordinates and first-hit histogram arithmetic; no particle reconstruction or event-to-action replay')


def validate_plan(root):
    plan, prepared = read_json(root/'PLAN.json'), read_json(root/'PREPARED.json')
    require(plan['schema'] == 'workload-3way-v1' and plan['prefix'] == PREFIX, 'Wrong experiment schema/prefix')
    require(prepared['plan_sha256'] == sha256(root/'PLAN.json') and prepared['planned_runs'] == 486
            and prepared['new_runs'] == 480 and prepared['known_runs'] == 6 and plan['adoption'] == ADOPTION
            and plan['formal_runs'] == prepared['formal_runs'] == 0, 'Root freeze/count/scope mismatch')
    require(plan['all_cohorts_frozen_before_candidate_results'] is True
            and set(plan['cohorts']) == set(prepared['manifests']) == set(COHORTS), 'Not a simultaneous 3-cohort freeze')
    seeds = plan['seeds']
    require(len(seeds) == 160 and len({s['seed_hex'] for s in seeds}) == 160
            and all(s['seed'] == s['derivation_index'] == i
                    and s['seed_hex'] == hashlib.sha256((PREFIX+str(i)).encode()).hexdigest()
                    for i, s in enumerate(seeds)), 'New seed derivation/identity mismatch')
    known = plan['known_seeds']
    require(len(known) == 2, 'Need the two predefined known counterexamples')
    for i, old_seed in enumerate((42, 107)):
        expected = hashlib.sha256(('2026B-discovery-scheduling-20260911:'+str(old_seed+32)).encode()).hexdigest()
        require(known[i]['seed'] == i and known[i]['source_seed'] == old_seed
                and known[i]['source_cohort'] == 'discovery_20260911/holdout128'
                and known[i]['source_derivation_index'] == old_seed+32
                and known[i]['seed_hex'] == known[i]['source_seed_hex'] == expected,
                'Known-counterexample source mapping mismatch')
    require(not {s['seed_hex'] for s in seeds} & {s['seed_hex'] for s in known}, 'Known examples leaked into new cohorts')
    configs = plan['configs']
    require(len(configs) == 3 and len({c['name'] for c in configs}) == 3
            and tuple(c.get('discovery_route', 'legacy') for c in configs) == ROUTES,
            'Need ordered D0/D1/D2 configs')
    frozen = lambda c: {k: v for k, v in c.items() if k not in ('name', 'discovery_route', 'discovery_channels')}
    require(all(frozen(c) == frozen(configs[0]) and c.get('discovery_channels', 'legacy') == 'legacy'
                and c.get('clearance_point', 'mec_center') == 'mec_center' for c in configs),
            'Changes outside the frozen node-order surrogate')
    for cohort, n in COHORTS.items():
        require(plan['cohorts'][cohort]['n'] == n and plan['cohorts'][cohort]['runs'] == n*3
                and sha256(root/cohort/'manifest.json') == prepared['manifests'][cohort], 'Cohort freeze binding mismatch')
    return plan, prepared


def compare_known_reference(root, seed, config, row, trace, scene):
    """Four D0/D1 comparisons are evidence reuse, not extra simulator runs."""
    folder = root/'reference_discovery'
    manifest_path = folder/'manifest.json'
    manifest = read_json(manifest_path)
    old_seed = seed['source_seed']
    scene_path = folder/'scenes'/f'q4_{old_seed:04d}.json'
    trace_path = folder/'q4/traces'/f'{config["name"]}_{old_seed:04d}.json.gz'
    reference = read_json(trace_path)
    require(manifest['cohort'] == 'holdout128' and manifest['seeds'][old_seed]['seed_hex'] == seed['seed_hex']
            and config in manifest['configs']['4'], 'Reference manifest/config identity mismatch')
    require(read_json(scene_path) == scene and digest(scene) == manifest['scene_hashes'][scene_path.name]
            and reference['scene_file'] == 'scenes/'+scene_path.name, 'Reference scene changed')
    old_row = reference['row']
    require(old_row['seed'] == old_seed and old_row['seed_hex'] == seed['seed_hex']
            and old_row['config_hash'] == digest(config) and old_row['scene_hash'] == digest(scene)
            and old_row['source_hash'] == digest(manifest['source_hashes']), 'Reference trace identity/hash mismatch')
    failures = compare_reference(row, trace, old_row, reference)
    failures += [key+'_mismatch' for key in ('targets', 'stages') if trace[key] != reference[key]]
    return dict(passed=not failures, failures=failures, source_seed=old_seed, trace_sha256=sha256(trace_path),
                scope='Exact PHYSICAL/actions/targets/stages; local seed, source hash, and wall runtime may differ'), [manifest_path, scene_path, trace_path]


def load_cohort(root, cohort, plan, prepared):
    folder, n = root/cohort, COHORTS[cohort]
    manifest = read_json(folder/'manifest.json')
    subset = (plan['known_seeds'] if cohort == 'known_counterexamples2' else
              plan['seeds'][:32] if cohort == 'development32' else plan['seeds'][32:])
    require(manifest['schema'] == 'recovered-benchmark-v1' and manifest['cohort'] == cohort
            and manifest['configs'] == {'4': plan['configs']}
            and manifest['seeds'] == [dict(s, seed=i) for i, s in enumerate(subset)]
            and manifest['source_hashes'] == plan['source_hashes'] and manifest['git_commit'] == plan['git_commit'],
            'Manifest seed/config/source identity mismatch')
    require(manifest['plan_hash'] == plan['cohorts'][cohort]['plan_hash'] == digest({k: manifest[k]
            for k in ('seeds', 'configs', 'source_hashes', 'scene_hashes')}), 'Cohort plan hash mismatch')
    require(manifest['formal_tests'] == 0 and manifest['limits'] == {'real_s': 1200, 'virtual_s': 360000},
            'Changed scope or execution budget')
    completion = read_json(folder/'completion.json')
    require(completion['completed_jobs'] == n*3, 'Cohort incomplete; do not summarize partial performance')
    configs = manifest['configs']['4']
    names = {f'{c["name"]}_{i:04d}.json' for c in configs for i in range(n)}
    require({p.name for p in (folder/'q4/rows').glob('*.json')} == names, 'Missing or unexpected raw rows')
    require({p.name for p in (folder/'q4/traces').glob('*.json.gz')} <= {name+'.gz' for name in names},
            'Unexpected raw traces')
    cases, raw_rows, certificates, details = [], [], {}, []
    evidence = [folder/'manifest.json', folder/'completion.json', folder/'q4/acceptance.json']
    for seed in manifest['seeds']:
        index = seed['seed']
        scene_path = folder/'scenes'/f'q4_{index:04d}.json'
        scene = read_json(scene_path)
        require(digest(scene) == manifest['scene_hashes'][scene_path.name]
                and scene['generator_seed_hex'] == seed['seed_hex'] and scene['problem_no'] == 4, 'Scene identity/hash mismatch')
        evidence.append(scene_path)
        for mode, config in zip(MODES, configs):
            variant = config['name']
            row_path, trace_path = folder/'q4/rows'/f'{variant}_{index:04d}.json', folder/'q4/traces'/f'{variant}_{index:04d}.json.gz'
            row = read_json(row_path)
            identity = dict(seed=index, seed_hex=seed['seed_hex'], problem=4, variant=variant,
                            total=len(scene['jammers']), config_hash=digest(config), scene_hash=digest(scene),
                            source_hash=digest(manifest['source_hashes']), device='cpu', clearance_point='mec_center')
            require(all(row.get(k) == v for k, v in identity.items()), 'Raw row identity/config/source mismatch')
            raw_rows.append(row)
            result = dict(row, cohort=cohort, mode=mode, sample_scope='known_counterexample' if cohort == 'known_counterexamples2' else 'new_seed',
                          derivation_index=seed.get('derivation_index'), source_seed=seed.get('source_seed'),
                          source_cohort=seed.get('source_cohort'), row_path=str(row_path.resolve()), row_sha256=sha256(row_path),
                          scene_path=str(scene_path.resolve()), scene_file_sha256=sha256(scene_path), trace_path=str(trace_path.resolve()))
            detail = dict(seed=index, variant=variant, mode=mode)
            evidence.append(row_path)
            try:
                trace = read_json(trace_path)
                evidence.append(trace_path)
                require(trace['row'] == row and trace['scene_file'] == 'scenes/'+scene_path.name
                        and all(k in row for k in PHYSICAL), 'Trace/row/physical evidence mismatch')
                # The reused auditor checks channel order, not route selection.
                # Real D2 config/hash is verified above; all three use legacy channels.
                metrics, discovery = audit_trace(trace, row, scene, {'discovery_channels': 'legacy'})
                certificate = audit_events(trace, row, 'mec_center')
                workload = audit_workload_events(trace, mode)
                certificates[index, variant] = certificate
                result.update(metrics, trace_sha256=sha256(trace_path), workload_refresh_events=workload['events'],
                              workload_changed_from_D1=workload['changed_from_D1'],
                              audit_passed=discovery['passed'] and certificate['passed'] and workload['passed'])
                detail.update(discovery=discovery, certificate=certificate, workload=workload, passed=result['audit_passed'])
                if cohort == 'known_counterexamples2' and mode in ('D0', 'D1'):
                    reference, paths = compare_known_reference(root, seed, config, row, trace, scene)
                    evidence.extend(paths)
                    result['audit_passed'] &= reference['passed']
                    detail.update(reference=reference, passed=result['audit_passed'])
            except (ValueError, KeyError, TypeError, OSError, ArithmeticError, IndexError) as error:
                result['audit_passed'] = False
                detail.update(passed=False, error=str(error))
            cases.append(result)
            details.append(detail)
    acceptance = evaluate_rows(raw_rows, expected_pairs=expected_pairs(range(n), [c['name'] for c in configs]),
                               baseline_name=configs[0]['name'])['acceptance']
    require(acceptance == read_json(folder/'q4/acceptance.json'), 'Stored acceptance differs from recomputation')
    summaries = {}
    for mode, config in zip(MODES, configs):
        raw = [r for r in raw_rows if r['variant'] == config['name']]
        valid = [r for r in cases if r['mode'] == mode and r['audit_passed'] and classify_run(r)['valid_full_clear']]
        summaries[mode] = dict(variant=config['name'], physical=physical_summary(raw, certificates, n),
                              metrics={key: quantiles([r.get(key) for r in valid]) for key in METRICS})
    return cases, dict(passed=acceptance['accept'] is True and all(d['passed'] for d in details),
                       acceptance=acceptance, summaries=summaries, case_audits=details,
                       manifest_sha256=prepared['manifests'][cohort]), evidence


def comparisons(cases):
    grouped = defaultdict(dict)
    for row in cases:
        key = row['cohort'], row['seed']
        require(row['mode'] not in grouped[key], 'Duplicate comparison identity')
        grouped[key][row['mode']] = row
    pairs = []
    for (cohort, seed), group in sorted(grouped.items()):
        require(set(group) == set(MODES), 'Incomplete 3-way case')
        for reference, candidate in (('D0', 'D1'), ('D1', 'D2')):
            a, b = group[reference], group[candidate]
            require(a['seed_hex'] == b['seed_hex'] and a['scene_hash'] == b['scene_hash'], 'Unpaired scene')
            valid = a['audit_passed'] and b['audit_passed'] and all(classify_run(r)['valid_full_clear'] for r in (a, b))
            pair = dict(cohort=cohort, seed=seed, seed_hex=a['seed_hex'], source_seed=a.get('source_seed'),
                        derivation_index=a.get('derivation_index'), contrast=candidate+'-'+reference,
                        reference=reference, candidate=candidate, valid_pair=valid,
                        reference_status=classify_run(a)['run_status'], candidate_status=classify_run(b)['run_status'])
            for key in METRICS:
                left, right = a.get(key), b.get(key)
                pair[key+'_delta'] = right-left if valid and left is not None and right is not None else None
            for key, field in (('mean_time_per_source', 'comparison'), ('last_source_first_seen_s', 'last_discovery_comparison')):
                delta = pair[key+'_delta']
                pair[field] = 'invalid' if delta is None else 'win' if delta < -1e-6 else 'loss' if delta > 1e-6 else 'tie'
            pairs.append(pair)
    return pairs


def paired_summary(pairs):
    result = {}
    for contrast in ('D1-D0', 'D2-D1'):
        rows = [p for p in pairs if p['contrast'] == contrast]
        valid = [p for p in rows if p['valid_pair']]
        def worst(metric):
            candidates = [p for p in valid if p[metric+'_delta'] is not None]
            return max(candidates, key=lambda p: p[metric+'_delta'], default=None)
        result[contrast] = dict(planned_pairs=len(rows), valid_pairs=len(valid), invalid_pairs=len(rows)-len(valid),
                               time_comparisons=dict(Counter(p['comparison'] for p in rows)),
                               last_discovery_comparisons=dict(Counter(p['last_discovery_comparison'] for p in rows)),
                               metrics={key: quantiles([p[key+'_delta'] for p in valid]) for key in METRICS},
                               worst_time=worst('mean_time_per_source'), worst_last_discovery=worst('last_source_first_seen_s'))
    return result


def adoption_gate(cohorts, passed, final):
    if not final:
        return dict(evaluated=False, criteria=ADOPTION, decision='Development/known integrity only; no tuning')
    a, b = [cohorts['holdout128']['summaries'][mode]['physical'] for mode in ('D1', 'D2')]
    available = all(a[k] is not None and b[k] is not None for k in ('mean', 'P95', 'P99')) and a['mean'] > 0
    reduction = 1-b['mean']/a['mean'] if available else None
    checks = dict(all_integrity_checks_pass=passed,
                  mean_reduction_at_least_one_percent=available and reduction >= .01,
                  P95_not_increased=available and b['P95'] <= a['P95'],
                  P99_not_increased=available and b['P99'] <= a['P99'])
    return dict(evaluated=True, criteria=ADOPTION, checks=checks, mean_reduction_fraction=reduction,
                passed=all(checks.values()), decision='PREDECLARED_THRESHOLD_MET' if all(checks.values()) else 'STOP_D2_NO_PARAMETER_SWEEP')


def markdown(audit, cases):
    lines = ['# Q4 workload-aware refresh：冻结三方案配对', '',
             'D0 原调度；D1 仅按剩余完整路长刷新；D2 只改变刷新排序 surrogate。MEC、原频道顺序、45 个节点及每节点全部未清频道保留。', '',
             f'门禁通过：{audit["passed"]}；最终新留出报告：{audit["final_holdout_report"]}；正式测试 0；本报告启动 solver 0。', '',
             '新开发 32 与新留出 128 在候选运行前同时冻结，均为确定性设计种子，不作 IID 或官方分布推断。已知反例 2 例只作单列回归，不并入新 160 seeds。', '']
    if not audit['passed']:
        lines += ['**存在失败或证据不一致：以下成功子集统计只供诊断，禁止据其作性能结论；全部失败保留在 CASES.csv/AUDIT.json。**', '']
    for cohort, data in audit['cohorts'].items():
        summaries = data['summaries']
        lines += ['## '+COHORT_LABELS[cohort], '',
                  '### 全清除与整局虚拟耗时（s/源）', '',
                  table(['方案', '全清/计划', '均值', 'P50', 'P95', 'P99', 'max', '异常', '协议失败', '超时'],
                        [[LABELS[mode], f'{p["full_clear_count"]}/{p["planned_count"]}',
                          *[p[k] for k in ('mean', 'P50', 'P95', 'P99', 'max', 'exception_count', 'protocol_count', 'timeout_count')]]
                         for mode in MODES for p in [summaries[mode]['physical']]]), '',
                  '### 最后真实源首次发现时间（s，不除以源数）', '',
                  table(['方案', '均值', 'P50', 'P95', 'P99', 'max'],
                        [[LABELS[mode]]+[summaries[mode]['metrics']['last_source_first_seen_s'][k]
                          for k in ('mean', 'P50', 'P95', 'P99', 'max')] for mode in MODES]), '',
                  '### 各阶段与操作（每例均值）', '',
                  table(['方案', '整局 s', '发现 s', '主动定位 s', '诊断 s', '光学兜底 s', '证书清除 s', '测量次', '切频次'],
                        [[LABELS[mode]]+[summaries[mode]['metrics'][k]['mean'] for k in
                          ('virtual_time_s', *('stage_'+s+'_s' for s in STAGES), 'detect_count', 'switch_count')]
                         for mode in MODES]), '',
                  '### 配对差：候选减参考（负值更小）', '']
        for contrast, pair in data['paired'].items():
            counts, last = pair['time_comparisons'], pair['last_discovery_comparisons']
            lines += [f'**{contrast}**：有效 {pair["valid_pairs"]}/{pair["planned_pairs"]}；'
                      f'整局胜/平/负 {counts.get("win",0)}/{counts.get("tie",0)}/{counts.get("loss",0)}；'
                      f'最后发现更早/平/更晚 {last.get("win",0)}/{last.get("tie",0)}/{last.get("loss",0)}。', '',
                      table(['指标', '配对均差', 'P95 Δ', 'P99 Δ', '最大 Δ'],
                            [[key]+[pair['metrics'][key][k] for k in ('mean', 'P95', 'P99', 'max')]
                             for key in ('mean_time_per_source', 'virtual_time_s', 'last_source_first_seen_s',
                                         'detect_count', 'switch_count', *('stage_'+s+'_s' for s in STAGES))]), '']
            for label, field, metric in (('整局最大配对 Δ（正数为退步）', 'worst_time', 'mean_time_per_source'),
                                         ('最后发现最大配对 Δ（正数为延迟）', 'worst_last_discovery', 'last_source_first_seen_s')):
                worst = pair[field]
                if worst:
                    lines += [f'{label}：local seed={worst["seed"]}，原反例 seed={worst.get("source_seed")}，'
                              f'Δ={worst[metric+"_delta"]:.6f}；seed_hex=`{worst["seed_hex"]}`。', '']
        if cohort == 'known_counterexamples2':
            lines += ['已知反例只列原案例结果，不宣称新留出收益：', '',
                      table(['原 discovery seed', '方案', '整局 s/源', '最后发现 s', '状态'],
                            [[r['source_seed'], r['mode'], r['mean_time_per_source'], r.get('last_source_first_seen_s'), r['run_status']]
                             for r in cases if r['cohort'] == cohort]), '']
    gate = audit['adoption_gate']
    lines += ['## 预先规定的 D2 对 D1 留出门槛', '',
              '整局 s/源均值至少下降 1%，P95 与 P99 均不增加，且全部完整性检查通过。最后发现时刻只作辅助风险，不强迫逐例单调。', '',
              f'判定：`{gate["decision"]}`。达到门槛也不自动修改默认策略；未达标停止本 D2，不继续扫参数。', '']
    if gate['evaluated']:
        lines += [f'留出均值相对下降：{gate["mean_reduction_fraction"]:.6%}。' if gate['mean_reduction_fraction'] is not None else '缺少可用留出均值。', '',
                  table(['门槛', '通过'], [[key, value] for key, value in gate['checks'].items()]), '']
    lines += ['## 解释与证据范围', '',
              '胜平负均采用 ±1e-6 平局阈值，最大 Δ 保留符号；负数表示该组最差配对仍更快。所有分位数均为线性插值的经验分位数：方案自身的耗时分位数与配对差 Δ 的分位数是不同统计量。分位数只描述本组成功且审计通过的案例；整局状态与失败计数分开保留。已知反例仅 2 例，不据其分位数作长尾推断。', '',
              '最后首次发现时刻从原动作的 direction/near 重建；真源集合只用于事后选择指标分母。发现后的继续扫描不代表可在线删除的义务。工作量 surrogate 不是真实未来清除时间，也不构成整局支配或最后发现不延迟证明。', '',
              '复用 discovery_report.audit_trace 检查实际频道序列、45 节点、首次发现、阶段和动作账本及真源位于证书多边形；仅传入已验证的 legacy 频道模式，原始完整配置和源码仍单独校验 SHA。复用 audit_events 对每个证书做 FP64 与精确有理数硬检查，安全半径不加容差。', '',
              'D2 事件独立重算两条已保存候选的移动费用、每频道 first-hit histogram 的 W=6×E[min(first_hit+1,N)]、总评分及严格切换条件。N=never-hit 仍按 N 次扫描计，当前预测命中测量也计入。粒子 SHA 只标识来源；未保存全体粒子坐标，故不声称重建了每个命中事件，也不把事件算术检查等同在线调用逐动作重放。', '',
              '两例已知反例中的 D0/D1 共 4 条新轨迹与保存的旧 discovery 轨迹比较：动作、targets、stages 与物理指标须精确一致；新局部索引、源码 hash 与现实运行时间不作相等要求。这是既有证据对照，不额外计作 4 次新运行。', '',
              '开发门禁只判完整性，不根据开发或已知反例的性能调参。160 个新种子对应 480 次完整运行，与 2 个已知反例对应的 6 次运行分开；本报告不修改默认策略或论文。', '']
    return '\n'.join(lines)


def plot_holdout(cases, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    rows = {(r['seed'], r['mode']): r for r in cases if r['cohort'] == 'holdout128'}
    require(set(rows) == {(s, m) for s in range(128) for m in MODES}, 'Incomplete plotting cohort')
    plt.rcParams.update({'font.sans-serif': ['Microsoft YaHei', 'Noto Sans CJK SC', 'SimHei', 'DejaVu Sans'],
                         'axes.unicode_minus': False, 'axes.spines.top': False, 'axes.spines.right': False,
                         'font.size': 9, 'svg.fonttype': 'path', 'figure.facecolor': 'white'})
    folder = output/'figures'
    folder.mkdir()
    fig, axes = plt.subplots(1, 2, figsize=(9, 5.2))
    fig.subplots_adjust(left=.08, right=.98, bottom=.24, top=.79, wspace=.30)
    for ax, key, title, unit in zip(axes, ('mean_time_per_source', 'last_source_first_seen_s'),
                                   ('整局耗时', '最后真实源首次发现'), ('s/源', 's')):
        x, y = [np.array([rows[s, mode][key] for s in range(128)], dtype=float) for mode in ('D1', 'D2')]
        delta, maximum = y-x, float(max(x.max(), y.max()))*1.05
        ax.plot([0, maximum], [0, maximum], color='#767676', ls='--', lw=1)
        ax.scatter(x, y, s=19, alpha=.65, color='#0F4D92', linewidths=0)
        ax.set(xlim=(0, maximum), ylim=(0, maximum), xlabel=f'D1 路程刷新（{unit}）',
               ylabel=f'D2 workload 刷新（{unit}）', title=title)
        ax.set_aspect('equal', adjustable='box')
        ax.grid(color='#E2E8F0', lw=.5)
        wins, losses = int((delta < -1e-6).sum()), int((delta > 1e-6).sum())
        ax.text(.04, .96, f'均值差 {delta.mean():+.3f} {unit}\n胜/平/负 {wins}/{128-wins-losses}/{losses}\n最大 Δ {delta.max():+.3f} {unit}',
                transform=ax.transAxes, va='top', fontsize=8,
                bbox={'facecolor': 'white', 'edgecolor': 'none', 'alpha': .9})
    fig.suptitle('Q4 新留出 128 seeds：D2 对 D1 配对', y=.97, fontsize=13, fontweight='bold')
    fig.text(.08, .055, '虚线下方为 D2 更快；Δ=D2−D1，保留全部尾部。\n本地确定性种子，非官方成绩；已知反例 2 例未混入。', fontsize=9)
    for extension in ('png', 'svg'):
        fig.savefig(folder/f'holdout_D2_vs_D1.{extension}', dpi=220, bbox_inches='tight')
    plt.close(fig)
    (folder/'README.md').write_text(
        f'# D2 对 D1 留出配对图\n\n数据来自 `{output.resolve()}/CASES.csv` 与 `PAIRS.csv`，'
        '经完整动作/证书审计后生成；每方案 128 个相同的新确定性种子。两例已知反例不进入此图。\n\n'
        '左图为整局虚拟 s/源；右图为最后真实源首次 direction/near 返回时间（s）。'
        '每点是同种子配对，差值 D2−D1；负值更快，±1e-6 计为平局。坐标包含全部数据，不截尾。'
        '本地非官方证据，不假定 IID，也不承诺整局普遍不劣。\n\n'
        'PNG 220 dpi；SVG 字形转路径，可跨机器分享。输入 SHA256 见上级 EVIDENCE_MANIFEST.json，'
        'CSV 和图片自身 SHA256 见上级 ARTIFACT_MANIFEST.json。\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cohort', choices=('development32',), help='Development + known-counterexample integrity gate only')
    args = parser.parse_args()
    root, output = args.root.resolve(), args.output.resolve()
    require(not output.exists(), 'Choose a new output directory; preserve existing reports')
    plan, prepared = validate_plan(root)
    archive, archive_path = audit_source_archive(root, plan)
    evidence = [root/'PLAN.json', root/'PREPARED.json', archive_path]
    gate = None
    if args.cohort is None:
        gate, paths = previous_development_gate(root)
        require(read_json(root/'development_audit/AUDIT.json')['cohorts']['known_counterexamples2']['passed'] is True,
                'Missing known-counterexample integrity gate')
        evidence.extend(paths)
    selected = ('development32', 'known_counterexamples2') if args.cohort else tuple(COHORTS)
    cases, cohorts = [], {}
    for name in selected:
        rows, cohort, paths = load_cohort(root, name, plan, prepared)
        cases.extend(rows)
        cohorts[name] = cohort
        evidence.extend(paths)
    pairs = comparisons(cases)
    for name, cohort in cohorts.items():
        cohort['paired'] = paired_summary([p for p in pairs if p['cohort'] == name])
    passed = all(c['passed'] for c in cohorts.values())
    audit = dict(schema='workload-3way-audit-v1', passed=passed, final_holdout_report=args.cohort is None,
                 performance_conclusion_allowed=args.cohort is None and passed, scope='local performance evidence; no adoption decision',
                 new_cases=sum(COHORTS[c]*3 for c in selected if c != 'known_counterexamples2'), known_cases=6,
                 formal_tests=0, solver_runs_started=0, input_root=str(root), cohorts=cohorts,
                 source_archive=archive, development_gate=gate, report_script_sha256=sha256(__file__),
                 freeze=dict(git_commit=plan['git_commit'], reference_commit=plan['reference_commit'],
                             plan_sha256=sha256(root/'PLAN.json'), source_hash=digest(plan['source_hashes']), prefix=PREFIX))
    audit['adoption_gate'] = adoption_gate(cohorts, passed, args.cohort is None)
    output.mkdir(parents=True)
    (output/'AUDIT.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    write_csv(output/'CASES.csv', cases)
    write_csv(output/'PAIRS.csv', pairs)
    (output/'RESULTS.md').write_text(markdown(audit, cases), encoding='utf-8')
    if audit['performance_conclusion_allowed']:
        plot_holdout(cases, output)
    scripts = {name: sha256(Path(__file__).with_name(name)) for name in ('workload_report.py', 'discovery_report.py', 'nccp_report.py')}
    (output/'EVIDENCE_MANIFEST.json').write_text(json.dumps(dict(script_sha256=sha256(__file__), scripts=scripts,
        files=[dict(path=str(p.resolve()), sha256=sha256(p), bytes=p.stat().st_size) for p in dict.fromkeys(evidence)]),
        ensure_ascii=False, indent=2), encoding='utf-8')
    (output/'ARTIFACT_MANIFEST.json').write_text(json.dumps(dict(solver_runs_started=0,
        files=[dict(path=p.relative_to(output).as_posix(), sha256=sha256(p), bytes=p.stat().st_size)
               for p in sorted(output.rglob('*')) if p.is_file()]),
        ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(output=str(output), passed=passed, new_cases=audit['new_cases'], known_cases=6,
                          performance_conclusion_allowed=audit['performance_conclusion_allowed'])))


if __name__ == '__main__':
    main()
