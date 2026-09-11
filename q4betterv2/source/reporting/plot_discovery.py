"""Read audited final CSVs and render the 128-seed Q4 holdout; never run Solver."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np


MODES = ((0, 0), (1, 0), (0, 1), (1, 1))
LABELS = ('原配置 / MEC', '仅刷新节点', '仅未知频道优先', '两者组合')
COLORS = ('#767676', '#0F4D92', '#42949E', '#B64342')
METRICS = (('mean_time_per_source', '整局耗时', 's/源', '01_holdout_total_time'),
           ('last_source_first_seen_s', '最后真实源首次发现时间', 's', '02_holdout_last_source_seen'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_holdout(source):
    audit = json.loads((source/'AUDIT.json').read_text(encoding='utf-8'))
    require(all(audit.get(k) is True for k in ('passed', 'final_holdout_report', 'performance_conclusion_allowed')),
            'Final holdout audit must pass before plotting')

    def read(name):
        with (source/name).open(encoding='utf-8-sig', newline='') as stream:
            return [r for r in csv.DictReader(stream) if r['cohort'] == 'holdout128']

    cases, pairs = {}, {}
    for row in read('CASES.csv'):
        seed = int(row['seed'])
        mode = int(row['route_refresh']), int(row['unknown_first'])
        key = seed, mode
        require(key not in cases, 'Duplicate holdout case')
        require(row['problem'] == '4' and row['run_status'] == 'FULL_CLEAR' and row['audit_passed'] == 'True',
                'Invalid holdout case')
        require(row['clearance_point'] == 'mec_center' and int(row['derivation_index']) == seed+32,
                'Unexpected clearance policy or holdout seed identity')
        cases[key] = row
    require(set(cases) == {(s, m) for s in range(128) for m in MODES}, 'Need exactly 128 cases per strategy')
    for row in read('PAIRS.csv'):
        key = int(row['seed']), (int(row['route_refresh']), int(row['unknown_first']))
        require(key not in pairs and row['valid_pair'] == 'True', 'Duplicate or invalid pair')
        require(row['baseline_status'] == row['candidate_status'] == 'FULL_CLEAR', 'Failed pair')
        pairs[key] = row
    require(set(pairs) == {(s, m) for s in range(128) for m in MODES[1:]}, 'Need exactly 384 valid pairs')

    values = {}
    for metric, _, _, _ in METRICS:
        data = np.array([[float(cases[s, m][metric]) for s in range(128)] for m in MODES])
        require(np.isfinite(data).all() and (data >= 0).all(), 'Missing or invalid plotting metric')
        for i, mode in enumerate(MODES[1:], 1):
            for seed in range(128):
                pair, baseline, candidate = pairs[seed, mode], cases[seed, MODES[0]], cases[seed, mode]
                require(pair['seed_hex'] == baseline['seed_hex'] == candidate['seed_hex']
                        and pair['candidate'] == candidate['variant'], 'Pair/case identity mismatch')
                require(abs(float(pair[metric+'_delta'])-(data[i, seed]-data[0, seed])) <= 1e-7,
                        'Pair/case metric mismatch')
        values[metric] = data
    return values


def render(source):
    values = load_holdout(source)  # Validate all inputs before creating any figure.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    plt.rcParams.update({'font.sans-serif': ['Microsoft YaHei', 'Noto Sans CJK SC', 'SimHei', 'DejaVu Sans'],
                         'axes.unicode_minus': False, 'axes.spines.top': False, 'axes.spines.right': False,
                         'axes.labelcolor': '#334155', 'text.color': '#0F172A', 'font.size': 9,
                         'axes.titleweight': 'bold', 'svg.fonttype': 'path', 'figure.facecolor': 'white'})
    output = source/'figures'
    output.mkdir(exist_ok=True)
    for metric, title, unit, stem in METRICS:
        data = values[metric]
        fig, axes = plt.subplots(1, 3, figsize=(12.8, 5.25))
        fig.subplots_adjust(left=.065, right=.99, bottom=.24, top=.79, wspace=.27)
        upper = float(data.max())*1.05
        for i, ax in enumerate(axes, 1):
            delta = data[i]-data[0]
            wins, losses = int((delta < -1e-6).sum()), int((delta > 1e-6).sum())
            ax.plot([0, upper], [0, upper], color=COLORS[0], lw=1, ls='--', zorder=1)
            ax.scatter(data[0], data[i], s=18, color=COLORS[i], alpha=.68, linewidths=0, zorder=2)
            ax.set(xlim=(0, upper), ylim=(0, upper), title=LABELS[i],
                   xlabel=f'原配置 / MEC（{unit}）', ylabel=f'候选方案（{unit}）')
            ax.set_aspect('equal', adjustable='box')
            ax.grid(color='#E2E8F0', lw=.5)
            ax.text(.04, .96, f'均值差：{delta.mean():+.3f} {unit}\n胜 / 平 / 负：{wins} / {128-wins-losses} / {losses}',
                    transform=ax.transAxes, va='top', fontsize=8.5,
                    bbox={'facecolor': 'white', 'edgecolor': 'none', 'alpha': .9, 'pad': 3})
        fig.suptitle(f'Q4 留出集配对：{title}', y=.97, fontsize=14, fontweight='bold')
        fig.text(.5, .90, f'128 个相同种子 / 每方案  |  原配置均值 {data[0].mean():.3f} {unit}  |  每点代表同一种子的配对',
                 ha='center', fontsize=10)
        fig.text(.065, .045, '虚线下方表示候选更快；均值差 = 候选 − 原配置。保留全部 128 例，不截断尾部。\n'
                 '本地恢复引擎 · 预先冻结的确定性设计种子 · 非官方成绩 · 所有方案使用 MEC 清除站位', fontsize=9)
        for extension in ('png', 'svg'):
            fig.savefig(output/f'{stem}.{extension}', dpi=220, bbox_inches='tight')
        plt.close(fig)

    hashes = '\n'.join(f'- `{name}`：`{hashlib.sha256((source/name).read_bytes()).hexdigest()}`'
                       for name in ('AUDIT.json', 'CASES.csv', 'PAIRS.csv'))
    (output/'README.md').write_text(
        '# Q4 发现调度留出集配对图\n\n'
        f'来源目录：`{source}`。读取 `CASES.csv`、`PAIRS.csv`，并要求最终 `AUDIT.json` 通过。\n\n'
        '仅展示 holdout128：预先冻结的 128 个相同确定性种子 × 4 方案，共 512 条完整案例、384 组相对基线配对；'
        '不混入开发 32 例。原配置、仅刷新节点、仅未知频道优先、组合均保留 MEC 清除站位。\n\n'
        '- `01_holdout_total_time`：整局虚拟时间除以真实源数，单位 s/源。\n'
        '- `02_holdout_last_source_seen`：所有真实源首次 direction/near 返回时间的最大值，单位 s；不除以源数。'
        '真实源集合仅用于事后指标计算，不输入策略。\n\n'
        '每张图的三列分别将一种候选与同种子基线配对；虚线是相等线，下方更快。均值差为候选减基线，'
        '胜/平/负按该图指标及 ±1e-6 的平局阈值计数。全部数据点与尾部保留；不提供 IID 置信区间，'
        '不声称普遍整局不劣或官方成绩。PNG 为 220 dpi，SVG 将文字转为路径以便跨机器分享。\n\n'
        '生成命令：\n\n'
        f'```text\npython -B B_solver/reporting/plot_discovery.py "{source}"\n```\n\n'
        '脚本只读已有结果，不调用 Solver/Engine，不启动任何演练或正式测试。\n\n'
        f'输入 SHA256：\n\n{hashes}\n', encoding='utf-8')
    print(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path, help='Final report directory containing AUDIT.json, CASES.csv and PAIRS.csv')
    render(parser.parse_args().report.resolve())
