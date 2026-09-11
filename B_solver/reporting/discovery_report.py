"""Read-only audit of the frozen Q4 discovery 2x2 experiment; never runs Solver."""
import argparse
from collections import Counter, defaultdict
import csv
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
import zipfile

import numpy as np

from nccp_report import (PHYSICAL, audit_events, classify_run, digest, evaluate_rows,
                         expected_pairs, physical_summary, read_json, sha256)

COHORTS = {'development32': (0, 32), 'holdout128': (32, 128)}
NODES = {(float(x), float(y)) for x in range(-2100, 2101, 700)
         for y in range(-2100, 2101, 700) if x*x+y*y <= 2800**2}
STAGES = ('discovery', 'active_localization', 'diagnostic', 'optical_fallback', 'certified_clear')
LABELS = {(0, 0): '原配置', (1, 0): '仅刷新节点', (0, 1): '仅未知频道优先', (1, 1): '两者组合'}
METRICS = ('mean_time_per_source', 'last_source_first_seen_s',
           'last_source_first_seen_per_source_s', 'final_discovery_measure_s',
           'post_last_seen_discovery_s', 'post_all_cleared_discovery_s',
           'stage_discovery_s', 'discovery_travel_s', 'discovery_measure_s',
           'discovery_switch_s', 'discovery_measures', 'distance')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def flags(config):
    route, channels = config.get('discovery_route', 'legacy'), config.get('discovery_channels', 'legacy')
    require(route in ('legacy', 'refresh_after_localize') and channels in ('legacy', 'unknown_first'),
            'Unknown scheduling option')
    return int(route != 'legacy'), int(channels != 'legacy')


def quantiles(values):
    values = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    if not values:
        return dict(n=0, mean=None, P50=None, P95=None, P99=None, max=None)
    return dict(n=len(values), mean=float(np.mean(values)), P50=float(np.percentile(values, 50)),
                P95=float(np.percentile(values, 95)), P99=float(np.percentile(values, 99)), max=max(values))


def point_in_convex_polygon_exact(point, polygon):
    """Use exact rationals for the stored polygon and the native integer source."""
    vertices = [[Fraction(float(x)) for x in v] for v in polygon]
    if not vertices or any(not min(v[k] for v in vertices) <= point[k] <= max(v[k] for v in vertices) for k in (0, 1)):
        return False
    signs = [(b[0]-a[0])*(point[1]-a[1])-(b[1]-a[1])*(point[0]-a[0])
             for a, b in zip(vertices, vertices[1:]+vertices[:1])]
    return bool(signs) and (all(x >= 0 for x in signs) or all(x <= 0 for x in signs))


