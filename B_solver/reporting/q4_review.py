"""Build a portable Q4 review from completed, immutable benchmark evidence.

No solver imports, simulator calls, or experiment execution. Run from any cwd:
  python B_solver/reporting/q4_review.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
REC = ROOT / "B_solver/results/recovered"
OUT = REC / "q4_morning_review"
PRIMARY = REC / "grid_v1_519"
VARIANTS = ["P4_current_grid_v1", "P4_route_only_grid_v1", "P4_diagnostic_v1_grid_v1"]
LABELS = ["基线", "仅路线重排", "诊断 v1"]
COLORS = ["#8894a2", "#73a5cf", "#174f84"]
STAGES = ["discovery", "active_localization", "diagnostic", "optical_fallback", "certified_clear"]
STAGE_LABELS = ["发现扫描", "主动定位", "诊断恢复", "光学兜底", "证书清除"]
STAGE_COLORS = ["#214f79", "#7ba6ca", "#9870a8", "#d7a85d", "#b4c2cb"]
EPS = 1e-6


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        for key in ("seed", "total", "cleared", "directional_count", "fallback_count", "diagnostic_count", "clear_attempts", "optical_clear_attempts", "detect_count", "switch_count", "grid_points"):
            row[key] = int(row[key])
        for key in ("mean_time_per_source", "virtual_time_s", "distance", *("stage_" + x + "_s" for x in STAGES)):
            row[key] = float(row[key])
            assert math.isfinite(row[key]), (path, key)
        assert row["run_status"] == "FULL_CLEAR" and row["cleared"] == row["total"]
        assert abs(sum(row["stage_" + s + "_s"] for s in STAGES) - row["virtual_time_s"]) < 1e-5
        assert abs(row["mean_time_per_source"] - row["virtual_time_s"] / row["total"]) < EPS
    return rows


def stats(rows):
    t = np.array([r["mean_time_per_source"] for r in rows])
    return {"n": len(t), "mean": float(t.mean()), "median": float(np.median(t)),
            "P95": float(np.percentile(t, 95)), "P99": float(np.percentile(t, 99)), "max": float(t.max())}


def paired_delta(values, reference):
    d = np.array(values) - np.array(reference)
    return {"mean": float(d.mean()), "wins": int((d < -EPS).sum()), "losses": int((d > EPS).sum()),
            "ties": int((abs(d) <= EPS).sum()), "worst": float(d.max()), "best": float(d.min())}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def save_fig(fig, stem):
    svg_path = OUT / "figures" / (stem + ".svg")
    fig.savefig(svg_path, bbox_inches="tight")
    # Matplotlib adds spaces at the ends of SVG path lines; remove only this
    # insignificant XML whitespace, without touching original evidence files.
    svg_path.write_bytes(("\n".join(line.rstrip() for line in svg_path.read_text(encoding="utf-8").splitlines()) + "\n").encode("utf-8"))
    fig.savefig(OUT / "figures" / (stem + ".png"), dpi=220, bbox_inches="tight")
    plt.close(fig)


def make_figures(summaries, means, groups):
    plt.rcParams.update({"font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
                         "axes.unicode_minus": False, "svg.fonttype": "none", "svg.hashsalt": "q4-review-v1",
                         "axes.spines.top": False, "axes.spines.right": False, "axes.grid": False,
                         "legend.frameon": False, "font.size": 10, "axes.labelsize": 10,
                         "xtick.labelsize": 9, "ytick.labelsize": 9})
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.1), gridspec_kw={"width_ratios": [1, 1.6]})
    ax = axes[0]
    bars = ax.barh(np.arange(3), [s["mean"] for s in summaries], color=COLORS, height=.55)
    ax.set_yticks(np.arange(3), LABELS)
    ax.invert_yaxis()
    ax.set_xlim(0, 1550)
    ax.bar_label(bars, fmt="%.2f", padding=6)
    ax.set_xlabel("平均虚拟时间（秒/源，越低越好）")
    ax.set_title("A  全体案例的平均成本", loc="left", pad=15)
    ax = axes[1]
    x = np.arange(3)
    for i, (label, color, s) in enumerate(zip(LABELS, COLORS, summaries)):
        bars = ax.bar(x + (i - 1) * .24, [s[k] for k in ["P95", "P99", "max"]], width=.23, color=color, label=label)
        ax.bar_label(bars, fmt="%.0f", padding=3, fontsize=8)
    ax.set_xticks(x, ["P95", "P99", "最大值"])
    ax.set_ylim(0, 7800)
    ax.set_ylabel("虚拟时间（秒/源）")
    ax.set_title("B  尾部耗时明显收缩", loc="left", pad=15)
    ax.legend(loc="upper left", ncol=3, fontsize=9)
    fig.tight_layout(w_pad=3)
    save_fig(fig, "q4_effect")

    fig, ax = plt.subplots(figsize=(11, 3.6))
    left = np.zeros(3)
    for i, label in enumerate(STAGE_LABELS):
        v = np.array([m[i] for m in means])
        ax.barh(np.arange(3), v, left=left, height=.55, color=STAGE_COLORS[i], label=label)
        for j in range(3):
            if v[j] >= 65:
                ax.text(left[j] + v[j] / 2, j, f"{v[j]:.1f}", ha="center", va="center", color="white" if i == 0 else "#172635", fontsize=10)
        left += v
    for i, value in enumerate(left):
        ax.text(value + 9, i, f"{value:.2f}", va="center")
    ax.set_yticks(np.arange(3), LABELS)
    ax.invert_yaxis()
    ax.set_xlim(0, 1440)
    ax.set_xlabel("各案例先按源数归一化，再对519例取均值（秒/源）")
    ax.set_title("相同519个种子的阶段成本：主要下降来自光学兜底", loc="left", pad=16)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.13), ncol=5)
    fig.tight_layout()
    save_fig(fig, "q4_stages")

    fig, ax = plt.subplots(figsize=(10.5, 3.7))
    for label, color, rows in zip(LABELS, COLORS, groups):
        values = np.sort([r["mean_time_per_source"] for r in rows])
        ax.step(np.r_[0, values], np.r_[0, np.arange(1, len(values) + 1) / len(values) * 100], where="post", color=color, lw=2, label=label)
    ax.set_xlim(0, 6800)
    ax.set_ylim(0, 102)
    ax.set_xlabel("虚拟时间（秒/源）")
    ax.set_ylabel("不超过该耗时的案例（%）")
    ax.set_title("完整经验分布：同一批519例，不拟合概率分布", loc="left", pad=14)
    ax.legend(loc="lower right")
    fig.tight_layout()
    save_fig(fig, "q4_distribution")


def main():
    acceptance = read_json(PRIMARY / "q4/acceptance.json")
    assert acceptance["accept"] and acceptance["expected_run_count"] == acceptance["observed_run_count"] == 1557
    manifest = read_json(PRIMARY / "manifest.json")
    assert manifest["git_commit"] == "3c4e844a010a36d8a441231025e2c1c9d2bc2cce"
    assert manifest["grid_version"] == "grid_v1"
    rows = read_rows(PRIMARY / "q4/cases.csv")
    by_key = {(r["seed"], r["variant"]): r for r in rows}
    assert len(rows) == len(by_key) == 1557
    assert set(by_key) == {(s["seed"], v) for s in manifest["seeds"] for v in VARIANTS}
    groups = [[by_key[(i, v)] for i in range(519)] for v in VARIANTS]
    summaries = [stats(g) for g in groups]
    stored = read_json(PRIMARY / "q4/summary.json")
    for v, st in zip(VARIANTS, summaries):
        for key in ("mean", "median", "P95", "P99", "max"):
            assert abs(st[key] - stored[v][key]) < EPS, (v, key)
    for i in range(519):
        assert len({g[i]["scene_hash"] for g in groups}) == 1
        assert len({g[i]["total"] for g in groups}) == 1

    (OUT / "figures").mkdir(parents=True, exist_ok=True)
    (OUT / "source").mkdir(exist_ok=True)
    means = [[float(np.mean([r["stage_" + s + "_s"] / r["total"] for r in g])) for s in STAGES] for g in groups]
    assert all(abs(sum(m) - st["mean"]) < EPS for m, st in zip(means, summaries))
    values = [[r["mean_time_per_source"] for r in g] for g in groups]
    pairs = [paired_delta(values[2], values[i]) for i in [0, 1]]
    stages = read_json(PRIMARY / "q4/stage_profile.json")
    assert len(stages[VARIANTS[2]]["tail_cases"]) == 26

    legacy_dir = REC / "grid_v0_reference100/q4/subsets/9dd50adbd73b"
    cuda_dir = REC / "grid_v1_cuda20/q4/subsets/bc5e474c6611"
    legacy_rows, cuda_rows = read_rows(legacy_dir / "cases.csv"), read_rows(cuda_dir / "cases.csv")
    for path, n in [(legacy_dir, 300), (cuda_dir, 60)]:
        a = read_json(path / "acceptance.json")
        assert a["accept"] and a["expected_run_count"] == a["observed_run_count"] == n
    legacy = []
    for i, v in enumerate(VARIANTS):
        old = [r for r in legacy_rows if r["variant"] == v.replace("grid_v1", "grid_v0")]
        assert len(old) == 100 and {r["seed"] for r in old} == set(range(100))
        assert all(r[k] == groups[i][r["seed"]][k] for r in old for k in ("seed_hex", "scene_hash", "source_hash"))
        legacy.append({"old": stats(old), "new": stats(groups[i][:100])})
    cuda_fields = ["virtual_time_s", "distance", "fallback_count", "clear_attempts", "detect_count", "switch_count", "diagnostic_count"]
    assert len({(r["seed"], r["variant"]) for r in cuda_rows}) == 60
    assert {(r["seed"], r["variant"]) for r in cuda_rows} == {(i, v) for i in range(20) for v in VARIANTS}
    assert all(r[f] == by_key[(r["seed"], r["variant"])][f] for r in cuda_rows for f in cuda_fields)
    assert all(r[f] == by_key[(r["seed"], r["variant"])][f] for r in cuda_rows for f in ("seed_hex", "scene_hash", "source_hash"))

    inputs = {"primary_cases.csv": PRIMARY / "q4/cases.csv", "primary_summary.json": PRIMARY / "q4/summary.json",
              "primary_acceptance.json": PRIMARY / "q4/acceptance.json", "primary_manifest.json": PRIMARY / "manifest.json",
              "primary_stage_profile.json": PRIMARY / "q4/stage_profile.json", "legacy_cases.csv": legacy_dir / "cases.csv",
              "legacy_acceptance.json": legacy_dir / "acceptance.json", "legacy_manifest.json": REC / "grid_v0_reference100/manifest.json",
              "cuda_manifest.json": REC / "grid_v1_cuda20/manifest.json", "cuda_cases.csv": cuda_dir / "cases.csv",
              "cuda_acceptance.json": cuda_dir / "acceptance.json", "EVIDENCE_AUDIT.json": REC / "EVIDENCE_AUDIT.json"}
    provenance = {"solver_commit": "3c4e844a010a36d8a441231025e2c1c9d2bc2cce", "evidence_commit": "a3d94ff",
                  "scope": "recovered practice generator plus independent local engine; no formal tests", "inputs": []}
    for dest, source in inputs.items():
        shutil.copy2(source, OUT / "source" / dest)
        provenance["inputs"].append({"path": "source/" + dest, "repo_path": source.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
    cases = []
    for i in range(519):
        rr = [g[i] for g in groups]
        cases.append({"seed": i, "seed_hex": rr[0]["seed_hex"], "family": rr[0]["stress"], "total": rr[0]["total"],
                      "directional": rr[0]["directional_count"], "times": [r["mean_time_per_source"] for r in rr],
                      "delta_base": rr[2]["mean_time_per_source"] - rr[0]["mean_time_per_source"],
                      "delta_route": rr[2]["mean_time_per_source"] - rr[1]["mean_time_per_source"],
                      "stages": [[r["stage_" + s + "_s"] / r["total"] for s in STAGES] for r in rr],
                      "fallback": [r["fallback_count"] for r in rr], "diagnostic": [r["diagnostic_count"] for r in rr],
                      "clear_attempts": [r["clear_attempts"] for r in rr], "optical_clear_attempts": [r["optical_clear_attempts"] for r in rr],
                      "distance_km": [r["distance"] / 1000 for r in rr]})
    with (OUT / "paired_519.csv").open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["seed", "seed_hex", "family", "total", "directional", "baseline_s_per_source", "route_s_per_source", "v1_s_per_source", "delta_base", "delta_route"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for c in cases:
            d = {k: c[k] for k in fields if k in c}
            d.update(dict(zip(fields[5:8], c["times"])))
            writer.writerow(d)

    selected = {min(cases, key=lambda c: c["delta_base"])["seed"], max(cases, key=lambda c: c["delta_base"])["seed"],
                max(cases, key=lambda c: c["delta_route"])["seed"], max(cases, key=lambda c: c["times"][2])["seed"]}
    evidence = OUT / "case_evidence"
    evidence.mkdir(exist_ok=True)
    for seed in sorted(selected):
        shutil.copy2(PRIMARY / "scenes" / f"q4_{seed:04d}.json", evidence / f"q4_{seed:04d}.json")
        for v in VARIANTS:
            stem = f"{v}_{seed:04d}"
            shutil.copy2(PRIMARY / "q4/rows" / (stem + ".json"), evidence / (stem + ".json"))
            traces = list((PRIMARY / "q4/traces").glob(stem + "*.gz"))
            assert len(traces) == 1
            shutil.copy2(traces[0], evidence / traces[0].name)
    provenance["selected_case_seeds"] = sorted(selected)
    provenance["validation"] = {"primary_rows": 1557, "legacy_rows": 300, "cuda_rows": 60,
        "primary_summary_recalculated": True, "stage_sums_consistent": True, "cuda_exact_match_fields": cuda_fields,
        "cuda_exact_match_count": 60, "no_solver_runs_during_report_build": True}
    write_json(OUT / "provenance.json", provenance)
    data = {"summaries": summaries, "pairs": pairs, "stage_means": means, "legacy": legacy, "cases": cases,
            "p95": summaries[2]["P95"], "labels": LABELS, "stage_labels": STAGE_LABELS}
    write_json(OUT / "review_data.json", data)
    make_figures(summaries, means, groups)

    table = "\n".join(f"|{label}|519/519|{s['mean']:.2f}|{s['median']:.2f}|{s['P95']:.2f}|{s['P99']:.2f}|{s['max']:.2f}|" for label, s in zip(LABELS, summaries))
    stage_table = "\n".join(f"|{label}|{means[0][j]:.2f}|{means[1][j]:.2f}|{means[2][j]:.2f}|{means[2][j]-means[0][j]:+.2f}|{means[2][j]-means[1][j]:+.2f}|" for j, label in enumerate(STAGE_LABELS))
    legacy_table = "\n".join(f"|{label}|{g['old']['mean']:.2f}|{g['new']['mean']:.2f}|{g['new']['mean']-g['old']['mean']:+.2f}|" for label, g in zip(LABELS, legacy))
    old_gain = (1 - legacy[2]["old"]["mean"] / legacy[0]["old"]["mean"]) * 100
    regression_base = sorted([c for c in cases if c["delta_base"] > EPS], key=lambda c: c["delta_base"], reverse=True)[:5]
    regression_table = "\n".join(f"|{c['seed']}|{c['times'][0]:.2f}|{c['times'][1]:.2f}|{c['times'][2]:.2f}|{c['delta_base']:+.2f}|{c['delta_route']:+.2f}|" for c in regression_base)
    report = f"""# B题 Q4效果对比｜晨检入口

