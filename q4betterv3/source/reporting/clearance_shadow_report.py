"""Summarize completed, frozen clearance-shadow evidence without running policy.

Uses only the standard library. Original CSVs and gzip checkpoints are read-only;
new detail CSVs preserve state keys, common-support ranks and tie counts.
"""
import argparse
import csv
import gzip
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
import sys


PLANNERS = ('q3_active', 'q4_active', 'diagnostic_v1')
LABELS = {'q3_active': 'Q3 active', 'q4_active': 'Q4 active', 'diagnostic_v1': 'Q4 diagnostic v1'}
RANK_METRICS = ('D_worst', 'R_worst', 'G_worst', 'sampled_cert_score',
                'certified_completion_cost', 'estimated_completion_cost')
PAIR_COUNTS = ('concordant', 'discordant', 'both_tied', 'current_only_tied', 'shadow_only_tied')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    path = Path(path)
    if path.suffix == '.gz':
        with gzip.open(path, 'rt', encoding='utf-8') as file:
            return json.load(file)
    return json.loads(path.read_text(encoding='utf-8'))


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def finite(value, context):
    require(not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value),
            'Missing or nonfinite numeric value: ' + context)
    return float(value)


def csv_value(value):
    return '' if value is None else str(value)


def state_key(case, state):
    return f"{case}/state={state['shadow_state_index']}/planner={state['planner_kind']}"


def validate_csv(path, expected, key_fields, required_fields=()):
    """Compare every supplied CSV cell and row against its gzip source."""
    with Path(path).open(encoding='utf-8-sig', newline='') as file:
        reader = csv.DictReader(file)
        fields, actual = reader.fieldnames, list(reader)
    require(fields and all(key in fields for key in tuple(key_fields)+tuple(required_fields)),
            'Required CSV columns missing: ' + str(path))
    require(len(fields) == len(set(fields)), 'Duplicate CSV columns: ' + str(path))
    index = {}
    for row in actual:
        key = tuple(row[field] for field in key_fields)
        require(key not in index, 'Duplicate CSV identity: ' + str(key))
        index[key] = row
    require(len(index) == len(expected), 'CSV row count does not match gzip evidence: ' + str(path))
    for row in expected:
        key = tuple(csv_value(row[field]) for field in key_fields)
        require(key in index, 'CSV identity missing: ' + str(key))
        for field in fields:
            require(index[key][field] == csv_value(row.get(field)),
                    f'CSV cell differs from gzip evidence: {path.name}, {key}, {field}')
    return len(actual)