def audit_trace(trace, row, scene, config):
    """Reconstruct coverage and discovery times using actions, not producer totals."""
    failures, first, cleared, groups = [], {}, set(), []
    totals = defaultdict(lambda: defaultdict(float))
    categories = defaultdict(lambda: defaultdict(float))
    source = {j['channel']: j for j in scene['jammers']}
    require(len(source) == len(scene['jammers']), 'Repeated native source channel')
    actions = trace['actions']
    require(actions and actions[0]['path'] == '/enter', 'Missing enter action')
    time_before, position, channel = 0., (0., 0.), 1
    first_index, clear_times, discovery = {}, [], []
    measure_count = switch_count = clear_count = 0
    for index, action in enumerate(actions):
        response = action['response']
        after = response['virtual_time_s']
        if response.get('accepted') is not True or not math.isfinite(after) or after < time_before:
            failures.append(f'action[{index}]: rejected/nonfinite/reversed time')
        if action['path'] in ('/measure', '/clear'):
            point, c = tuple(action['position']), action['channel']
            require(len(point) == 2 and all(math.isfinite(x) for x in point), 'Invalid action position')
            travel = math.dist(position, point)
            switched = int(action['path'] == '/measure' and c != channel)
            measured = 5 if action['path'] == '/measure' else 0
            clearing = (5 if response.get('clear_result') == 'success' else 3) if action['path'] == '/clear' else 0
            if abs((after-time_before)-(travel/5+switched+measured+clearing)) > 1.1e-6:
                failures.append(f'action[{index}]: physical time ledger')
            for field, expected in (('travel_m', travel), ('travel_s', after-time_before-switched-measured-clearing), ('switch_s', switched),
                                    ('measure_s', measured), ('clear_s', clearing), ('total_s', after-time_before)):
                if abs(float(action.get(field, -1))-expected) > 1.1e-6:
                    failures.append(f'action[{index}]: {field}')
            for field in ('travel_m', 'travel_s', 'switch_s', 'measure_s', 'clear_s', 'total_s'):
                totals[action['stage']][field] += action[field]
            if action['path'] == '/measure':
                measure_count += 1
                switch_count += switched
                known = c in first
                if action['stage'] == 'discovery':
                    if not groups or groups[-1]['point'] != point:
                        ordered = [channel]+[x for x in range(1, 21) if x != channel]
                        if flags(config)[1]:
                            ordered = ordered[:1]+[x for x in ordered[1:] if x not in first]+[x for x in ordered[1:] if x in first]
                        groups.append(dict(point=point, expected=[x for x in ordered if x not in cleared], channels=[]))
                    groups[-1]['channels'].append(c)
                    discovery.append((index, action))
                    category = 'known_actual' if known else ('unseen_actual' if c in source else 'absent_channel')
                    for field, value in (('count', 1), ('measure_s', measured), ('switch_s', switched)):
                        categories[category][field] += value
                result = response.get('measure_result')
                if result not in ('no_signal', 'direction', 'near'):
                    failures.append(f'action[{index}]: invalid measurement result')
                if result in ('direction', 'near') and not known:
                    first[c], first_index[c] = after, index
                channel = c
            else:
                clear_count += 1
                if response.get('clear_result') not in ('success', 'no_target_in_range'):
                    failures.append(f'action[{index}]: invalid clear result')
                if response.get('clear_result') == 'success':
                    if c in cleared or c not in source:
                        failures.append(f'action[{index}]: repeated/non-source clear')
                    cleared.add(c)
                    clear_times.append(after)
            position = point
        time_before = after
    for group in groups:
        if group['channels'] != group['expected']:
            failures.append(f'node {group["point"]}: missing/repeated/channel-order mismatch')
    if len(groups) != 45 or {g['point'] for g in groups} != NODES:
        failures.append('45-node set/count mismatch')
    if actions[-1]['path'] != '/exit':
        failures.append('missing exit')
    if set(first) != set(source) or cleared != set(source):
        failures.append('not all true sources discovered/cleared')
    targets = {target['channel']: target for target in trace['targets']}
    if len(targets) != len(trace['targets']):
        failures.append('duplicate target channel')
    for c in range(1, 21):
        if targets.get(c, {}).get('first_seen_time') != first.get(c):
            failures.append(f'channel {c}: first_seen_time mismatch')
        if c in first:
            action = actions[first_index[c]]
            if targets[c].get('first_seen_position') != action['position']:
                failures.append(f'channel {c}: first_seen_position mismatch')
    containment = 0
    for target in trace['targets']:
        for event in target.get('certified_clearance_events', []):
            c = target['channel']
            if c not in source:
                failures.append('certificate on non-source channel')
                continue
            point = [Fraction(source[c]['x_um'], 1000000), Fraction(source[c]['y_um'], 1000000)]
            if not point_in_convex_polygon_exact(point, event['polygon']):
                failures.append(f'channel {c}: true source outside stored certificate polygon')
            containment += 1
    for stage in STAGES:
        if abs(totals[stage]['total_s']-float(row['stage_'+stage+'_s'])) > 1.1e-6:
            failures.append('stage total mismatch: '+stage)
        for field in ('travel_m', 'travel_s', 'switch_s', 'measure_s', 'clear_s', 'total_s'):
            if abs(totals[stage][field]-trace['stages'][stage][field]) > 1.1e-6:
                failures.append('stage record mismatch: '+stage+'/'+field)
    for field, observed in (('virtual_time_s', time_before), ('detect_count', measure_count),
                            ('switch_count', switch_count), ('clear_attempts', clear_count),
                            ('distance', sum(v['travel_m'] for v in totals.values()))):
        if abs(float(row[field])-observed) > 1.1e-6:
            failures.append('row ledger mismatch: '+field)
    last = max(first[c] for c in source) if set(source) <= set(first) else None
    last_index = max(first_index[c] for c in source) if last is not None else None
    after_seen = [a for i, a in discovery if last_index is not None and i > last_index]
    after_clear = [a for _, a in discovery if clear_times and a['response']['virtual_time_s'] > max(clear_times)]
    metrics = dict(first_source_first_seen_s=min(first.values()) if first else None,
                   last_source_first_seen_s=last,
                   last_source_first_seen_per_source_s=last/len(source) if last is not None else None,
                   final_discovery_measure_s=discovery[-1][1]['response']['virtual_time_s'] if discovery else None,
                   post_last_seen_discovery_s=sum(a['total_s'] for a in after_seen) if last is not None else None,
                   post_all_cleared_discovery_s=sum(a['total_s'] for a in after_clear) if cleared == set(source) else None,
                   post_last_seen_discovery_measures=len(after_seen), post_all_cleared_discovery_measures=len(after_clear),
                   discovery_nodes=len(groups), discovery_measures=len(discovery),
                   discovery_travel_s=totals['discovery']['travel_s'],
                   discovery_measure_s=totals['discovery']['measure_s'],
                   discovery_switch_s=totals['discovery']['switch_s'])
    for category in ('known_actual', 'unseen_actual', 'absent_channel'):
        for field in ('count', 'measure_s', 'switch_s'):
            metrics[category+'_'+field] = categories[category][field]
    return metrics, dict(passed=not failures, failures=failures, node_count=len(groups),
                         channel_obligation_count=len(discovery), true_source_polygon_checks=containment)