**已完成。本轮整理已有实验，未重新运行求解器。** 求解代码冻结于 `3c4e844`，完整证据已提交于 `a3d94ff`。双击 [index.html](index.html) 看图表并筛选519个种子；给GPT审阅可直接发送本文与 [CASE_NOTES.md](CASE_NOTES.md)。

**当前结论：保留诊断v1作为下一步Q4开发参照。** 在同一批519个种子上，v1平均耗时比基线低 **31.43%**，比仅路线重排低 **6.59%**。基线的大部分尾部已被压下；下一步优先审计发现扫描的调度成本。默认入口仍保留基线，运行v1需显式使用 `configs/q4_p4_diag_v1_grid_v1.yaml`。

## 一眼看结果

单位均为**虚拟秒/源**，每个案例总虚拟时间除以该场景总源数，再对519个案例求均值或分位数；不是程序执行秒数，也不是按全部源数加权的均值。三方案使用同一场景和同一 `grid_v1`。P95表示95%的本组案例不超过该值。

|方案|全清除案例|均值|中位数|P95|P99|最大|
|---|---:|---:|---:|---:|---:|---:|
{table}

![总体与尾部](figures/q4_effect.png)

- v1相对基线：均值 −31.43%，P95 −61.39%，P99 −73.24%，最大值 −80.80%。同种子逐例比较为 **264胜、26负、229平**。
- v1相对仅路线：均值 −6.59%，P95 −9.71%，P99 −17.90%，最大值 −20.08%。同种子逐例比较为 **273胜、17负、229平**。
- 基线 → 仅路线平均省349.06秒/源；仅路线 → v1再省63.52秒/源。不能把总计412.58秒/源全部归给诊断。以上为配置对比的描述性结果，未做因果分离或iid显著性推断。
- 三方案都已全清除，因此当前收益体现为耗时、路程和清除尝试下降，不能写成成功率提升。