def load_evidence(root):
    root = Path(root)
    required = ('SUMMARY.json', 'RUN_MANIFEST.json', 'STATES.csv', 'CANDIDATES.csv')
    require(all((root/name).is_file() for name in required),
            'Shadow results are incomplete; require SUMMARY.json, RUN_MANIFEST.json, STATES.csv and CANDIDATES.csv')
    summary, manifest = read_json(root/'SUMMARY.json'), read_json(root/'RUN_MANIFEST.json')
    plan_path = root.parent/'SHADOW_PLAN.json'
    require(plan_path.is_file(), 'Frozen SHADOW_PLAN.json missing from input parent directory')
    plan = read_json(plan_path)
    require(sha256(plan_path) == summary.get('plan_sha256'), 'Frozen plan hash mismatch')
    planned = {}
    for job in plan['jobs']:
        name = f"q{job['problem']}_{job['seed']:04d}_{job['variant']}"
        require(name not in planned, 'Duplicate case in frozen plan: ' + name)
        planned[name] = job
    for key in ('passed', 'all_replays_exact', 'all_states_captured', 'source_unchanged'):
        require(summary.get(key) is True, 'Shadow acceptance gate is not true: ' + key)
    require(summary.get('formal_runs') == 0, 'Unexpected formal-run evidence')
    require(summary.get('rates_are_population_estimates') is False, 'Missing fixed-subset scope declaration')
    require(not summary.get('failed_cases'), 'Shadow cases have failures')
    cases = summary.get('cases', [])
    require(len(cases) > 0 and summary.get('expected_cases') == summary.get('completed_cases') == len(cases),
            'Incomplete or empty case set')
    require(len(cases) == len(planned), 'Completed case count differs from frozen plan')
    require(summary.get('plan_sha256') == manifest.get('plan_sha256') and bool(manifest.get('source_hashes')),
            'Missing or inconsistent frozen provenance')
    require(manifest.get('max_states') is None, 'State-capped replay cannot establish all-state coverage')
    state_rows, candidate_rows, states, seen = [], [], [], set()
    sources = {name: sha256(root/name) for name in required}
    sources['../SHADOW_PLAN.json'] = sha256(plan_path)
    action_count = 0
    for case in cases:
        name = case['case']
        require(name not in seen, 'Duplicate case: ' + name)
        seen.add(name)
        path = root/'cases'/Path(case['path']).name
        require(path.is_file() and sha256(path) == case.get('sha256'), 'Missing or changed checkpoint: ' + name)
        sources['cases/'+path.name] = sha256(path)
        payload = read_json(path)
        require(payload.get('plan_sha256') == summary['plan_sha256'], 'Checkpoint plan mismatch: ' + name)
        proof = payload.get('replay_integrity', {})
        require(proof.get('passed') is True and proof.get('solver_trace_excluded_fields') == [],
                'Exact full-trace replay proof missing: ' + name)
        require(set(('actions_fingerprint', 'solver_trace_fingerprint', 'policy_rng_fingerprint',
                     'hypothesis_rng_creation_count', 'virtual_time')).issubset(proof.get('compared', [])),
                'Incomplete replay comparison fields: ' + name)
        require(not payload.get('skipped') and case.get('skipped') == 0, 'Skipped states: ' + name)
        job = payload['job']
        require(name == f"q{job['problem']}_{job['seed']:04d}_{job['variant']}", 'Checkpoint identity mismatch: ' + name)
        require(name in planned and job == planned[name], 'Checkpoint job differs from frozen plan: ' + name)
        require(proof.get('actions_count') == case.get('action_count'), 'Action count mismatch: ' + name)
        action_count += case['action_count']
        require(len(payload['states']) == case.get('states'), 'State count mismatch: ' + name)
        for index, state in enumerate(payload['states']):
            key = state_key(name, state)
            require(state['shadow_state_index'] == index and state['planner_kind'] in PLANNERS,
                    'Unexpected state index or planner: ' + key)
            require(state.get('rng_and_inputs_unchanged') is True, 'State mutation check missing: ' + key)
            require(state.get('policy_use') == 'shadow_only_never_used_for_action_selection', 'Unexpected policy use: ' + key)
            require(state['scenario_design'].get('common_across_candidates') is True and
                    state['scenario_design'].get('calibrated_probability') is False, 'Unexpected scenario design: ' + key)
            candidates = state['candidate_records']
            require(len(candidates) == state['candidate_count'] > 0, 'Empty or incomplete candidates: ' + key)
            require([r['candidate_index'] for r in candidates] == list(range(len(candidates))), 'Candidate identity mismatch: ' + key)
            require(state['planner_selected_index'] in range(len(candidates)), 'Missing original selection: ' + key)
            for field in ('current_D', 'current_R', 'current_G', 'shadow_G_rule_lambda'):
                finite(state.get(field), key+'/'+field)
            identity = dict(case=name, problem=job['problem'], variant=job['variant'], seed=job['seed'],
                            state=index, planner_kind=state['planner_kind'])
            state_rows.append(dict(state, **identity))
            for record in candidates:
                for field in ('move_time_s',):
                    finite(record.get(field), key+'/'+field)
                for field in ('current_planner_score',) + RANK_METRICS:
                    if record.get(field) is not None:
                        finite(record[field], key+'/'+field)
                require(record.get('current_planner_score') is not None or record.get('current_score_reason'),
                        'Unexplained missing original score: ' + key)
                candidate_rows.append(dict(**identity, candidate_x=record['point'][0], candidate_y=record['point'][1],
                    **{field: value for field, value in record.items() if field not in ('point', 'outcomes')}))
            states.append((name, state))
    require(action_count == summary.get('action_count'), 'Aggregate action count mismatch')
    require(states and set(state['planner_kind'] for _, state in states) == set(PLANNERS),
            'Completed evidence does not cover all three declared planners')
    counts = dict(states=validate_csv(root/'STATES.csv', state_rows, ('case', 'state'),
                      ('candidate_count', 'current_score_count', 'GAP_DEGENERATE_STATE', 'no_signal_candidate_count',
                       'planner_selected_index', 'shadow_G_rule_choice', 'min_move_time_choice')),
                  candidates=validate_csv(root/'CANDIDATES.csv', candidate_rows, ('case', 'state', 'candidate_index'),
                      ('candidate_x', 'candidate_y', 'move_time_s', 'current_planner_score', 'rank_current',
                       'rank_D', 'rank_R', 'rank_G', 'no_signal_possible')+RANK_METRICS))
    for kind in PLANNERS:
        subset = [state for _, state in states if state['planner_kind'] == kind]
        stored = summary.get('groups', {}).get(kind, {})
        require(stored.get('captured_states') == len(subset) and
                stored.get('gap_degenerate_states') == sum(s['GAP_DEGENERATE_STATE'] for s in subset),
                'Summary group differs from raw states: ' + kind)
    return summary, manifest, states, sources, counts