def load_cohort(root, cohort, plan, prepared):
    folder = root/cohort
    manifest = read_json(folder/'manifest.json')
    start, n = COHORTS[cohort]
    require(sha256(folder/'manifest.json') == prepared['manifests'][cohort], 'Prepared manifest hash mismatch')
    require(manifest['cohort'] == cohort and manifest['configs']['4'] == plan['configs']
            and set(manifest['configs']) == {'4'} and manifest['source_hashes'] == plan['source_hashes']
            and manifest['git_commit'] == plan['git_commit'],
            'Manifest identity/config/source mismatch')
    require(manifest['plan_hash'] == plan['cohorts'][cohort]['plan_hash'] == digest({k:manifest[k]
            for k in ('seeds', 'configs', 'source_hashes', 'scene_hashes')}), 'Cohort plan hash mismatch')
    require(manifest['seeds'] == [dict(s, seed=i) for i, s in enumerate(plan['seeds'][start:start+n])], 'Cohort seed mapping')
    require(manifest['formal_tests'] == 0 and manifest['limits'] == {'real_s':1200, 'virtual_s':360000}, 'Scope/budget changed')
    completion = read_json(folder/'completion.json')
    require(completion['completed_jobs'] == n*4, 'Cohort not complete; no partial performance report')
    require(plan['cohorts'][cohort]['n'] == n and plan['cohorts'][cohort]['runs'] == n*4, 'Cohort planned size')
    configs = manifest['configs']['4']
    require(len(configs) == 4 and {flags(c) for c in configs} == set(LABELS), 'Not a complete 2x2 design')
    baseline = next(c for c in configs if flags(c) == (0, 0))
    frozen = lambda c: {k:v for k,v in c.items() if k not in ('name','discovery_route','discovery_channels')}
    require(all(frozen(c) == frozen(baseline) and c.get('clearance_point','mec_center') == 'mec_center' for c in configs),
            'Changes outside the two scheduling flags')
    required_rows = {f'{c["name"]}_{i:04d}.json' for c in configs for i in range(n)}
    require({p.name for p in (folder/'q4/rows').glob('*.json')} == required_rows, 'Raw row set incomplete/unexpected')
    cases, certs, details, evidence, raw_rows = [], {}, [], [], []
    evidence += [folder/'manifest.json', folder/'completion.json', folder/'q4/acceptance.json']
    for seed in manifest['seeds']:
        scene_path = folder/'scenes'/f'q4_{seed["seed"]:04d}.json'
        scene = read_json(scene_path)
        require(digest(scene) == manifest['scene_hashes'][scene_path.name]
                and scene['generator_seed_hex'] == seed['seed_hex'] and scene['problem_no'] == 4, 'Scene hash/identity')
        for config in configs:
            variant, index = config['name'], seed['seed']
            row_path = folder/'q4/rows'/f'{variant}_{index:04d}.json'
            trace_path = folder/'q4/traces'/f'{variant}_{index:04d}.json.gz'
            row = read_json(row_path)
            identity = dict(seed=index, seed_hex=seed['seed_hex'], problem=4, variant=variant,
                            total=len(scene['jammers']), config_hash=digest(config), scene_hash=digest(scene),
                            source_hash=digest(manifest['source_hashes']))
            require(all(row.get(k) == v for k,v in identity.items()), 'Raw row identity/hash mismatch')
            raw_rows.append(row)
            result = dict(row, cohort=cohort, derivation_index=seed['derivation_index'],
                          route_refresh=flags(config)[0], unknown_first=flags(config)[1],
                          row_path=str(row_path.resolve()), row_sha256=sha256(row_path),
                          trace_path=str(trace_path.resolve()), scene_path=str(scene_path.resolve()),
                          scene_file_sha256=sha256(scene_path))
            detail = dict(seed=index, variant=variant)
            try:
                trace = read_json(trace_path)
                require(trace['row'] == row and trace['scene_file'] == 'scenes/'+scene_path.name, 'Trace/row/scene mismatch')
                require(all(k in row for k in PHYSICAL), 'Missing physical row evidence')
                metrics, discovery_check = audit_trace(trace, row, scene, config)
                certificate = audit_events(trace, row, 'mec_center')
                certs[index, variant] = certificate
                result.update(metrics, trace_sha256=sha256(trace_path),
                              audit_passed=discovery_check['passed'] and certificate['passed'])
                detail.update(discovery=discovery_check, certificate=certificate, passed=result['audit_passed'])
            except (ValueError, KeyError, TypeError, OSError, ArithmeticError) as error:
                result['audit_passed'] = False
                detail.update(passed=False, error=str(error))
            cases.append(result)
            details.append(detail)
    acceptance = read_json(folder/'q4/acceptance.json')
    require({row['device'] for row in raw_rows} == {'cpu'}, 'This frozen experiment requires CPU-only cases')
    recomputed = evaluate_rows(raw_rows, expected_pairs=expected_pairs(range(n), [c['name'] for c in configs]),
                               baseline_name=configs[0]['name'])['acceptance']
    require(acceptance == recomputed, 'Stored acceptance differs from recomputation')
    summaries = {}
    for config in configs:
        rows = [r for r in raw_rows if r['variant'] == config['name']]
        selected = [c for c in cases if c['variant'] == config['name'] and c['audit_passed'] and classify_run(c)['valid_full_clear']]
        summaries[config['name']] = dict(flags=list(flags(config)), physical=physical_summary(rows,certs,n),
            metrics={key:quantiles([r.get(key) for r in selected]) for key in METRICS})
    passed = acceptance.get('accept') is True and all(d['passed'] for d in details)
    return cases, dict(passed=passed, acceptance=acceptance, summaries=summaries, case_audits=details,
                       manifest_sha256=sha256(folder/'manifest.json')), evidence


