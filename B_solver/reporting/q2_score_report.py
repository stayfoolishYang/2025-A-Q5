"""Read saved fixed-candidate Q2 scores; never evaluate geometry or a simulator."""
import argparse
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path


COUNT = 213
LAMBDA = .2
TOL = 1e-6  # Saved numerical-envelope bookkeeping, never a clearance tolerance.


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as stream:
        return json.load(stream)


def fingerprint(path):
    return dict(path=str(path.resolve()), bytes=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def finite(*values):
    return all(type(v) in (int, float) and math.isfinite(v) for v in values)


def load_evidence(root, check_live_sources=False):
    plan, completed = read_json(root/'PLAN.json'), read_json(root/'COMPLETED.json')
    require(plan['schema'] == 'q2-fixed-candidate-score-v1' and plan['candidate_count'] == COUNT
            and completed['candidates'] == COUNT and plan['lambda_m_per_s'] == LAMBDA,
            'Wrong or incomplete fixed-candidate experiment')
    require(all(record[k] == 0 for record in (plan, completed)
                for k in ('solver_runs', 'simulator_runs', 'official_calls'))
            and completed['original_inputs_unchanged'] is True, 'Scope or input-integrity mismatch')
    require(plan['coarse'] == dict(angles=9, radii=17, errors=5)
            and plan['fine'] == dict(angles=17, radii=33, errors=9)
            and plan['envelope'] == dict(tolerance_m=.01, max_splits=20000, initial_bins=72),
            'Changed frozen scoring design')
    evidence = [fingerprint(root/'PLAN.json'), fingerprint(root/'COMPLETED.json')]
    sources, frozen_names = [], set()
    for item in plan['files']:
        frozen, source = root/item['frozen'], Path(item['source'])
        require(frozen.resolve().is_relative_to(root.resolve()), 'Frozen path leaves experiment root')
        require(item['frozen'] not in frozen_names, 'Duplicate frozen file')
        frozen_names.add(item['frozen'])
        snapshot = fingerprint(frozen)
        require(snapshot['sha256'] == item['sha256'], 'Frozen source SHA mismatch: '+str(frozen))
        evidence.append(snapshot)
        if check_live_sources:
            current = fingerprint(source)
            require(current['sha256'] == item['sha256'], 'Live source SHA mismatch: '+str(source))
            sources.append(current)
    require('frozen/q2_candidates.csv' in frozen_names, 'Candidate CSV not bound to PLAN')
    with (root/'frozen/q2_candidates.csv').open(encoding='utf-8-sig', newline='') as stream:
        original = list(csv.DictReader(stream))
    require(len(original) == COUNT and len({(r['x'], r['y']) for r in original}) == COUNT
            and all(r['safe'] == 'True' for r in original), 'Changed candidate set/safety flags')
    expected = {f'{i:03d}.json.gz' for i in range(COUNT)}
    require({p.name for p in (root/'candidates').iterdir()} == expected, 'Missing or unexpected candidate files')
    rows, evaluations, common, boundary = [], 0, 0, 0
    work_counts = dict(cached_wedge_evaluations=0, wedge_evaluations=0, near_disk_intersections=0)
    for i, old in enumerate(original):
        path = root/'candidates'/f'{i:03d}.json.gz'
        record = read_json(path)
        evidence.append(fingerprint(path))
        require(type(record['index']) is int and record['index'] == i, 'Candidate index mismatch')
        x, y, diameter, time = [float(old[k]) for k in ('x', 'y', 'worst_sampled_diameter_m', 'action_time_s')]
        require(finite(x, y, diameter, time) and record['x'] == x and record['y'] == y
                and abs(record['baseline_diameter_m']-diameter) < 1e-7
                and abs(record['action_time_s']-time) < 1e-9
                and abs(record['baseline_score_m']-(diameter+LAMBDA*time)) < 1e-7
                and record['baseline_representative_scenarios'] == 15, f'Baseline D/T/coordinate mismatch: {i}')
        envelope = record['envelope']
        lower, upper, gap = [envelope[k] for k in ('lower_m', 'upper_m', 'gap_m')]
        require(finite(lower, upper, gap) and lower >= 0 and upper+TOL >= lower
                and abs(gap-(upper-lower)) <= 1e-9 and upper+TOL >= diameter,
                f'Invalid numerical interval: {i}')
        leaves = envelope['leaves']
        require(bool(leaves) and all(len(leaf) == 3 and finite(*leaf) and 0 <= leaf[0] < leaf[1] <= 360
                                    and leaf[2] >= 0 for leaf in leaves)
                and leaves[0][0] == 0 and leaves[-1][1] == 360
                and all(a[1] == b[0] for a, b in zip(leaves, leaves[1:]))
                and upper == max(leaf[2] for leaf in leaves), f'Leaf coverage or maximum mismatch: {i}')
        require(type(envelope['splits']) is int and 0 <= envelope['splits'] <= 20000
                and len(leaves) == 72+envelope['splits']
                and envelope['converged'] == (gap <= .01)
                and (envelope['converged'] or envelope['splits'] == 20000)
                and finite(envelope['nesting_residual_m'], record['clip_max_residual_m'], record['calipers_max_difference_m'])
                and envelope['nesting_residual_m'] <= TOL and record['clip_max_residual_m'] <= TOL
                and record['calipers_max_difference_m'] >= 0, f'Envelope/numerical audit mismatch: {i}')
        near_upper = record['near_outer_upper_m']
        all_upper = max(upper, near_upper)
        require(finite(near_upper, record['all_branch_outer_upper_m']) and 0 <= near_upper <= 10
                and record['all_branch_outer_upper_m'] == all_upper, f'Near upper-bound mismatch: {i}')
        for name in ('coarse', 'fine', 'near_boundary'):
            sample = record[name]
            points, count = sample['source_points'], sample['scenario_count']
            counts = sample['counts']
            require(type(points) is int and points >= 0 and type(count) is int
                    and set(counts) == {'direction', 'near', 'no_signal'}
                    and all(type(v) is int and v >= 0 for v in counts.values())
                    and sum(counts.values()) == count and counts['no_signal'] == 0,
                    f'Invalid conditional response counts: {i}/{name}')
            if name != 'near_boundary':
                design = plan[name]
                require(points == design['angles']*design['radii'] and count == points*design['errors'],
                        f'Changed common conditional grid: {i}/{name}')
            else:
                require(points == count and points <= 25, f'Changed dedicated near-boundary grid: {i}')
            value = sample['max_outer_diameter_m']
            require(finite(value) and 0 <= value <= all_upper+TOL
                    and ((count == 0 and sample['witness'] is None and value == 0)
                         or (count > 0 and isinstance(sample['witness'], dict))),
                    f'Conditional-grid maximum exceeds all-branch envelope: {i}/{name}')
        coarse, fine = [record[name]['max_outer_diameter_m'] for name in ('coarse', 'fine')]
        require(fine+TOL >= coarse, f'Nested common grid maximum decreased: {i}')
        radius = record['sampled_argmax_mec_radius_m']
        require(finite(radius) and radius >= 0, f'Invalid radius at sampled diameter maximizer: {i}')
        require(all(type(record[k]) is int and record[k] >= 0 for k in (*work_counts, 'posterior_evaluations'))
                and record['near_disk_intersections'] == 1
                and record['wedge_evaluations'] == record['cached_wedge_evaluations']+16
                and record['posterior_evaluations'] == record['wedge_evaluations']+1,
                f'Geometry-work accounting mismatch: {i}')
        rows.append(dict(index=i, x=x, y=y, D_old_m=diameter, J_old_m=diameter+LAMBDA*time, T_s=time,
                         continuous_LB_m=lower, continuous_UB_m=upper, gap_m=gap,
                         J_LB_m=lower+LAMBDA*time, J_UB_m=upper+LAMBDA*time,
                         converged=envelope['converged'], splits=envelope['splits'],
                         coarse_max_outer_D_m=coarse, fine_max_outer_D_m=fine, fine_minus_coarse_m=fine-coarse,
                         coarse_scenarios=record['coarse']['scenario_count'], fine_scenarios=record['fine']['scenario_count'],
                         coarse_near_scenarios=record['coarse']['counts']['near'],
                         fine_near_scenarios=record['fine']['counts']['near'],
                         near_boundary_scenarios=record['near_boundary']['scenario_count'],
                         near_boundary_near_scenarios=record['near_boundary']['counts']['near'],
                         near_boundary_max_outer_D_m=record['near_boundary']['max_outer_diameter_m'],
                         near_outer_upper_m=near_upper, all_branch_outer_upper_m=all_upper,
                         R_at_sampled_D_argmax_m=radius,
                         sampled_D_argmax_report_deg=envelope['argmax_sampled_report_deg'],
                         clip_max_residual_m=record['clip_max_residual_m'],
                         calipers_max_difference_m=record['calipers_max_difference_m'],
                         nesting_residual_m=envelope['nesting_residual_m'],
                         cached_wedge_evaluations=record['cached_wedge_evaluations'],
                         wedge_evaluations=record['wedge_evaluations'], near_disk_intersections=1,
                         posterior_evaluations=record['posterior_evaluations'], runtime_s=record['runtime_s']))
        for key in work_counts:
            work_counts[key] += record[key]
        evaluations += record['posterior_evaluations']
        common += record['coarse']['scenario_count']+record['fine']['scenario_count']
        boundary += record['near_boundary']['scenario_count']
    require(completed['posterior_evaluations'] == evaluations and completed['common_scenarios'] == common
            and completed['boundary_scenarios'] == boundary
            and all(completed[key] == value for key, value in work_counts.items())
            and completed['all_envelopes_converged'] == all(r['converged'] for r in rows), 'Completion totals mismatch')
    return rows, plan, completed, evidence, sources


def compatible_optima(rows, lower, upper):
    best = min(rows, key=lambda row: (row[upper], row['index']))
    other_lower = min(row[lower] for row in rows if row['index'] != best['index'])
    return dict(best_upper_index=best['index'], best_upper_value=best[upper],
                minimum_other_lower=other_lower,
                compatible_indices=[r['index'] for r in rows if r[lower] <= best[upper]],
                numerically_separated=best[upper] < other_lower,
                separation_margin_m=other_lower-best[upper])


def ordering_comparison(rows, old_key, upper_key):
    old_order = [r['index'] for r in sorted(rows, key=lambda r: (r[old_key], r['index']))]
    upper_order = [r['index'] for r in sorted(rows, key=lambda r: (r[upper_key], r['index']))]
    return dict(old_top_five=old_order[:5], upper_top_five=upper_order[:5],
                changed_ranking_positions=sum(a != b for a, b in zip(old_order, upper_order)))


def table(headers, rows):
    def cell(value):
        return f'{value:.6f}' if isinstance(value, float) else str(value)
    return '\n'.join(['| '+' | '.join(headers)+' |', '| '+' | '.join(['---']*len(headers))+' |']
                     + ['| '+' | '.join(map(cell, row))+' |' for row in rows])


def markdown(summary, rows):
    top = sorted(rows, key=lambda r: (r['J_LB_m'], r['index']))[:12]
    lines = ['# Q2 固定 213 候选：评分与 near 情景审计', '',
             f'文件及算术门禁通过；收敛候选 {summary["converged_candidates"]}/213。求解器运行 0、模拟器运行 0、官方接口调用 0。', '',
             '原候选、外包多边形及输入文件的冻结副本已按 SHA256 核对。'
             f'主实验重算 {summary["work_counts"]["posterior_evaluations"]} 次后验几何；本报告仅重读既有证据，无新增站位或额外后验求解。', '',
             f'本次是否额外核对 PLAN 所记本机原文件：{summary["live_sources_checked"]}。默认只核冻结副本，解压复核不依赖旧绝对路径；'
             '`--check-live-sources` 才追加本机原文件核对。', '',
             '主目标是第二次观测外包域直径 D，同时报告固定 `λ=0.2` 的 `J=D+0.2T`。'
             'T 是第二次移动与检测增量秒数。连续变量是报告角度，站位仍是固定离散集合。', '']
    if summary['calipers_discrepancy_candidates_above_1e_6']:
        lines += [f'**子情景直径算法存在差异：{summary["calipers_discrepancy_candidates_above_1e_6"]} 个候选的某个旧情景中，'
                  f'旋转卡尺与全点对距离之差超过1e−6 m；最大为 {summary["maximum_calipers_difference_m"]:.9f} m。'
                  '213个已保存的15情景最大值仍全部复现通过。文件/算术门禁通过不表示所有子情景几何计算一致；本报告保留差异，未修正共享几何。**', '']
    for title, key in (('仅 D', 'diameter'), ('固定 λ=0.2 的 J', 'score')):
        result = summary[key]
        lines += [f'## {title}', '',
                  f'最小数值上界来自候选 #{result["best_upper_index"]}：{result["best_upper_value"]:.9f} m。', '',
                  f'相容最优集合（L≤min U）：{result["compatible_indices"]}。', '',
                  f'该候选 U 是否严格小于所有其他候选 L：{result["numerically_separated"]}；'
                  f'分离裕量 {result["separation_margin_m"]:.9f} m。', '']
    lines += ['## J 下界最小的 12 个候选', '',
              table(['编号', 'x', 'y', '旧 D', 'D 下界', 'D 上界', 'gap', 'T 秒', 'J 下界', 'J 上界', 'R@采样D最大处'],
                    [[r[k] for k in ('index', 'x', 'y', 'D_old_m', 'continuous_LB_m', 'continuous_UB_m', 'gap_m',
                                    'T_s', 'J_LB_m', 'J_UB_m', 'R_at_sampled_D_argmax_m')] for r in top]), '',
              '## 共同条件网格与 near 专属点', '',
              f'共同粗网格：每候选 153 个真源位置×5 个误差；细网格：561×9，合计 {summary["common_scenarios"]} 个情景。'
              '细网格嵌套粗网格，固定源位置均以首测30°可实现为条件；不是独立随机样本或真实模拟器成绩。', '',
              f'共同网格 near 情景：粗 {summary["coarse_near_scenarios"]}、细 {summary["fine_near_scenarios"]}。'
              '同一源位置在不同误差枚举中重复计作情景，不能据此估计 near 概率。', '',
              f'near 边界专属点另有 {summary["near_boundary_scenarios"]} 个情景，其中 near {summary["near_boundary_near_scenarios"]}；'
              '未混入共同粗细网格最大值。全部已保存情景的外包直径均不超过 max(角域上界, near上界)+1e−6 m。', '',
              f'细减粗最大值：{summary["largest_fine_minus_coarse_m"]:.9f} m；旧15情景到连续角域上界的最大差：'
              f'{summary["largest_UB_minus_old_m"]:.9f} m。全部 213 行见 CANDIDATES.csv。', '',
              f'原15情景的 J 最优候选为 #{summary["old_best_J_index"]}；这里只按同一固定候选与模型作排名比较，'
              '不能将首测轴镜像点之间的原评分差全部归因于采样误差，因为已冻结外包多边形本身并不镜像对称。', '',
              f'细条件网格最大外包 D 最小的候选为 #{summary["fine_grid_best_D_index"]}。', '',
              *[f'{label} 的旧评分与数值 UB 排序：原前5名 {info["old_top_five"]}，UB前5名 {info["upper_top_five"]}；'
                f'完整213名有 {info["changed_ranking_positions"]} 个排名位置不同。'
                '这只是数值上界排序变化，未逐对确认分离区间，不能称真实次序翻转。\n'
                for label, info in summary['ordering_comparisons'].items()],
              '## 数值与结论边界', '',
              '每个角区间用扩宽 wedge 得到固定外包模型的数值上界；已核对叶区间无缝覆盖[0,360]、总上界等于叶上界最大值、'
              '父子数值残差及各记录的收敛状态。下界来自已采样报告角度，指向这个角域代理目标；不声称每个角度都对应合法的真实 direction 情景。', '',
              f'最大裁剪残差 {summary["maximum_clip_residual_m"]:.3e} m，最大父子上界残差 {summary["maximum_nesting_residual_m"]:.3e} m。'
              f'计算量分开计：缓存内实际 wedge 计算 {summary["work_counts"]["cached_wedge_evaluations"]} 次，'
              f'加上旧15情景重算和最终后验后 wedge 共 {summary["work_counts"]["wedge_evaluations"]} 次，'
              f'near 圆盘求交 {summary["work_counts"]["near_disk_intersections"]} 次，'
              f'总后验几何计算 {summary["work_counts"]["posterior_evaluations"]} 次。这些不是模拟器运行次数。', '',
              '0.01 m gap 是浮点算法停止阈值，不是严格 FP64/精确算术证书。上面的“严格小于”只是保存浮点数之间的比较，'
              '不能升级为精确几何最优证明、连续站位全局最优或官方性能保证。', '',
              'R 仅为“连续扫描过程中采样到的最大 D 所对应后验”的 MEC 半径；它不是最大 R，也没有优化 R。'
              'near 使用独立支路，上界不超过10 m；模型外包和合法情景网格的最大值须分别解释。', '',
              '本报告只读原始实验并产生新报告目录，未重新裁剪几何或运行候选评分。实验前 7 项独立测试已另行通过；'
              '其输出由实验负责人保存，本报告没有重跑测试。原始输入与报告文件各自的 SHA256 见 EVIDENCE_MANIFEST.json 和 ARTIFACT_MANIFEST.json。', '',
              '![全部候选与前列数值区间](q2_score_audit.png)', '']
    return '\n'.join(lines)


def plot(rows, summary, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    plt.rcParams.update({'font.sans-serif': ['Microsoft YaHei', 'SimHei', 'DejaVu Sans'],
                         'axes.unicode_minus': False, 'svg.fonttype': 'path', 'font.size': 9,
                         'axes.spines.top': False, 'axes.spines.right': False})
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.4))
    fig.subplots_adjust(left=.055, right=.985, bottom=.24, top=.80, wspace=.35)
    indices = [r['index'] for r in rows]
    axes[0].scatter(indices, [r['continuous_UB_m']-r['D_old_m'] for r in rows], s=13, label='连续数值 UB − 旧 D', color='#0F4D92')
    axes[0].scatter(indices, [r['continuous_LB_m']-r['D_old_m'] for r in rows], s=7, label='连续数值 LB − 旧 D', color='#E09E35')
    axes[0].axhline(0, color='#777777', lw=.8)
    axes[0].set(xlabel='原候选编号（0–212）', ylabel='直径差（m）', title='全部 213 候选：包络与旧情景分差')
    axes[0].legend(fontsize=8)
    top = sorted(rows, key=lambda r: (r['J_LB_m'], r['index']))[:12]
    compatible = summary['score']['compatible_indices']
    for i, row in enumerate(top):
        color = '#B94732' if row['index'] in compatible else '#0F4D92'
        axes[1].plot([row['J_LB_m'], row['J_UB_m']], [i, i], color=color, lw=3)
        axes[1].plot((row['J_LB_m']+row['J_UB_m'])/2, i, 'o', ms=3, color=color)
    axes[1].set(yticks=range(len(top)), yticklabels=[f'#{r["index"]}' for r in top],
                xlabel='J = D + 0.2T（m）', title='J 下界前 12 名：数值区间')
    axes[1].invert_yaxis()
    x, y = [r['coarse_max_outer_D_m'] for r in rows], [r['fine_max_outer_D_m'] for r in rows]
    limit = max(x+y)*1.04
    axes[2].plot([0, limit], [0, limit], '--', lw=1, color='#777777')
    axes[2].scatter(x, y, s=13, color='#0F4D92', alpha=.65)
    axes[2].set(xlim=(0, limit), ylim=(0, limit), xlabel='粗条件网格最大外包 D（m）',
                ylabel='细条件网格最大外包 D（m）', title='共同真源/误差网格：粗 → 细')
    axes[2].set_aspect('equal', adjustable='box')
    for ax in axes:
        ax.grid(color='#E2E8F0', lw=.5)
    fig.suptitle('Q2 固定 213 候选评分审计', fontsize=15, fontweight='bold', y=.97)
    fig.text(.055, .055, '保留全部候选与尾部；红色为 J 区间相容最优候选。near 专属边界点未并入右图。\n'
             '浮点角域代理的数值包络与条件网格；非严格几何证书、连续站位全局最优或官方成绩。', fontsize=9)
    for extension in ('png', 'svg'):
        fig.savefig(output/f'q2_score_audit.{extension}', dpi=220, bbox_inches='tight')
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--check-live-sources', action='store_true',
                        help='Additionally verify original absolute source paths from PLAN on this machine')
    args = parser.parse_args()
    root, output = args.root.resolve(), args.output.resolve()
    require(not output.exists(), 'Use a new output directory; preserve previous reports')
    rows, plan, completed, evidence, sources = load_evidence(root, args.check_live_sources)
    summary = dict(schema='q2-fixed-score-report-v1', evidence_audit_passed=True, candidate_count=COUNT,
                   converged_candidates=sum(r['converged'] for r in rows), lambda_m_per_s=LAMBDA,
                   diameter=compatible_optima(rows, 'continuous_LB_m', 'continuous_UB_m'),
                   score=compatible_optima(rows, 'J_LB_m', 'J_UB_m'),
                   common_scenarios=completed['common_scenarios'],
                   coarse_near_scenarios=sum(r['coarse_near_scenarios'] for r in rows),
                   fine_near_scenarios=sum(r['fine_near_scenarios'] for r in rows),
                   near_boundary_scenarios=completed['boundary_scenarios'],
                   near_boundary_near_scenarios=sum(r['near_boundary_near_scenarios'] for r in rows),
                   largest_fine_minus_coarse_m=max(r['fine_minus_coarse_m'] for r in rows),
                   largest_UB_minus_old_m=max(r['continuous_UB_m']-r['D_old_m'] for r in rows),
                   old_best_J_index=min(rows, key=lambda r: (r['J_old_m'], r['index']))['index'],
                   fine_grid_best_D_index=min(rows, key=lambda r: (r['fine_max_outer_D_m'], r['index']))['index'],
                   primary_objective='second-observation outer-region diameter D',
                   secondary_fixed_score='J=D+0.2T',
                   ordering_comparisons={'D': ordering_comparison(rows, 'D_old_m', 'continuous_UB_m'),
                                         'J': ordering_comparison(rows, 'J_old_m', 'J_UB_m')},
                   frozen_source_hashes_checked=True, live_sources_checked=args.check_live_sources,
                   maximum_clip_residual_m=max(r['clip_max_residual_m'] for r in rows),
                   maximum_calipers_difference_m=max(r['calipers_max_difference_m'] for r in rows),
                   calipers_discrepancy_candidates_above_1e_6=sum(r['calipers_max_difference_m'] > TOL for r in rows),
                   maximum_nesting_residual_m=max(r['nesting_residual_m'] for r in rows),
                   work_counts={key: completed[key] for key in ('cached_wedge_evaluations', 'wedge_evaluations',
                                                                'near_disk_intersections', 'posterior_evaluations')},
                   maximum_gap_m=max(r['gap_m'] for r in rows), input_root=str(root),
                   experiment_git_commit=plan['git_commit'], solver_runs=0, simulator_runs=0, official_calls=0,
                   exact_geometry_certificate=False, continuous_station_global_optimum=False)
    output.mkdir(parents=True)
    with (output/'CANDIDATES.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output/'SUMMARY.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    (output/'RESULTS.md').write_text(markdown(summary, rows), encoding='utf-8')
    plot(rows, summary, output)
    for source in sources:
        require(fingerprint(Path(source['path']))['sha256'] == source['sha256'], 'Source changed while reporting')
    (output/'EVIDENCE_MANIFEST.json').write_text(json.dumps(dict(report_script=fingerprint(Path(__file__)),
        input_files=evidence, frozen_source_hashes_checked=True, live_sources_checked=args.check_live_sources,
        additionally_checked_live_sources=sources), ensure_ascii=False, indent=2), encoding='utf-8')
    artifacts = [dict(fingerprint(path), path=path.name) for path in sorted(output.iterdir()) if path.is_file()]
    (output/'ARTIFACT_MANIFEST.json').write_text(json.dumps(dict(files=artifacts, solver_runs=0, simulator_runs=0),
        ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(output=str(output), passed=True, candidates=COUNT,
                         compatible_D=summary['diameter']['compatible_indices'], compatible_J=summary['score']['compatible_indices'])))


if __name__ == '__main__':
    main()