def optimum(values, maximize=False):
    known = {index: value for index, value in enumerate(values) if value is not None}
    if not known:
        return set()
    best = (max if maximize else min)(known.values())
    return {index for index, value in known.items() if value == best}


def compare_ranks(records, field, current_max=False):
    """Pairwise ordering on common support; exact ties stay explicit."""
    support = [r for r in records if r.get('current_planner_score') is not None and r.get(field) is not None]
    result = dict(common_candidates=len(support), candidate_pairs=len(support)*(len(support)-1)//2,
                  **{name: 0 for name in PAIR_COUNTS})
    shadow_max = field == 'sampled_cert_score'
    for first, second in combinations(support, 2):
        a = first['current_planner_score'] - second['current_planner_score']
        b = first[field] - second[field]
        a = -a if current_max else a
        b = -b if shadow_max else b
        label = ('both_tied' if a == b == 0 else 'current_only_tied' if a == 0 else
                 'shadow_only_tied' if b == 0 else 'concordant' if (a > 0) == (b > 0) else 'discordant')
        result[label] += 1
    a_top = optimum([r['current_planner_score'] for r in support], current_max)
    b_top = optimum([r[field] for r in support], shadow_max)
    result.update(top_sets_overlap=bool(a_top & b_top) if support else None,
                  top_sets_equal=a_top == b_top if support else None,
                  current_top_size=len(a_top), shadow_top_size=len(b_top))
    return result