def comparisons(cases):
    pairs, factorial = [], []
    grouped = defaultdict(dict)
    for row in cases:
        grouped[row['cohort'],row['seed']][row['route_refresh'],row['unknown_first']] = row
    for (cohort, seed), rows in grouped.items():
        baseline = rows[0,0]
        valid = all(r['audit_passed'] and classify_run(r)['valid_full_clear'] for r in rows.values())
        for flag, candidate in rows.items():
            if flag == (0,0):
                continue
            pair = dict(cohort=cohort, seed=seed, seed_hex=baseline['seed_hex'],
                        derivation_index=baseline['derivation_index'], candidate=candidate['variant'],
                        route_refresh=flag[0], unknown_first=flag[1], valid_pair=valid,
                        baseline_status=baseline['run_status'], candidate_status=candidate['run_status'])
            for key in METRICS:
                a,b = baseline.get(key), candidate.get(key)
                pair[key+'_delta'] = b-a if valid and a is not None and b is not None else None
            delta = pair['mean_time_per_source_delta']
            pair['comparison'] = 'invalid' if delta is None else 'win' if delta < -1e-6 else 'loss' if delta > 1e-6 else 'tie'
            last_delta = pair['last_source_first_seen_s_delta']
            pair['last_discovery_comparison'] = ('invalid' if last_delta is None else 'win' if last_delta < -1e-6
                                                  else 'loss' if last_delta > 1e-6 else 'tie')
            pairs.append(pair)
        f = dict(cohort=cohort,seed=seed,seed_hex=baseline['seed_hex'],valid=valid)
        for key in ('mean_time_per_source','last_source_first_seen_s'):
            values = [rows[k].get(key) for k in ((0,0),(1,0),(0,1),(1,1))]
            if valid and all(x is not None for x in values):
                a,b,c,d = values
                f[key+'_node_main_delta'] = ((b-a)+(d-c))/2
                f[key+'_channel_main_delta'] = ((c-a)+(d-b))/2
                f[key+'_interaction_delta'] = d-b-c+a
        factorial.append(f)
    return pairs, factorial