## 成本为什么下降，下一步做什么

|指标（519例汇总）|基线|仅路线|v1|
|---|---:|---:|---:|
|平均路程 km|67.34|44.05|41.81|
|发生光学兜底的案例|290/519|290/519|31/519|
|光学兜底轮次|574|570|33|
|光学清除尝试|61,753|69,513|260|
|全部清除尝试|67,957|75,721|7,005|
|诊断测量|0|0|1,000|

仅路线虽然省路程和时间，光学清除尝试却增加；不能将其描述为减少探测次数。路线变化也会改变后续观测及定位区域，不能假设三方案始终搜索完全相同的点集。

下表先对每个案例按源数归一化，再取519例均值。Δ=v1减参照，负数表示省时；五阶段Δ相加等于总体均值Δ。

|阶段（秒/源）|基线|仅路线|v1|Δ基线|Δ仅路线|
|---|---:|---:|---:|---:|---:|
{stage_table}

![阶段成本](figures/q4_stages.png)

按**阶段原始秒数之和 / 总原始秒数之和**计算，v1的发现扫描占全体耗时82.54%，其自身最慢5%（26例）中占85.27%；这26例没有光学兜底。全体光学兜底仅占0.06%。这个占比口径与上表均值的比例不同，不能混算。

下一步建议审计45个覆盖节点上的位置—频道访问顺序、重复无信号测量和末个源的首次发现时刻，保持覆盖结构和MEC≤19.999m证书。占比大不代表能消除全部成本；新调度方案尚未实现或验证。暂不继续扩大诊断深度。