def describe_state(case, state):
    records = state['candidate_records']
    move = [r['move_time_s'] for r in records]
    gap = [r.get('G_worst') for r in records]
    known = all(value is not None for value in gap)
    rule = [g+state['shadow_G_rule_lambda']*t for g, t in zip(gap, move)] if known else []
    g_top, move_top = optimum(rule), optimum(move)
    g_chosen = min(g_top) if g_top else None
    require(g_chosen == state['shadow_G_rule_choice'], 'G-rule choice mismatch: '+state_key(case, state))
    require(min(move_top) == state['min_move_time_choice'], 'Move-time choice mismatch: '+state_key(case, state))
    action = state.get('next_executed_action')
    measure = bool(action and action.get('path') == '/measure')
    executed = action.get('position') if measure else None
    executed_indices = [r['candidate_index'] for r in records if r['point'] == executed] if measure else []
    no_signal = [r for r in records if r['no_signal_possible']]
    tolerance = finite(state.get('gap_equality_tolerance_m'), 'gap tolerance')
    for record in no_signal:
        outcomes = [o for o in record['outcomes'] if o['outcome'] == 'no_signal']
        require(outcomes and all(o['no_signal_keeps_hard_polygon'] for o in outcomes),
                'no_signal hard-polygon witness missing: '+state_key(case, state))
        require(record['G_worst'] is not None and record['G_worst'] >= state['current_G']-tolerance,
                'no_signal worst gap shrank unexpectedly: '+state_key(case, state))
    return dict(state_key=state_key(case, state), case=case, state=state['shadow_state_index'],
        planner_kind=state['planner_kind'], action_index_before_selection=state.get('action_index_before_selection'),
        target_channel=state.get('metadata', {}).get('target_channel'),
        planner_point=state['planner_selected_point'], next_action_path=action.get('path') if action else None,
        executed_point=action.get('position') if action else None, g_rule_lambda=state['shadow_G_rule_lambda'],
        candidate_count=len(records), current_score_count=sum(r['current_planner_score'] is not None for r in records),
        current_score_missing=sum(r['current_planner_score'] is None for r in records),
        gap_degenerate=state['GAP_DEGENERATE_STATE'], no_signal_candidates=len(no_signal),
        all_candidates_no_signal_possible=len(no_signal) == len(records),
        all_candidate_G_equals_current=state['G_equals_current_count'] == len(records),
        no_signal_candidate_indices=[r['candidate_index'] for r in no_signal],
        invalid_posterior_candidates=sum(r['invalid_posterior_count'] > 0 for r in records),
        invalid_posterior_outcomes=sum(r['invalid_posterior_count'] for r in records),
        current_G=state['current_G'], G_unique_values=state['G_unique_values'],
        g_rule_choice=g_chosen, min_move_choice=min(move_top), planner_choice=state['planner_selected_index'],
        g_rule_top_indices=sorted(g_top), min_move_top_indices=sorted(move_top),
        g_vs_move_index_different=g_chosen != min(move_top) if known else None,
        g_vs_move_top_sets_disjoint=not bool(g_top & move_top) if known else None,
        g_vs_planner_index_different=g_chosen != state['planner_selected_index'] if known else None,
        planner_outside_g_top=state['planner_selected_index'] not in g_top if known else None,
        actual_next_is_measure=measure, actual_executed_candidate_indices=executed_indices,
        actual_measure_outside_candidates=measure and not executed_indices,
        g_vs_actual_measure_point_different=records[g_chosen]['point'] != executed if known and measure else None,
        actual_measure_outside_g_top=not bool(set(executed_indices) & g_top) if known and measure else None,
        original_plan_accepted=state.get('original_plan_accepted'),
        executed_planned_measurement=state.get('executed_planned_measurement'),
        execution_override_detected=state.get('execution_override_detected'),
        execution_override_reason=state.get('execution_override_reason'))


def fraction(rows, field):
    values = [row[field] for row in rows if row[field] is not None]
    return dict(numerator=sum(values), denominator=len(values), rate=sum(values)/len(values) if values else None)


def ratio_text(value):
    return (f"{value['numerator']}/{value['denominator']} ({100*value['rate']:.2f}%)"
            if value['denominator'] else '不可比较（分母为 0）')


def table(headers, rows):
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', ' ')
    return '\n'.join(['| '+' | '.join(map(cell, headers))+' |',
                      '| '+' | '.join('---' for _ in headers)+' |']+
                     ['| '+' | '.join(map(cell, row))+' |' for row in rows])


def write_csv(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with Path(path).open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
                          for key, value in row.items()} for row in rows)