def fmt(value):
    return '—' if value is None else f'{value:.3f}' if isinstance(value,float) else str(value)


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|']+
                     ['| '+' | '.join(fmt(x) for x in row)+' |' for row in rows])


def markdown(audit, pairs, factorial):
    lines = ['# Q4 发现调度：冻结 2×2 配对实验', '',
             '本报告仅审计已保存的本地模拟轨迹；MEC 固定，45 个节点和每节点全部未清频道的扫描义务保留。正式测试 0。', '',
             f'完整性与性能证据门禁：**{audit["passed"]}**。这不是默认方案采用决定。', '',
             '种子为预先冻结的确定性设计，非 IID、非官方场景。开发只作完整性门禁，不能据此反复调参后仍将本批留出称为独立验证。', '',
             f'基准提交 `{audit["freeze"]["reference_commit"]}`；本轮执行提交 `{audit["freeze"]["git_commit"]}`。PLAN 与两个 manifest、源码 ZIP 全部逐文件绑定。', '',
             '每个方案的开发样本数为 32、留出样本数为 128；两批分开呈现，不合并后声称扩大留出。P50/P95/P99 是案例值的线性经验分位数，不是总体分位数保证或置信界。32 例的 P99 主要由最大两例决定，应与最大配对回退一起阅读。', '',
             '整场均值为先算每例虚拟秒／该例真实源数再取平均；最后源首次发现使用整场虚拟秒。分位数差不等于逐案例配对差的分位数。', '']
    if len(audit['cohorts']) == 1:
        lines += ['**仅开发批次审计；留出结果未读取，最终性能结论待留出完成。**', '']
    if not audit['passed']:
        lines += ['**存在失败或证据不一致，禁止据下方成功子集统计下性能结论。失败保留在 AUDIT.json/CASES.csv。**','']
    for cohort, data in audit['cohorts'].items():
        lines += ['## '+cohort, '', '### 整场时间与完整性', '']
        summaries = data['summaries']
        rows = []
        for summary in summaries.values():
            p = summary['physical'];label=LABELS[tuple(summary['flags'])]
            rows.append([label,f'{p["full_clear_count"]}/{p["planned_count"]}',p['mean'],p['P50'],p['P95'],p['P99'],p['max'],p['exception_count'],p['protocol_count'],p['timeout_count']])
        lines += [table(['方案','全清','均值 s/source','P50','P95','P99','max','异常','协议','超时'],rows),'',
                  '### 最后真实源首次发现', '',
                  table(['方案','均值 s','P50','P95','P99','max'],[[LABELS[tuple(v['flags'])]]+[v['metrics']['last_source_first_seen_s'][k] for k in ('mean','P50','P95','P99','max')] for v in summaries.values()]), '',
                  '### 发现成本分解（每例均值）','',
                  table(['方案','最后扫描完成 s','discovery s','移动 s','测量 s','切频 s','测量次数','全部发现后扫描 s','全部清除后扫描 s'],
                    [[LABELS[tuple(v['flags'])]]+[v['metrics'][k]['mean'] for k in ('final_discovery_measure_s','stage_discovery_s','discovery_travel_s','discovery_measure_s','discovery_switch_s','discovery_measures','post_last_seen_discovery_s','post_all_cleared_discovery_s')] for v in summaries.values()]),'',
                  '后段扫描是依真实源集合进行的事后诊断，不授权在线提前停止，也不能全额当作可删除收益。','',
                  '### 三方案分别对原配置的配对差','', '差值为候选减基线，负值更快；胜平负按整场 s/source，±1e−6 为平局。','']
        rows=[]
        for variant,v in summaries.items():
            if tuple(v['flags'])==(0,0): continue
            group=[p for p in pairs if p['cohort']==cohort and p['candidate']==variant and p['valid_pair']]
            count=Counter(p['comparison'] for p in group);worst=max(group,key=lambda p:p['mean_time_per_source_delta'],default=None)
            rows.append([LABELS[tuple(v['flags'])],quantiles([p['mean_time_per_source_delta'] for p in group])['mean'],
                         quantiles([p['last_source_first_seen_s_delta'] for p in group])['mean'],
                         f'{count["win"]}/{count["tie"]}/{count["loss"]}',worst['mean_time_per_source_delta'] if worst else None,worst['seed'] if worst else None])
        lines += [table(['候选','整场均差 s/source','最后发现均差 s','胜/平/负','最大配对 Δ s/source','seed'],rows),'',
                  '最大配对 Δ 为候选减基线；正数是回退，若为负数则该候选所有有效案例均更快。', '',
                  '### 最后源首次发现的配对回退', '']
        rows=[]
        for variant,v in summaries.items():
            if tuple(v['flags'])==(0,0): continue
            group=[p for p in pairs if p['cohort']==cohort and p['candidate']==variant and p['valid_pair']]
            count=Counter(p['last_discovery_comparison'] for p in group)
            worst=max(group,key=lambda p:p['last_source_first_seen_s_delta'],default=None)
            rows.append([LABELS[tuple(v['flags'])],f'{count["win"]}/{count["tie"]}/{count["loss"]}',
                         worst['last_source_first_seen_s_delta'] if worst else None,worst['seed'] if worst else None])
        lines += [table(['候选','更早/平/更晚','最大配对延迟 Δ s','seed'],rows),'',
                  '### 2×2 因子分解','',
                  '节点主效应 = ((节点−基线)+(组合−频道))/2；频道主效应类似；交互 = 组合−节点−频道+基线。均为本批配对描述，不是总体因果证明。','']
        fs=[f for f in factorial if f['cohort']==cohort and f['valid']]
        lines += [table(['指标','节点主效应均值','频道主效应均值','交互均值'],
                    [[{'mean_time_per_source':'整场 s/source','last_source_first_seen_s':'最后发现 s'}[key]]+[quantiles([f[key+'_'+effect+'_delta'] for f in fs])['mean'] for effect in ('node_main','channel_main','interaction')]
                    for key in ('mean_time_per_source','last_source_first_seen_s')]),'']
    lines += ['## 解释范围','',
              '刷新方案只在同状态下完整剩余开路径严格缩短时替换缓存顺序。这不保证首跳、最后源发现时间或被定位打断后的整场支配。未知频道优先仍保留当前频道优先和全部测量义务，不能把未知等同于真实有源。', '',
              'MEC 证书逐顶点采用 FP64 与精确二进制有理数复核；真实源是否落在存储的证书多边形内仅由 evaluator 核验。45 节点、每节点频道序列、首次发现时刻、动作费用和阶段账本独立重建。输入与输出 SHA256 见清单；报告脚本没有启动 solver。','']
    if audit.get('development_gate'):
        lines += ['## 报告版本与开发门禁', '',
                  f'保留的开发门禁报告脚本 SHA256：`{audit["development_gate"]["script_sha256"]}`。', '',
                  f'本次最终报告脚本 SHA256：`{audit["report_script_sha256"]}`。后续修改仅补充报告分位数口径、首次发现配对回退和冻结来源复核；原开发证据未改。', '']
    return '\n'.join(lines)