## 回退和最慢案例必须保留

|seed索引|基线|仅路线|v1|Δ基线|Δ仅路线|
|---|---:|---:|---:|---:|---:|
{regression_table}

- **366，最大收益**：基线6636.04 → 仅路线1391.50 → v1 977.91秒/源，主要省去昂贵光学搜索。
- **455，最大对基线回退**：v1多10.89秒/源（0.95%）。基线光学很快命中，诊断和随后的证书清除成本未完全赚回。
- **105，最大对仅路线回退**：v1多13.65秒/源（1.56%）。路线改变后续发现观测，不能仅用“诊断是否有效”解释。
- **283，v1最慢**：1274.04秒/源；发现扫描占83.27%，仍遍历45个发现节点，重点看末个源的发现时刻。

四例的三方案JSON、gzip轨迹及场景原件保存在 [case_evidence](case_evidence/)；逐动作解释见 [CASE_NOTES.md](CASE_NOTES.md)。所有519例（含完整32字节种子）可在网页筛选或下载 [paired_519.csv](paired_519.csv)。seed为本次冻结清单索引，不是官方测试编号。

## 网格版本与CUDA对照

旧网格只复跑同一清单前100个种子；不能与519例总体直接相减。下面只比较同100例均值。

|方案|grid_v0|grid_v1|新减旧（秒/源）|
|---|---:|---:|---:|
{legacy_table}

