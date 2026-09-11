"""Present the two completed NCCP audits without running or changing experiments.

The holdout is never assumed to exist. Missing/unfinished audits stop generation
with an explicit pending status. Performance figures require both independent
NCCP evidence gates; acceptance is read, never reassigned by this presentation.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import sys


BASE = Path(__file__).resolve().parents[1]
COHORTS = ("development100", "holdout256")
COHORT_LABELS = {"development100": "开发集100", "holdout256": "留出集256"}
PROBLEMS = ("4", "3")
PALETTE = {"baseline": "#64748B", "candidate": "#0F766E", "regression": "#B45309", "local": "#2563EB"}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def finite(value):
    result = float(value)
    require(math.isfinite(result), f"非有限数值：{value!r}")
    return result


def close(a, b):
    return math.isclose(finite(a), finite(b), rel_tol=1e-10, abs_tol=1e-7)


def quantile(values, q):
    ordered = sorted(values)
    require(bool(ordered), "有效配对为空")
    position = (len(ordered) - 1) * q / 100
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def fmt(value, precision=3, signed=False):
    if value is None:
        return "—"
    return format(float(value), ("+" if signed else "") + f".{precision}f")


def pct(value):
    return f"{100 * value:.4f}%"


def count(value):
    number = finite(value)
    require(number >= 0 and number.is_integer(), "计数必须为非负整数")
    return str(int(number))


def table(headers, rows):
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    result = ["| " + " | ".join(map(cell, headers)) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    result.extend("| " + " | ".join(map(cell, row)) + " |" for row in rows)
    return "\n".join(result)


def readiness(root):
    status = []
    for name in COHORTS:
        directory = root / name
        if not (directory / "manifest.json").is_file():
            status.append(f"{name}：输入尚未准备，待运行")
            continue
        manifest = read_json(directory / "manifest.json")
        expected = len(manifest["seeds"]) * sum(len(group) for group in manifest["configs"].values())
        if not (directory / "completion.json").is_file():
            status.append(f"{name}：尚无完成记录，待运行或运行中；预期{expected}例")
            continue
        completion = read_json(directory / "completion.json")
        if completion.get("completed_jobs") != expected:
            status.append(f"{name}：完成记录{completion.get('completed_jobs')}/{expected}，待完成")
            continue
        missing = [file for file in ("REPORT.md", "NCCP_AUDIT.json", "NCCP_PAIRS.csv") if not (directory / file).is_file()]
        if missing:
            status.append(f"{name}：运行结束，待审计/报告（缺{', '.join(missing)}）")
    return status


def load_cohort(root, name):
    directory = root / name
    manifest = read_json(directory / "manifest.json")
    audit = read_json(directory / "NCCP_AUDIT.json")
    report = (directory / "REPORT.md").read_text(encoding="utf-8")
    require(audit.get("performance_conclusion_allowed") is True,
            f"{name}：证据门禁未通过，不生成性能比较：{audit.get('failure_reasons')}")
    require(audit.get("cohort") == manifest.get("cohort") == name, f"{name}队列身份不一致")
    require(name in report, f"{name}原报告身份不符")
    require(audit["manifest_sha256"] == sha256(directory / "manifest.json"), f"{name}manifest与审计哈希不符")
    require(audit["source_hash"] == digest(manifest["source_hashes"]), f"{name}源码指纹与审计不符")
    require(audit["shared_seed_plan_hash"] == manifest["shared_seed_plan_hash"], f"{name}种子计划与审计不符")
    seeds = manifest["seeds"]
    expected_count = 100 if name == "development100" else 256
    require(len(seeds) == expected_count and [item["seed"] for item in seeds] == list(range(expected_count)),
            f"{name}种子编号或数量不符")
    require(set(audit["problems"]) == set(PROBLEMS), f"{name}Q3/Q4审计不完整")
    with (directory / "NCCP_PAIRS.csv").open(encoding="utf-8-sig", newline="") as stream:
        raw_pairs = list(csv.DictReader(stream))
    pairs = {(str(item["problem"]), int(item["seed"])): item for item in raw_pairs}
    expected = {(problem, seed) for problem in PROBLEMS for seed in range(expected_count)}
    require(len(raw_pairs) == len(pairs) == len(expected) and set(pairs) == expected,
            f"{name}配对CSV有缺失、重复或计划外记录")
    evidence = [directory / filename for filename in ("manifest.json", "REPORT.md", "NCCP_AUDIT.json",
                                                     "NCCP_PAIRS.csv", "completion.json", "run_request.json")]
    for problem in PROBLEMS:
        summary = audit["problems"][problem]
        configs = manifest["configs"][problem]
        require(len(configs) == 2 and summary["baseline"] == configs[0]["name"]
                and summary["candidate"] == configs[1]["name"], f"{name} Q{problem}配置名不符")
        acceptance_path = directory / f"q{problem}/acceptance.json"
        acceptance = read_json(acceptance_path)
        require(acceptance == summary["evaluation_acceptance"] and acceptance.get("accept") is True,
                f"{name} Q{problem}acceptance与审计不一致或未通过")
        require(acceptance["expected_run_count"] == acceptance["observed_run_count"] == expected_count * 2,
                f"{name} Q{problem}完成计数不符")
        for filename in ("acceptance.json", "summary.json", "stage_profile.json", "cases.csv"):
            evidence.append(directory / f"q{problem}" / filename)
        a_times, b_times, deltas = [], [], []
        for seed in range(expected_count):
            item = pairs[problem, seed]
            source_seed = None if item.get("source_seed") in (None, "") else int(item["source_seed"])
            require(item["seed_hex"] == seeds[seed]["seed_hex"] and source_seed == seeds[seed].get("source_seed"),
                    f"{name} Q{problem} seed={seed}种子映射不符")
            require(item["baseline"] == summary["baseline"] and item["candidate"] == summary["candidate"],
                    f"{name} Q{problem}配对方案不符")
            require(item["baseline_status"] == item["candidate_status"] == "FULL_CLEAR", "配对包含未全清除案例")
            b, a, delta = (finite(item[key]) for key in
                            ("baseline_time_per_source", "candidate_time_per_source", "time_delta_s_per_source"))
            require(close(delta, a - b), "配对时间差与原数值不符")
            comparison = "win" if delta < -1e-6 else "loss" if delta > 1e-6 else "tie"
            require(item["comparison"] == comparison, "配对胜负标记不符")
            item.update(delta=delta, baseline_time=b, candidate_time=a, local_seed=seed, source_seed_value=source_seed)
            a_times.append(a)
            b_times.append(b)
            deltas.append(delta)
        for metric_name, values in (("baseline_metrics", b_times), ("candidate_metrics", a_times)):
            metrics = summary[metric_name]
            require(metrics["n"] == expected_count, "有效全清除数量与计划不符")
            observed = {"mean": statistics.fmean(values), "P50": quantile(values, 50), "P95": quantile(values, 95),
                        "P99": quantile(values, 99), "max": max(values)}
            require(all(close(metrics[key], value) for key, value in observed.items()), "审计汇总与配对CSV不一致")
            label = metric_name.removesuffix("_metrics")
            records = [pairs[problem, seed] for seed in range(expected_count)]
            require(metrics["planned_count"] == metrics["observed_count"] == metrics["audited_case_count"] == expected_count
                    and metrics["full_clear_count"] == expected_count and metrics["full_clear_rate"] == 1.,
                    "全清除分母或逐例证书审计计数不符")
            require(all(item[label+"_valid_full_clear"] == "True" and item[label+"_invalid_evidence"] == "False"
                        for item in records), "配对表含失败或证据异常")
            for field in ("exception_count", "protocol_count", "timeout_count", "partial_clear_count",
                          "zero_clear_count", "invalid_evidence_count"):
                require(metrics[field] == 0, f"完整性计数不符：{field}")
            require(metrics["status_counts"] == {status: expected_count if status == "FULL_CLEAR" else 0
                    for status in ("FULL_CLEAR", "PARTIAL_CLEAR", "ZERO_CLEAR", "EXCEPTION", "TIMEOUT", "PROTOCOL_ERROR")},
                    "分类状态计数不符")
            additive = {"total_virtual_time_s": "virtual_time_s", "total_distance_m": "distance",
                        "total_observed_virtual_time_s": "virtual_time_s", "total_observed_distance_m": "distance",
                        "total_polygon_clear_travel_m": "polygon_clear_travel_m",
                        "same_state_counterfactual_saving_m": "same_state_clear_saving_m"}
            additive.update({field: field for field in ("polygon_certified_count", "near_certified_count",
                "polygon_zero_move_count", "nccp_fallback_count", "current_position_certified_count",
                "current_position_certified_case_count", "zero_move_clear_count", "zero_move_clear_case_count")})
            for field, raw_field in additive.items():
                require(close(metrics[field], sum(finite(item[label+"_"+raw_field]) for item in records)),
                        f"审计与配对表附加账本不符：{field}")
            require(close(metrics["mean_polygon_clear_travel_m_per_source"], statistics.fmean(
                finite(item[label+"_polygon_clear_travel_m"])/finite(item[label+"_total"]) for item in records)),
                "证书段平均米/源不符")
            minimums = [finite(item[label+"_minimum_same_state_saving_m"]) for item in records
                        if item[label+"_minimum_same_state_saving_m"] != ""]
            require(bool(minimums) and min(minimums) >= 0.
                    and close(metrics["minimum_same_state_saving_m"], min(minimums)),
                    "同状态单事件移动节省出现负值或最小值不符")
        paired = summary["paired"]
        require(paired["n"] == expected_count and close(paired["mean_delta_s_per_source"], statistics.fmean(deltas)),
                "配对数量或平均差与审计不符")
        for label, comparison in (("wins", "win"), ("losses", "loss"), ("ties", "tie")):
            require(paired[label] == sum(pairs[problem, seed]["comparison"] == comparison for seed in range(expected_count)),
                    "胜负平数量与审计不符")
        require(close(paired["maximum_regression"], max(0., max(deltas))), "最大回退与审计不符")
        candidate, baseline = summary["candidate_metrics"], summary["baseline_metrics"]
        cert_delta = sum(finite(pairs[problem, seed]["actual_polygon_clear_travel_delta_m"]) for seed in range(expected_count))
        local_saving = sum(finite(pairs[problem, seed]["candidate_same_state_counterfactual_saving_m"]) for seed in range(expected_count))
        run_delta = sum(finite(pairs[problem, seed]["whole_run_distance_delta_m"]) for seed in range(expected_count))
        require(close(cert_delta, candidate["total_polygon_clear_travel_m"] - baseline["total_polygon_clear_travel_m"])
                and close(local_saving, candidate["same_state_counterfactual_saving_m"])
                and close(run_delta, candidate["total_distance_m"] - baseline["total_distance_m"]),
                "实际路程与同状态节省账本不符")
    require(all(path.is_file() for path in evidence), f"{name}部分小证据文件缺失")
    return dict(name=name, directory=directory, manifest=manifest, audit=audit, pairs=pairs, evidence=evidence)


def load_complete(root):
    pending = readiness(root)
    require(not pending, "两批尚未全部完成，未生成最终结果：\n" + "\n".join(pending))
    cohorts = {name: load_cohort(root, name) for name in COHORTS}
    development, holdout = (cohorts[name] for name in COHORTS)
    for field in ("shared_seed_plan_hash", "source_hash"):
        require(development["audit"][field] == holdout["audit"][field], f"两队列{field}不一致")
    require(development["manifest"]["configs"] == holdout["manifest"]["configs"], "两队列配置不同")
    reference = development["audit"]["baseline_reference"]
    require(reference.get("applicable") is True and reference["checked"] == 200 and reference["mismatched"] == 0,
            "开发集200条历史基线逐动作复现门禁未通过")
    require(holdout["audit"]["baseline_reference"].get("applicable") is False,
            "新留出集不应有旧历史轨迹复现结果")
    require(all(item.get("source_seed") is None for item in holdout["manifest"]["seeds"]), "留出复用了旧索引")
    require(not {item["seed_hex"] for item in development["manifest"]["seeds"]}
            & {item["seed_hex"] for item in holdout["manifest"]["seeds"]}, "开发与留出种子重叠")
    prepared = read_json(root / "PREPARED.json")
    plan = read_json(root / "PLAN.json")
    require(digest(plan) == prepared["plan_hash"], "PLAN.json哈希与输入准备记录不符")
    for name, data in cohorts.items():
        require(prepared["manifest_sha256"][name] == sha256(data["directory"] / "manifest.json")
                and data["manifest"]["plan_hash"] == prepared["plan_hash"], "冻结输入准备记录不符")
    return cohorts


def render_figures(cohorts, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    font = Path("C:/Windows/Fonts/msyh.ttc")
    if font.is_file():
        font_manager.fontManager.addfont(str(font))
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(font)).get_name()
    else:
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "Noto Sans CJK SC", "SimHei", "DejaVu Sans"]
    plt.rcParams.update({"axes.unicode_minus": False, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.labelcolor": "#334155", "text.color": "#0F172A", "axes.titleweight": "bold",
                         "font.size": 9, "svg.fonttype": "none", "figure.facecolor": "white"})
    target = output / "figures"
    target.mkdir()
    files = []

    def save(fig, stem):
        for extension in ("png", "svg"):
            path = target / f"{stem}.{extension}"
            fig.savefig(path, dpi=170, bbox_inches="tight")
            files.append(path)
        plt.close(fig)

    fig, axes = plt.subplots(2, 2, figsize=(11, 7), constrained_layout=True)
    for row, problem in enumerate(PROBLEMS):
        for column, name in enumerate(COHORTS):
            axis = axes[row, column]
            data = cohorts[name]["audit"]["problems"][problem]
            values = [data[key]["mean"] for key in ("baseline_metrics", "candidate_metrics")]
            bars = axis.bar(["冻结基线", "NCCP"], values, color=[PALETTE["baseline"], PALETTE["candidate"]], width=.55)
            axis.set_ylim(0, max(values) * 1.20 if max(values) else 1)
            axis.set_title(f"Q{problem} · {COHORT_LABELS[name]}")
            axis.set_ylabel("平均秒/源（纵轴从0开始）")
            axis.grid(axis="y", color="#E2E8F0", linewidth=.6)
            axis.set_axisbelow(True)
            for bar, value in zip(bars, values):
                axis.text(bar.get_x() + bar.get_width() / 2, value, f"{value:.3f}", ha="center", va="bottom")
            delta = values[1] - values[0]
            axis.text(.98, .96, f"Δ={delta:+.3f}秒/源\n相对变化={delta / values[0] * 100:+.4f}%",
                      transform=axis.transAxes, ha="right", va="top", fontsize=8)
    fig.suptitle("NCCP整体均值：开发与留出分开，不放大微小差异", fontsize=13)
    save(fig, "01_mean_from_zero")

    fig, axes = plt.subplots(2, 2, figsize=(11, 7), constrained_layout=True)
    for row, problem in enumerate(PROBLEMS):
        extent = max(abs(item["delta"]) for name in COHORTS
                     for (p, _), item in cohorts[name]["pairs"].items() if p == problem)
        limit = extent * 1.15 if extent else 1.
        for column, name in enumerate(COHORTS):
            axis = axes[row, column]
            pairs = sorted((item for (p, _), item in cohorts[name]["pairs"].items() if p == problem),
                           key=lambda item: (item["delta"], item["local_seed"]))
            values = [item["delta"] for item in pairs]
            colors = [PALETTE["regression"] if item["comparison"] == "loss" else PALETTE["candidate"] for item in pairs]
            axis.scatter(range(1, len(pairs) + 1), values, s=12, color=colors, alpha=.8, linewidths=0)
            axis.axhline(0, color="#475569", linewidth=.8)
            axis.axhline(statistics.fmean(values), color="#2563EB", linestyle="--", linewidth=.8)
            axis.set_ylim(-limit, limit)
            axis.set_xlabel("按差值排序的案例序位（不是种子编号）")
            axis.set_ylabel("NCCP−基线，秒/源；负值更快")
            summary = cohorts[name]["audit"]["problems"][problem]["paired"]
            axis.set_title(f"Q{problem} · {COHORT_LABELS[name]} · 胜/负/平 {summary['wins']}/{summary['losses']}/{summary['ties']}")
            axis.text(.02, .97, f"最大回退 {summary['maximum_regression']:.3f}秒/源\n蓝虚线为平均差",
                      transform=axis.transAxes, va="top", fontsize=8)
    fig.suptitle("逐例配对差：保留全部回退案例，开发与留出同题同尺度", fontsize=13)
    save(fig, "02_paired_deltas")

    fig, axes = plt.subplots(2, 2, figsize=(11, 7), constrained_layout=True)
    for row, problem in enumerate(PROBLEMS):
        for column, name in enumerate(COHORTS):
            axis = axes[row, column]
            data = cohorts[name]["audit"]["problems"][problem]
            baseline, candidate = data["baseline_metrics"], data["candidate_metrics"]
            n = data["expected_cases_per_variant"]
            values = [(baseline["total_polygon_clear_travel_m"] - candidate["total_polygon_clear_travel_m"]) / n,
                      candidate["same_state_counterfactual_saving_m"] / n,
                      (baseline["total_distance_m"] - candidate["total_distance_m"]) / n]
            bars = axis.bar(["证书段实际节省\n独立轨迹之差", "同状态局部节省\n仅候选轨迹内", "全程实际节省\n独立轨迹之差"], values,
                            color=[PALETTE["candidate"], PALETTE["local"], PALETTE["baseline"]], width=.65)
            lo, hi = min(0., min(values)), max(0., max(values))
            span = hi - lo or 1.
            axis.set_ylim(lo - .12 * span if lo < 0 else 0, hi + .25 * span)
            axis.axhline(0, color="#475569", linewidth=.8)
            for bar, value in zip(bars, values):
                axis.text(bar.get_x() + bar.get_width() / 2, value, f"{value:+.2f}", ha="center",
                          va="bottom" if value >= 0 else "top", fontsize=8)
            axis.set_title(f"Q{problem} · {COHORT_LABELS[name]}")
            axis.set_ylabel("米/案例；正值表示节省")
    fig.suptitle("三种路程账本含义不同，不能把同状态节省当作全程收益", fontsize=13)
    save(fig, "03_travel_accounting")
    return files


def readme(root, cohorts):
    holdout_q4 = cohorts["holdout256"]["audit"]["problems"]["4"]
    b, c, p = (holdout_q4[key] for key in ("baseline_metrics", "candidate_metrics", "paired"))
    lines = ["# NCCP配对复核：Q4为主，Q3作为对照",
             f"**Q4留出256例中，两方案均全部清除。平均耗时由{fmt(b['mean'])}变为{fmt(c['mean'])}秒/源，"
             f"NCCP−基线为{fmt(p['mean_delta_s_per_source'], signed=True)}秒/源；逐例胜/负/平为"
             f"{p['wins']}/{p['losses']}/{p['ties']}，最大回退{fmt(p['maximum_regression'])}秒/源。**",
             "两批`performance_conclusion_allowed=true`后才生成本报告。开发集100例用于回归检查，"
             "留出集256例是在候选结果出现前固定的新种子；两者分开呈现，不混算成绩。"
             "相同种子的方案运行不是独立样本，本地确定性种子也不作iid抽样推断。没有官方正式测试成绩。",
             f"原始证据位于`{root}`，冻结源码提交为`{cohorts['holdout256']['manifest']['git_commit']}`。"
             "本报告只读取已有结果，不执行求解器，也不改写acceptance或NCCP_AUDIT。",
             "## 1. Q4结果"]
    for problem in PROBLEMS:
        if problem == "3":
            lines.append("## 2. Q3对照")
        records = []
        for name in COHORTS:
            data = cohorts[name]["audit"]["problems"][problem]
            expected = data["expected_cases_per_variant"]
            for label, key in (("冻结基线", "baseline_metrics"), ("NCCP", "candidate_metrics")):
                metrics = data[key]
                records.append([COHORT_LABELS[name], label, f"{metrics['n']}/{expected}",
                                pct(metrics["full_clear_rate"]), *[fmt(metrics[field]) for field in ("mean", "P50", "P95", "P99", "max")]])
        lines.append(table(["队列", "方案", "全清除/计划", "成功率", "均值秒/源", "P50", "P95", "P99", "最大"], records))
        records = []
        for name in COHORTS:
            data = cohorts[name]["audit"]["problems"][problem]
            for label, key in (("冻结基线", "baseline_metrics"), ("NCCP", "candidate_metrics")):
                metrics = data[key]
                records.append([COHORT_LABELS[name], label, count(metrics["exception_count"]),
                    count(metrics["protocol_count"]), count(metrics["timeout_count"]),
                    count(metrics["partial_clear_count"]+metrics["zero_clear_count"]),
                    fmt(metrics["total_observed_virtual_time_s"]), fmt(metrics["total_observed_distance_m"])])
        lines.append(table(["队列", "方案", "异常", "协议失败", "超时", "其余未清完", "总虚拟时间/s", "总移动/m"], records))
        records = []
        for name in COHORTS:
            data = cohorts[name]["audit"]["problems"][problem]
            paired = data["paired"]
            b, c = data["baseline_metrics"], data["candidate_metrics"]
            records.append([COHORT_LABELS[name], paired["n"], fmt(paired["mean_delta_s_per_source"], signed=True),
                            pct((c["mean"] - b["mean"]) / b["mean"]),
                            f"{paired['wins']}/{paired['losses']}/{paired['ties']}", fmt(paired["maximum_regression"])])
        lines.append(table(["队列", "配对n", "平均Δ秒/源", "均值相对变化", "胜/负/平", "最大回退秒/源"], records))
        lines.append("Δ=NCCP−基线，负值表示更快。均值是各案例T/N的等权平均，P50为中位数，分位数采用线性插值；成功率以计划案例数为分母。"
                     "异常、协议失败、超时为分类器的互斥案例状态，协议失败同时包括证据格式校验失败后的重分类；总虚拟时间和总路程保留全部已观察案例。"
                     "这些是已完成案例的描述性比较，不是全程不劣证明。")
        for name in COHORTS:
            losses = sorted((item for (p, _), item in cohorts[name]["pairs"].items()
                             if p == problem and item["comparison"] == "loss"), key=lambda item: (-item["delta"], item["local_seed"]))
            lines.append(f"Q{problem} {COHORT_LABELS[name]}共有{len(losses)}个回退案例，以下最多列5个：")
            if losses:
                lines.append(table(["本批seed", "旧519索引", "基线秒/源", "NCCP秒/源", "Δ秒/源"],
                                   [[item["local_seed"], item["source_seed_value"] if item["source_seed_value"] is not None else "新留出",
                                     fmt(item["baseline_time"]), fmt(item["candidate_time"]), fmt(item["delta"], signed=True)]
                                    for item in losses[:5]]))
            else:
                lines.append("没有时间差超过1e-6秒/源的正向回退。")
    lines.extend(["## 3. 清除段路程：实际轨迹与同状态局部比较分开",
                  "**实际证书段差**：两个独立方案各自运行时，多边形证书clear动作的移动距离总和之差。"
                  "**同状态局部节省**：只在NCCP自己的每个清除状态中，比较它实际落点与MEC圆心的距离后求和。"
                  "两个量的状态集合不一定相同，不能互相替代，也不能直接换算成全程时间改善。"])
    records = []
    for problem in PROBLEMS:
        for name in COHORTS:
            data = cohorts[name]["audit"]["problems"][problem]
            b, c = data["baseline_metrics"], data["candidate_metrics"]
            records.append([f"Q{problem}", COHORT_LABELS[name], fmt(b["total_polygon_clear_travel_m"]),
                            fmt(c["total_polygon_clear_travel_m"]),
                            fmt(c["total_polygon_clear_travel_m"] - b["total_polygon_clear_travel_m"], signed=True),
                            fmt(c["same_state_counterfactual_saving_m"]),
                            fmt(c["total_distance_m"] - b["total_distance_m"], signed=True)])
    lines.append(table(["题目", "队列", "基线证书段总米数", "NCCP证书段总米数", "实际证书段Δ米", "候选同状态局部节省米", "全程实际Δ米"], records))
    records = []
    for problem in PROBLEMS:
        for name in COHORTS:
            data = cohorts[name]["audit"]["problems"][problem]
            b, c = data["baseline_metrics"], data["candidate_metrics"]
            records.append([f"Q{problem}", COHORT_LABELS[name], fmt(b["mean_polygon_clear_travel_m_per_source"]),
                            fmt(c["mean_polygon_clear_travel_m_per_source"]), fmt(c["minimum_same_state_saving_m"], precision=9)])
    lines.append(table(["题目", "队列", "基线证书段平均米/源", "NCCP证书段平均米/源", "NCCP单事件局部节省最小米数"], records))
    lines.extend(["## 4. 原地clear：near与NCCP多边形证书不是同一类",
                  "near计数指测量返回near后在原坐标clear；多边形零移动计数指已满足多边形证书条件时，"
                  "选定清除点恰为当前位置。二者分开统计，不把near事件当作NCCP新增能力。"
                  "选点回退表示NCCP选择器返回MEC圆心，不等于Q4进入光学兜底。"])
    records = []
    for problem in PROBLEMS:
        for name in COHORTS:
            data = cohorts[name]["audit"]["problems"][problem]
            for label, key in (("冻结基线", "baseline_metrics"), ("NCCP", "candidate_metrics")):
                metrics = data[key]
                records.append([f"Q{problem}", COHORT_LABELS[name], label, count(metrics["polygon_certified_count"]),
                                count(metrics["near_certified_count"]), count(metrics["polygon_zero_move_count"]),
                                count(metrics["nccp_fallback_count"])])
    lines.append(table(["题目", "队列", "方案", "多边形证书clear", "near原地clear", "多边形证书零移动", "选点回退MEC次数"], records))
    records = []
    for problem in PROBLEMS:
        for name in COHORTS:
            data = cohorts[name]["audit"]["problems"][problem]
            for label, key in (("冻结基线", "baseline_metrics"), ("NCCP", "candidate_metrics")):
                metrics = data[key]
                records.append([f"Q{problem}", COHORT_LABELS[name], label,
                    *[count(metrics[field]) for field in ("current_position_certified_case_count",
                        "current_position_certified_count", "zero_move_clear_case_count", "zero_move_clear_count")]])
    lines.append(table(["题目", "队列", "方案", "当前位置已有证书的案例", "对应事件数", "有零移动clear的案例", "全部零移动clear次数"], records))
    lines.append("当前位置已有证书由每个多边形clear事件的起点逐顶点严格复算，不要求方案实际选择留在原地；near不计入此状态数。"
                 "案例计数每例至多一次，事件计数可超过案例数；全部零移动clear次数为near与多边形证书零移动之和。")
    lines.extend(["## 5. 三张小图",
                  "均值柱图纵轴从0开始，避免把小幅收益画成大幅跃升；配对图保留正负两侧，并展示所有案例。"
                  "路程图将总量除以本批案例数，单位为米/案例，三种节省的定义与上表相同。",
                  "![均值从零起](figures/01_mean_from_zero.png)",
                  "![逐例配对差](figures/02_paired_deltas.png)",
                  "![三种路程账本](figures/03_travel_accounting.png)",
                  "PNG适合直接查看；同名SVG可编辑和放大。",
                  "## 6. 审计门禁和解释边界",
                  "- 两个cohort均通过现有NCCP证据审计；本呈现脚本还核对manifest指纹、配置/种子映射、配对CSV、均值/分位数及路程账本。\n"
                  "- 开发集200条历史基线已逐动作精确复现，差异为0。新留出集没有历史轨迹，此项明确不适用；其前置条件是开发审计通过。\n"
                  "- 顶点安全距离及同状态移动不增加由原NCCP_AUDIT逐事件复核；这不推出整条执行路径更短或每例耗时更低。\n"
                  "- 查看结果后调参会改变留出解释。如果看过结果后修改算法或参数，需明确新实验，不能把反复使用本留出集称作独立验证。\n"
                  "- runtime和设备启动耗时不作为得分或加速结论。没有重新设计模型，没有使用官方正式测试。",
                  "本汇总不授予本地研发ACCEPT。performance_conclusion_allowed只是本批性能证据可比较，"
                  "shadow开关动作轨迹一致性、完整离线测试、invalid安全恢复等完整验收事项须另行核对；不得从本报告门禁反推它们已全部完成。",
                  "数学口径补充：精确MEC中心位于可行多边形的凸包内，任意覆盖该多边形的合法清除点距该中心不超过19.999 m。"
                  "因此同一当前状态下，单次多边形clear直接节省的移动时间最多为19.999/5=3.9998秒。"
                  "这是单次动作的理论界，整局均值变化超过4秒/源可以来自后续路径或调度改变，并不与该局部界矛盾。"
                  "本呈现脚本不新增数值验收门槛，也不把代码返回的带浮点裕量MEC半径代入更强的界替代原证书审计。",
                  "## 7. 给GPT的证据文件",
                  "本目录`evidence/`保存两份manifest、两份NCCP审计、两份配对CSV、原REPORT和每题acceptance/summary/阶段汇总/原始CSV等小证据。"
                  "完整逐动作trace仍保留在J盘，不复制到本目录。`EVIDENCE_MANIFEST.json`逐项记录J盘绝对来源、复制后相对路径、大小及SHA-256；"
                  "`ARTIFACT_MANIFEST.json`记录本次生成文件的校验值。",
                  "原审计报告：[开发集REPORT](evidence/development100/REPORT.md)、[留出集REPORT](evidence/holdout256/REPORT.md)。\n"
                  "完整配对表：[开发集CSV](evidence/development100/NCCP_PAIRS.csv)、[留出集CSV](evidence/holdout256/NCCP_PAIRS.csv)。"])
    if (root / "DEVELOPMENT_CASE_NOTES.md").is_file():
        lines.append("[开发案例说明](evidence/DEVELOPMENT_CASE_NOTES.md)仅解释开发集中的已观察案例，"
                     "不是留出集病例，也不把开发阶段的回退解释外推成留出结论。")
    else:
        lines.append("开发案例说明`DEVELOPMENT_CASE_NOTES.md`尚未提供，本次未附该文本；不据此假定已有个案解释。")
    return "\n\n".join(lines) + "\n"


def copy_evidence(root, cohorts, output):
    source_files = [root / "PLAN.json", root / "PREPARED.json"]
    if (root / "DEVELOPMENT_CASE_NOTES.md").is_file():
        source_files.append(root / "DEVELOPMENT_CASE_NOTES.md")
    for cohort in cohorts.values():
        source_files.extend(cohort["evidence"])
    entries = []
    for source in source_files:
        relative = Path("evidence") / source.relative_to(root)
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        before = sha256(source)
        shutil.copyfile(source, destination)
        require(sha256(destination) == before == sha256(source), f"复制期间证据发生变化：{source}")
        entries.append({"source_path": str(source.resolve()), "copied_path": relative.as_posix(),
                        "size_bytes": destination.stat().st_size, "sha256": before})
    return entries


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("J:/2026B_experiments/nccp_20260911"))
    parser.add_argument("--output", type=Path, default=BASE / "results/recovered/nccp_20260911_summary")
    args = parser.parse_args()
    root, output = args.root.resolve(), args.output.resolve()
    try:
        require(not output.exists(), f"输出目录已存在，拒绝混入旧报告：{output}")
        cohorts = load_complete(root)
        text = readme(root, cohorts)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"未生成合并结果：{error}", file=sys.stderr)
        return 2
    output.mkdir(parents=True, exist_ok=False)
    evidence = copy_evidence(root, cohorts, output)
    write_json(output / "EVIDENCE_MANIFEST.json", {"schema": "nccp-summary-evidence-v1", "source_root": str(root),
               "generated_at_utc": datetime.now(timezone.utc).isoformat(),
               "summary_script_sha256": sha256(__file__), "files": evidence})
    figures = render_figures(cohorts, output)
    (output / "README.md").write_text(text, encoding="utf-8")
    generated = [output / "README.md", output / "EVIDENCE_MANIFEST.json", *figures]
    write_json(output / "ARTIFACT_MANIFEST.json", {"schema": "nccp-summary-artifacts-v1",
               "files": [{"path": path.relative_to(output).as_posix(), "size_bytes": path.stat().st_size,
                          "sha256": sha256(path)} for path in generated],
               "copied_evidence_count": len(evidence), "solver_runs_started": 0,
               "performance_gates_read_only": {name: cohort["audit"]["performance_conclusion_allowed"]
                                                for name, cohort in cohorts.items()}})
    print(f"已生成 {output / 'README.md'}；Q4置首，3张PNG及3张SVG；未运行求解器。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