def audit_source_archive(root, plan):
    paths=list(root.glob('frozen_source_*.zip'))
    require(len(paths)==1, 'Need exactly one frozen source ZIP')
    path=paths[0]
    with zipfile.ZipFile(path) as archive:
        names=archive.namelist()
        require(len(names)==len(set(names)) and set(names)==set(plan['source_hashes'])|{'PLAN.json'}, 'Source ZIP member set')
        require(archive.read('PLAN.json')==(root/'PLAN.json').read_bytes(), 'ZIP contains a different PLAN')
        require(all(hashlib.sha256(archive.read(name)).hexdigest()==value
                    for name,value in plan['source_hashes'].items()), 'Frozen ZIP member hash mismatch')
    return dict(passed=True,path=str(path),sha256=sha256(path),source_members=len(plan['source_hashes'])),path


def relocated_evidence_path(value, saved_root, current_root):
    """Resolve archived absolute inputs under the supplied copy, never the host."""
    pure = PureWindowsPath if PureWindowsPath(saved_root).drive else PurePosixPath
    original, path = pure(saved_root), pure(value)
    require(original.is_absolute() and path.is_absolute() and '..' not in path.parts,
            'Development evidence must be an absolute path inside its saved root')
    try:
        relative = path.relative_to(original)
    except ValueError as error:
        raise ValueError('Development evidence escapes its saved root') from error
    base = Path(current_root).resolve()
    resolved = base.joinpath(*relative.parts).resolve()
    require(resolved.is_relative_to(base), 'Relocated evidence escapes current root')
    return resolved