在旧网格的100例内，v1相对旧基线仍省 **{old_gain:.2f}%**；收益并非只由新网格产生。不过新网格的保守边界增加了基线成本，所以必须保留版本对照。`grid_v1`解决数值稳定性，并非速度优化。

同一清单前20个种子×3方案的60次CUDA运行，与对应CPU运行的虚拟时间、距离及5项关键计数逐项完全相等。此处只验证决策结果一致性，未评估GPU速度，更未验证8卡部署。

## 实验范围与证据入口

- 主Q4是519个不同种子×3方案=1557次；另有旧网格300次、CUDA60次，**Q4合计1917次运行**。连同Q3的519次，共2436次。追加对照复用种子，不增加独立样本数。
- 使用用户提供的还原演练生成器及独立本地规则引擎；不是官方正式场景、不是历史518种子清单的完整复跑。结构压力种子不是iid样本，519/519只说明这份清单全部通过，不能外推所有场景必胜。
- Q4验收1557/1557齐全，无失败、超时、异常或协议错误；失败不会因提前退出变成时间胜利。`accept`只表示完整性和完成率，不能作为性能最优证明。
- **未启动官方App，正式测试累计启动0次。** 本报告未新增测试运行；求解策略保持冻结。
- 可携带原始输入：[source](source/)；输入原路径及SHA256：[provenance.json](provenance.json)；全体实验的轨迹账本审计：[EVIDENCE_AUDIT.json](source/EVIDENCE_AUDIT.json)。
- 完整2436次证据包：`2026B_还原演练引擎_2436次评测_3c4e844.zip`，SHA256 `54352627feb44eef820ad613cbcb98a7fb08baece9cab57afa742203084faa65`。本晨检包保留重点案例的完整轨迹，其余全量轨迹在该证据包。

重建本晨检材料：在仓库执行 `python B_solver/reporting/q4_review.py`（依赖NumPy、Matplotlib）。图表PNG适合直接发送，SVG可编辑；网页不依赖网络或外部库。
"""
    (OUT / "README.md").write_text(report, encoding="utf-8")
    template = (ROOT / "B_solver/reporting/q4_review_template.html").read_text(encoding="utf-8")
    for name in ("q4_effect", "q4_stages", "q4_distribution"):
        svg = (OUT / "figures" / (name + ".svg")).read_text(encoding="utf-8")
        svg = svg[svg.index("<svg"):]
        template = template.replace("{{" + name + "}}", svg)
    template = template.replace("{{DATA}}", json.dumps(data, ensure_ascii=False, allow_nan=False).replace("</", "<\\/"))
    (OUT / "index.html").write_text(template, encoding="utf-8")
    print(json.dumps({"output": str(OUT), "q4_cases": len(cases), "paired": pairs, "selected_evidence": sorted(selected)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