def build_report(root, output=None):
    root = Path(root)
    output = Path(output) if output else root
    summary, manifest, states, sources, csv_counts = load_evidence(root)
    detail = [describe_state(case, state) for case, state in states]
    rank_rows = [dict(state_key=state_key(case, state), planner_kind=state['planner_kind'], metric=field,
                     **compare_ranks(state['candidate_records'], field, state['planner_kind'] == 'q4_active'))
                 for case, state in states for field in RANK_METRICS]
    groups = {}
    for kind in PLANNERS:
        rows = [row for row in detail if row['planner_kind'] == kind]
        group = dict(states=len(rows), cases=len({r['case'] for r in rows}),
                     candidates=sum(r['candidate_count'] for r in rows),
                     actual_score_candidates=sum(r['current_score_count'] for r in rows),
                     missing_score_candidates=sum(r['current_score_missing'] for r in rows),
                     no_signal_candidates=sum(r['no_signal_candidates'] for r in rows),
                     no_signal_states=sum(r['no_signal_candidates'] > 0 for r in rows),
                     invalid_posterior_candidates=sum(r['invalid_posterior_candidates'] for r in rows),
                     invalid_posterior_outcomes=sum(r['invalid_posterior_outcomes'] for r in rows))
        for field in ('gap_degenerate', 'all_candidates_no_signal_possible', 'all_candidate_G_equals_current',
                      'g_vs_move_index_different', 'g_vs_move_top_sets_disjoint', 'g_vs_planner_index_different',
                      'planner_outside_g_top', 'g_vs_actual_measure_point_different', 'actual_measure_outside_g_top',
                      'original_plan_accepted', 'executed_planned_measurement', 'execution_override_detected'):
            group[field] = fraction(rows, field)
        group['actual_measurements'] = sum(r['actual_next_is_measure'] for r in rows)
        group['actual_measure_outside_candidates'] = sum(r['actual_measure_outside_candidates'] for r in rows)
        group['ranks'] = {}
        for metric in RANK_METRICS:
            matches = [r for r in rank_rows if r['planner_kind'] == kind and r['metric'] == metric]
            totals = {field: sum(r[field] for r in matches) for field in ('common_candidates', 'candidate_pairs')+PAIR_COUNTS}
            totals.update(states_with_common_support=sum(r['common_candidates'] > 0 for r in matches),
                          states_with_two_common_candidates=sum(r['common_candidates'] >= 2 for r in matches),
                          top_sets_overlap=fraction(matches, 'top_sets_overlap'))
            denominator = totals['concordant']+totals['discordant']
            totals['strict_pair_inversion_rate'] = totals['discordant']/denominator if denominator else None
            group['ranks'][metric] = totals
        groups[kind] = group
    audit = dict(schema='clearance-shadow-report-v1', passed=True, policy_change_recommended=False,
                 input_directory=str(root.resolve()), expected_cases=summary['expected_cases'],
                 cases=summary['completed_cases'], actions=summary['action_count'], states=len(detail),
                 source_sha256=sources, report_script_sha256=sha256(__file__), plan_sha256=summary['plan_sha256'],
                 runtime_source_hashes=manifest['source_hashes'], csv_exactly_matches_gzip=csv_counts,
                 groups=groups, formal_runs=0, rates_are_population_estimates=False,
                 rank_ties='exact floating-point equality; no arbitrary tie breaking in rank comparisons',
                 gap_degeneracy_tolerance_m=sorted({s['gap_equality_tolerance_m'] for _, s in states}),
                 scope=summary.get('scope'), selection_rule=summary.get('selection_rule'))
    lines = ['# CLEARANCE SHADOW 审计', '',
        f"完成 {audit['cases']}/{audit['expected_cases']} 条固定轨迹、{audit['actions']} 次原动作、{audit['states']} 个候选选择状态的 shadow off/on 精确回放。动作、完整策略 trace、虚拟时间和 RNG 均一致；没有 trace 字段豁免。原始 CSV 每个单元格已与 gzip 检查点核对。", '',
        '这是首批案例与已知极端案例增强的描述性审计；同一场景的 baseline/NCCP、同一轨迹内多个状态具有相关性。以下分母是捕获状态或候选配对，不能视为独立样本、总体发生率或官方测试结果。此次只补测量，不替换 v1，不承诺全局收益。', '',
        '## 范围和指标', '',
        '- Q3 active 记录原 next_view 分数；Q4 active 记录原 signal_counts/next_view 结果重建并核验选择的实际分数。',
        '- diagnostic v1 只覆盖深度 1；全候选保留，但真实 v1 score 和 estimated completion 仅在原 beam 内可用。beam 外 null 不参与当前分数排名，也不以 proxy 冒充真实分数。',
        '- D/R/G 来自每状态固定、所有候选共享的至多 8 个见证假设与 3 个固定角误差。Q3 使用明确标注的几何见证；它们不同于原规划器的代表分支聚合。',
        '- 空或非有限假设后验在原 shadow 中标为无效：证书分数不给权重，D/R/G 的最坏值只在有效分支间计算。本报告另列无效后验计数，存在无效分支时不能将这些最坏值扩称为全结果保证。',
        '- sampled_cert_score 按固定场景设计权重求和，非观测箱计数，非校准成功概率。额外保守 no_signal 分支权重为 0，只进入最坏指标；no_signal 保留原硬多边形。',
        '- Q4 的 no_signal_possible 来自当前有限保留假设；假设为空时保守记为 true。false 只表示这些假设未给出 no_signal，不能证明真实场景不可能出现 no_signal，也不是硬排除证书。Q3 则按全向 1000 m 安全范围判断。此次原策略与硬可行域均未改变。',
        '- certified completion 仅在全部样本结果可认证时给出观测后的最坏完成成本；estimated completion 是原 v1 score 减原测点耗时。两者缺值均保留理由。',
        '- 排名以精确浮点相等识别并列。G 退化另沿用记录的 1e-8 m 容差；容差内退化并不自动意味着 G+λT 的浮点最优点完全相同。G 规则使用记录的 λ=0.2 m/s。', '',
        '## 三类规划器退化与分数覆盖', '',
        table(['规划器', '状态/轨迹', '候选', '实际分数有值/缺值', 'G 退化', '所有候选 G=当前 G', '有 no_signal 的状态'],
              [[LABELS[k], f"{g['states']}/{g['cases']}", g['candidates'],
                f"{g['actual_score_candidates']}/{g['missing_score_candidates']}", ratio_text(g['gap_degenerate']),
                ratio_text(g['all_candidate_G_equals_current']), f"{g['no_signal_states']}/{g['states']}"] for k,g in groups.items()]), '',
        table(['规划器', '含无效后验的候选数', '无效后验分支数'],
              [[LABELS[k],g['invalid_posterior_candidates'],g['invalid_posterior_outcomes']] for k,g in groups.items()]), '',
        '## G 规则与原选择、实际执行', '',
        table(['规划器', 'G 与最小耗时索引不同', '两者最优集合无交集', 'G 与原选点索引不同', '原选点不在 G 最优集合', 'G 与实际下一测量点不同'],
              [[LABELS[k]]+[ratio_text(g[f]) for f in ('g_vs_move_index_different', 'g_vs_move_top_sets_disjoint',
                'g_vs_planner_index_different', 'planner_outside_g_top', 'g_vs_actual_measure_point_different')] for k,g in groups.items()]), '',
        '索引差异沿用候选顺序中的首个 argmin，可能只是并列选择。最优集合列避免把并列误判为严格差异。实际执行列仅纳入下一动作确为 /measure 且 G 规则可计算的状态；被拒绝的诊断计划、后续 clear 不计入这一分母。若实际点落在原候选之外，仍计入实际测量点差异，并在明细明确标记。', '',
        table(['规划器', '实际下一测量次数', '实际点在候选外', '执行 override', '诊断计划接受', '诊断计划实际测量'],
              [[LABELS[k],g['actual_measurements'],g['actual_measure_outside_candidates'],ratio_text(g['execution_override_detected']),
                ratio_text(g['original_plan_accepted']),ratio_text(g['executed_planned_measurement'])] for k,g in groups.items()]), '',
        '## 与当前实际分数的排名关系', '',
        '每个状态只比较两项均有值的候选。下表计数为候选对汇总；候选较多的状态权重更大，不是状态比例。逆序率分母仅含双方严格有序的候选对；双方并列及单边并列单列。成对排序需要至少 2 个共同候选，最优集合重合则纳入至少 1 个共同候选的状态，因此两列状态分母可以不同。最优集合重合仅在共同候选子集上计算，尤其不能把 diagnostic beam 内重合解释成全候选最优。', '']
    for kind, group in groups.items():
        lines.extend([f'### {LABELS[kind]}', '', table(
            ['指标', '共同候选≥2 的状态', '一致/逆序', '双方并列', '仅当前并列/仅指标并列', '严格配对逆序率', '共同子集最优集合重合'],
            [[metric, value['states_with_two_common_candidates'], f"{value['concordant']}/{value['discordant']}",
              value['both_tied'], f"{value['current_only_tied']}/{value['shadow_only_tied']}",
              f"{100*value['strict_pair_inversion_rate']:.2f}%" if value['strict_pair_inversion_rate'] is not None else '不可比较',
              ratio_text(value['top_sets_overlap'])] for metric,value in group['ranks'].items()]), ''])
    lines.extend(['## no_signal 可定位实例', '',
        '以下按规划器选择原始顺序中第一个含 no_signal 的状态，给出完整 state key。全部实例与候选索引列在 CLEARANCE_SHADOW_STATES.csv；对应 gzip 中保留后验指标及重建所需输入，包括输入多边形、固定场景和权重，可重建后验几何并逐项复算。', ''])
    examples = []
    for kind in PLANNERS:
        example = next((r for r in detail if r['planner_kind'] == kind and r['no_signal_candidates']), None)
        if example:
            examples.append([example['state_key'], example['action_index_before_selection'], example['target_channel'],
                             f"{example['no_signal_candidates']}/{example['candidate_count']}", example['current_G'], example['G_unique_values']])
    lines.extend([table(['完整 state key', '动作前索引', '频道', 'no_signal 候选数', '当前 G/m', 'G 不同值数'], examples), '',
        '## 原始证据和可复算表', '',
        '- 输入：上级目录的 SHADOW_PLAN.json，以及 SUMMARY.json、RUN_MANIFEST.json、STATES.csv、CANDIDATES.csv、cases/*.json.gz；病例集合须与冻结计划精确相等，原文件未改写。',
        '- CLEARANCE_SHADOW_STATES.csv：完整 state key、原选择、G/耗时最优集合、实际执行和 no_signal 候选索引。',
        '- CLEARANCE_SHADOW_RANKS.csv：每状态每指标的共同候选数、五类候选对关系和最优集合关系。',
        '- CLEARANCE_SHADOW_AUDIT.json：验收结果、全部输入 SHA256、运行源码指纹、分母和精确汇总数。', '',
        f"计划 SHA256：`{summary['plan_sha256']}`。", '',
        '本报告不评价 wall-clock 加速，也不把见证场景证书分数当作真实成功概率。下一步是否修改评分，必须另立策略实验；本次审计结论本身不构成切换依据。', ''])
    # Refuse to publish if evidence changed while it was being summarized.
    require(all(sha256(root/name) == digest for name,digest in sources.items()), 'Evidence changed during report generation')
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output/'CLEARANCE_SHADOW_STATES.csv', detail)
    write_csv(output/'CLEARANCE_SHADOW_RANKS.csv', rank_rows)
    (output/'CLEARANCE_SHADOW_AUDIT.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    (output/'CLEARANCE_SHADOW_AUDIT.md').write_text('\n'.join(lines), encoding='utf-8')
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        result = build_report(args.input, args.output)
    except (KeyError, TypeError, ValueError, OSError) as exc:
        print(json.dumps(dict(passed=False, status='REFUSED_INCOMPLETE_OR_INVALID_EVIDENCE',
                              reason=f'{type(exc).__name__}: {exc}', report_written=False), ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(dict(passed=result['passed'], cases=result['cases'], states=result['states'],
                          output=str(args.output or args.input)), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