def relative_artifact_path(value, folder):
    pure = PureWindowsPath(value)
    require(not pure.is_absolute() and not pure.drive and not pure.root and '..' not in pure.parts,
            'Development artifact path must stay relative to its folder')
    base = Path(folder).resolve()
    path = base.joinpath(*pure.parts).resolve()
    require(path.is_relative_to(base), 'Development artifact escapes folder')
    return path


def previous_development_gate(root):
    folder=root/'development_audit'
    audit=read_json(folder/'AUDIT.json')
    evidence=read_json(folder/'EVIDENCE_MANIFEST.json')
    require(audit['passed'] is True and audit['cohorts']['development32']['manifest_sha256']==sha256(root/'development32/manifest.json'),
            'Missing/patched development integrity gate')
    for manifest_name in ('ARTIFACT_MANIFEST.json','EVIDENCE_MANIFEST.json'):
        for record in read_json(folder/manifest_name)['files']:
            path=(relative_artifact_path(record['path'],folder) if manifest_name=='ARTIFACT_MANIFEST.json'
                  else relocated_evidence_path(record['path'],audit['input_root'],root))
            require(path.stat().st_size==record['bytes'] and sha256(path)==record['sha256'], 'Preserved development evidence modified')
    return dict(passed=True,audit_path=str(folder/'AUDIT.json'),audit_sha256=sha256(folder/'AUDIT.json'),
                script_sha256=evidence['script_sha256']),[folder/name for name in ('AUDIT.json','EVIDENCE_MANIFEST.json','ARTIFACT_MANIFEST.json')]


