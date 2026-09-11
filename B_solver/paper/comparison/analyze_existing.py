"""Read existing Q1/Q2 evidence and produce tables/figures. Never imports a solver."""
from pathlib import Path
import csv
import hashlib
import json
import statistics as stats
import subprocess
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
OUT = HERE / 'evidence'
OUT.mkdir(exist_ok=True)
(HERE / 'figures').mkdir(exist_ok=True)

def read(name):
    with (BASE / 'results' / name).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def write(name, rows):
    with (OUT / name).open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

a, b = read('ablations/second_view.csv'), read('ablations/point_vs_set.csv')
methods = ['random_safe', 'perpendicular_midpoint', 'NBV']
lookup = {(r['seed'], r['method']): r for r in a}
assert len(lookup) == len(a) == 300
summary = []
for method in methods:
    rows = [r for r in a if r['method'] == method]
    stop = [r for r in b if r['method'] == method]
    assert len(rows) == len(stop) == 100
    assert {int(r['seed']) for r in rows} == set(range(100))
    summary.append(dict(method=method, n=100,
        mean_diameter_m=stats.mean(float(r['diameter_m']) for r in rows),
        mean_two_measurement_time_s=stats.mean(float(r['time_s']) for r in rows),
        point_failure_count=sum(r['point_attempt_success'] == 'False' for r in stop),
        mec_ready_count=sum(r['mec_stop'] == 'True' for r in stop),
        mec_ready_truth_outside_20m=sum(r['mec_stop'] == 'True' and float(r['mec_center_error_m']) > 20 for r in stop),
        diameter_ready_count=sum(r['diameter_stop'] == 'True' for r in stop),
        diameter_mec_disagreement_count=sum(r['diameter_stop'] != r['mec_stop'] for r in stop)))
write('historical_100_method_summary.csv', summary)
pairs = []
for baseline in methods[:2]:
    for seed in range(100):
        x, y = lookup[(str(seed), 'NBV')], lookup[(str(seed), baseline)]
        pairs.append(dict(seed=seed, baseline=baseline,
            delta_diameter_m=float(x['diameter_m'])-float(y['diameter_m']),
            delta_time_s=float(x['time_s'])-float(y['time_s'])))
write('historical_100_paired_deltas.csv', pairs)
paired_summary = []
for baseline in methods[:2]:
    rows = [r for r in pairs if r['baseline'] == baseline]
    for metric in ['delta_diameter_m', 'delta_time_s']:
        vals = [r[metric] for r in rows]
        paired_summary.append(dict(baseline=baseline, metric=metric, n=len(vals),
            mean=stats.mean(vals), median=stats.median(vals),
            wins=sum(v < -1e-9 for v in vals), ties=sum(abs(v) <= 1e-9 for v in vals),
            losses=sum(v > 1e-9 for v in vals)))
write('historical_100_pair_summary.csv', paired_summary)

plt.rcParams.update({'font.sans-serif': ['Microsoft YaHei', 'DejaVu Sans'],
    'axes.unicode_minus': False, 'svg.fonttype': 'none', 'font.size': 10})
labels = ['随机安全点', '垂直中点', 'NBV']
colors = ['#a6b6c8', '#40a69f', '#315b91']
fig, axes = plt.subplots(1, 2, figsize=(10, 4.4), layout='constrained')
for ax, field, title, unit in zip(axes,
        ['mean_diameter_m', 'mean_two_measurement_time_s'],
        ['平均后验直径（越小越好）', '前两次测量累计时间（越小越好）'], ['m', 's']):
    vals = [r[field] for r in summary]
    ax.bar(labels, vals, color=colors)
    ax.set_ylim(0, max(vals)*1.22)
    ax.set(title=title, ylabel=unit)
    ax.spines[['top', 'right']].set_visible(False)
    for i, v in enumerate(vals): ax.text(i, v+max(vals)*.025, f'{v:.2f}', ha='center')
fig.suptitle('历史100个单源算例：NBV缩小平均直径，但增加移动时间', fontsize=12)
for ext in ['png', 'svg']: fig.savefig(HERE/f'figures/01_historical_tradeoff.{ext}', dpi=220)
plt.close(fig)

q2 = json.loads((BASE/'results/q2.json').read_text(encoding='utf-8'))
fig, ax = plt.subplots(figsize=(7, 4.6), layout='constrained')
rows = q2['solutions']
unique = [rows[0], rows[2], rows[3]]
ax.plot([r['time_s'] for r in unique], [r['worst_sampled_diameter_m'] for r in unique], 'o-', color='#315b91')
for r, label in zip(unique, ['λ=0 / 0.2', 'λ=1', 'λ=5']):
    ax.annotate(label, (r['time_s'], r['worst_sampled_diameter_m']), xytext=(7, 10), textcoords='offset points')
ax.set(xlabel='第二动作新增时间 / s', ylabel='最大采样后验直径 / m',
       title='固定213候选集的权重权衡（已有单个30°算例）', xlim=(115, 225), ylim=(90, 270))
ax.spines[['top', 'right']].set_visible(False)
for ext in ['png', 'svg']: fig.savefig(HERE/f'figures/02_lambda_tradeoff.{ext}', dpi=220)
plt.close(fig)

protected = ['results/ablations/second_view.csv', 'results/ablations/point_vs_set.csv', 'results/q2.json', 'ablations.py', 'questions.py', 'geometry.py']
manifest = {'kind': 'read-only reanalysis of existing evidence', 'new_solver_runs': 0,
    'official_calls': 0, 'formal_test_starts': 0, 'pairing_tolerance_for_display_only': 1e-9,
    'files': [{'path': n, 'sha256': hashlib.sha256((BASE/n).read_bytes()).hexdigest()} for n in protected]}
(OUT/'analysis_provenance.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
history = subprocess.check_output(['git', 'log', '--format=%h %ad %s', '--date=iso', '--',
    'B_solver/questions.py', 'B_solver/geometry.py', 'B_solver/experiments/clearance_geometry_audit.py'], cwd=BASE.parent, text=True, encoding='utf-8')
(OUT/'git_method_history.txt').write_text(history, encoding='utf-8')
print(json.dumps({'methods': summary, 'paired': paired_summary}, ensure_ascii=False))