def write_csv(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--cohort',choices=('development32',),help='Only the completed development integrity gate; no final holdout conclusion')
    args=parser.parse_args();root=args.root.resolve();output=args.output.resolve()
    require(not output.exists(), 'Choose a new output directory; preserve previous reports')
    plan,prepared=read_json(root/'PLAN.json'),read_json(root/'PREPARED.json')
    require(prepared['plan_sha256']==sha256(root/'PLAN.json') and prepared['planned_runs']==640
            and plan['formal_runs']==prepared['formal_runs']==0, 'Root freeze binding/scope failed')
    require(plan['all_cohorts_frozen_before_candidate_results'] is True and len(plan['seeds'])==160, 'Not a frozen 160-seed plan')
    require(plan['prefix']=='2026B-discovery-scheduling-20260911:', 'Changed seed prefix')
    require(set(prepared['manifests']) == set(COHORTS) and all(sha256(root/name/'manifest.json') == value
            for name,value in prepared['manifests'].items()), 'Both cohorts must match the original simultaneous freeze')
    require(len({s['seed_hex'] for s in plan['seeds']})==160 and all(s['derivation_index']==i and s['seed']==i
            and s['seed_hex']==hashlib.sha256((plan['prefix']+str(i)).encode()).hexdigest() for i,s in enumerate(plan['seeds'])), 'Seed derivation changed')
    archive,archive_path=audit_source_archive(root,plan)
    cases=[];audits={};evidence=[root/'PLAN.json',root/'PREPARED.json',archive_path]
    development_gate=None
    if args.cohort is None:
        development_gate,paths=previous_development_gate(root);evidence.extend(paths)
    for name in ([args.cohort] if args.cohort else COHORTS):
        rows,audit,paths=load_cohort(root,name,plan,prepared)
        cases.extend(rows);audits[name]=audit;evidence.extend(paths)
    pairs,factorial=comparisons(cases)
    audit=dict(passed=all(a['passed'] for a in audits.values()),scope='local performance evidence; no adoption decision',
               final_holdout_report=args.cohort is None,performance_conclusion_allowed=args.cohort is None and all(a['passed'] for a in audits.values()),
               formal_tests=0,solver_runs_started=0,input_root=str(root),cohorts=audits,
               source_archive=archive,development_gate=development_gate,report_script_sha256=sha256(__file__),
               freeze=dict(git_commit=plan['git_commit'],reference_commit=plan['reference_commit'],plan_sha256=sha256(root/'PLAN.json'),
                           prefix=plan['prefix'],source_hash=digest(plan['source_hashes'])))
    output.mkdir(parents=True)
    (output/'AUDIT.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    write_csv(output/'CASES.csv',cases);write_csv(output/'PAIRS.csv',pairs);write_csv(output/'FACTORIAL.csv',factorial)
    (output/'RESULTS.md').write_text(markdown(audit,pairs,factorial),encoding='utf-8')
    (output/'EVIDENCE_MANIFEST.json').write_text(json.dumps(dict(script_sha256=sha256(__file__),
        files=[dict(path=str(p.resolve()),sha256=sha256(p),bytes=p.stat().st_size) for p in evidence]),ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'ARTIFACT_MANIFEST.json').write_text(json.dumps(dict(solver_runs_started=0,files=[dict(path=p.name,sha256=sha256(p),bytes=p.stat().st_size)
        for p in sorted(output.iterdir()) if p.is_file()]),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(output=str(output),passed=audit['passed'],cases=len(cases),performance_conclusion_allowed=audit['performance_conclusion_allowed'])))


if __name__=='__main__':
    main()
