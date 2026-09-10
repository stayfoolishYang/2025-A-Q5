"""Read completed recovered-engine evidence and write a Chinese handoff report.

This module intentionally lives outside the benchmark's frozen source set. It
never imports or runs the solver, simulator, or evaluator, and never changes an
acceptance decision. Incomplete or inconsistent evidence stops report creation.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys


STAGES = {
    "discovery": "发现扫描",
    "active_localization": "主动定位",
    "diagnostic": "诊断恢复",
    "optical_fallback": "光学兜底",
    "certified_clear": "证书清除",
}
FAMILIES = {
    "byte_pattern": "固定字节模式",
    "one_bit": "单比特输入",
    "sha256_new_design": "新定义SHA-256派生",
    "supplied_all_directional_fixture": "附带全定向种子",
}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def need(condition, message):
    if not condition:
        raise ValueError(message)


def finite(value):
    result = float(value)
    need(math.isfinite(result), f"非有限数值：{value!r}")
    return result


def percentile(values, q):
    """Linear interpolation matching the frozen evaluator's NumPy default."""
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * q / 100
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def stats(values):
    return {"mean": statistics.fmean(values) if values else None,
            "P95": percentile(values, 95), "P99": percentile(values, 99),
            "max": max(values) if values else None}


def number(value, places=2, signed=False):
    if value is None:
        return "—"
    return format(value, ("+" if signed else "") + f".{places}f")


def percent(value):
    return "—" if value is None else f"{value * 100:.2f}%"


def table(headers, rows):
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    result = ["| " + " | ".join(map(cell, headers)) + " |",
              "| " + " | ".join("---" for _ in headers) + " |"]
    result.extend("| " + " | ".join(map(cell, row)) + " |" for row in rows)
    return "\n".join(result)


def close(a, b):
    if a is None or b is None:
        return a is b
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-7)


def load_completed(root, full=True):
    manifest = read_json(root / "manifest.json")
    seeds = manifest["seeds"]
    seed_ids = [int(item["seed"]) for item in seeds]
    need(seed_ids == list(range(len(seeds))), "manifest种子编号不连续，停止生成报告")
    need(len({item["seed_hex"] for item in seeds}) == len(seeds), "manifest存在重复seed_hex")
    need(set(manifest["configs"]) == {"3", "4"}, "报告要求完整Q3/Q4冻结计划")
    completion = read_json(root / "completion.json")
    request = read_json(root / "run_request.json")
    indices = request["indices"]
    problems = request["problems"]
    need(len(set(indices)) == len(indices) and indices and set(indices) <= set(seed_ids), "run_request种子子集无效")
    need(len(set(problems)) == len(problems) and set(problems) <= {3, 4} and problems, "run_request题号无效")
    if full:
        need(indices == seed_ids and set(problems) == {3, 4}, "主报告要求完整冻结计划")
    else:
        need(problems == [4], "辅助对照要求Q4计划")
    expected_jobs = len(indices) * sum(len(manifest["configs"][str(problem)]) for problem in problems)
    need(completion["completed_jobs"] == expected_jobs,
         f"完整计划尚未完成：completion={completion['completed_jobs']}，预期={expected_jobs}")
    need(request["jobs"] == expected_jobs, "run_request工作数与计划不符")
    evidence_files = [root / name for name in ("manifest.json", "completion.json", "run_request.json")]
    loaded = {}
    unsuccessful = 0
    for problem in problems:
        folder = root / f"q{problem}"
        report_folder = folder if indices == seed_ids else folder / "subsets" / digest(indices)[:12]
        files = {name: report_folder / name for name in
                 ("summary.json", "acceptance.json", "stage_profile.json", "cases.csv", "classified_cases.csv")}
        evidence_files.extend(files.values())
        summary, acceptance, profile = (read_json(files[key]) for key in
                                        ("summary.json", "acceptance.json", "stage_profile.json"))
        raw, classified = read_csv(files["cases.csv"]), read_csv(files["classified_cases.csv"])
        configs = manifest["configs"][str(problem)]
        names = [config["name"] for config in configs]
        plan = {(seed, name) for seed in indices for name in names}
        keyed = {(int(row["seed"]), row["variant"]): row for row in raw}
        checks = {(int(row["seed"]), row["variant"]): row for row in classified}
        need(len(raw) == len(keyed) == len(plan) and set(keyed) == plan,
             f"Q{problem} cases.csv存在缺失、重复或计划外案例")
        need(len(classified) == len(checks) == len(plan) and set(checks) == plan,
             f"Q{problem} classified_cases.csv未完整覆盖冻结计划")
        need(acceptance["expected_run_count"] == acceptance["observed_run_count"] == len(plan),
             f"Q{problem} acceptance计数与完整计划不符")
        need(set(summary) == set(names), f"Q{problem} summary方案不符")
        scene_meta = {}
        for seed in indices:
            scene_name = f"q{problem}_{seed:04d}.json"
            scene = read_json(root / "scenes" / scene_name)
            scene_hash = digest(scene)
            need(scene_hash == manifest["scene_hashes"][scene_name], f"冻结场景哈希变化：{scene_name}")
            need(scene["generator_seed_hex"] == seeds[seed]["seed_hex"] and scene["problem_no"] == problem,
                 f"冻结场景身份变化：{scene_name}")
            scene_meta[seed] = {
                "total": len(scene["jammers"]), "hash": scene_hash,
                "directional": sum(source["kind"] == "directional" for source in scene["jammers"]),
            }
        for config in configs:
            for seed in indices:
                row, check = keyed[seed, config["name"]], checks[seed, config["name"]]
                expected = {"problem": str(problem), "scene_hash": scene_meta[seed]["hash"],
                            "config_hash": digest(config), "source_hash": digest(manifest["source_hashes"]),
                            "device": request["device"]}
                need(all(row.get(key) == value for key, value in expected.items()),
                     f"Q{problem} seed={seed} {config['name']}原始证据身份/哈希/设备不符")
                need(int(row["total"]) == scene_meta[seed]["total"], "结果总源数与冻结场景不符")
                for key in ("scene_hash", "config_hash", "source_hash", "mean_time_per_source", "cleared", "total"):
                    need(row.get(key) == check.get(key), f"分类CSV与原始CSV不一致：{key}")
                row["valid"] = check["valid_full_clear"] == "True"
                row["status"] = check["run_status"]
                row["seed_number"] = seed
                row["seed_hex"] = seeds[seed]["seed_hex"]
                row["family"] = seeds[seed]["family"]
                row["source_count"] = scene_meta[seed]["total"]
                row["all_directional"] = scene_meta[seed]["directional"] == scene_meta[seed]["total"]
                if row["valid"]:
                    row["time"] = finite(row["mean_time_per_source"])
                else:
                    row["time"] = None
                unsuccessful += row["status"] != "FULL_CLEAR" or bool(row.get("error"))
            group = [keyed[seed, config["name"]] for seed in indices]
            timed = [row["time"] for row in group if row["valid"]]
            recorded = summary[config["name"]]
            need(recorded["expected_n"] == len(indices) and recorded["n"] == len(group)
                 and recorded["all_clear"] == len(timed), f"{config['name']}汇总计数过期")
            for key, value in stats(timed).items():
                need(close(value, recorded[key]), f"{config['name']} {key}汇总与CSV不一致")
            if timed:
                need(config["name"] in profile and profile[config["name"]]["n"] == len(timed),
                     f"{config['name']}阶段账本缺失/过期")
                expected_tail = {row["seed_number"] for row in group
                                 if row["valid"] and row["time"] >= percentile(timed, 95)}
                need(profile[config["name"]]["tail_metric"] == "mean_time_per_source"
                     and set(profile[config["name"]]["tail_cases"]) == expected_tail,
                     f"{config['name']}阶段尾部案例口径不符")
                for row in group:
                    if row["valid"]:
                        phase_total = sum(finite(row[f"stage_{stage}_s"]) for stage in STAGES)
                        need(abs(phase_total - finite(row["virtual_time_s"])) <= 1e-5,
                             f"{config['name']} seed={row['seed_number']}阶段账本不平")
                valid_rows = [row for row in group if row["valid"]]
                tail_rows = [row for row in valid_rows if row["seed_number"] in expected_tail]
                for stage in STAGES:
                    aggregate = sum(finite(row[f"stage_{stage}_s"]) for row in valid_rows) / sum(finite(row["virtual_time_s"]) for row in valid_rows)
                    tail_aggregate = sum(finite(row[f"stage_{stage}_s"]) for row in tail_rows) / sum(finite(row["virtual_time_s"]) for row in tail_rows)
                    need(close(aggregate, profile[config["name"]]["stages"][stage]["aggregate_fraction"])
                         and close(tail_aggregate, profile[config["name"]]["stages"][stage]["tail_aggregate_fraction"]),
                         f"{config['name']} {stage}阶段占比与CSV不一致")
        loaded[problem] = dict(summary=summary, acceptance=acceptance, profile=profile,
                               rows=keyed, names=names, configs=configs, folder=folder, indices=indices,
                               device=request["device"])
    need(unsuccessful == completion["unsuccessful"], "completion失败数与CSV不一致")
    return manifest, loaded, expected_jobs, evidence_files


def paired(rows, candidate, reference, seeds):
    result = {"pairs": [], "success_wins": 0, "success_losses": 0, "both_failed": 0}
    for seed in seeds:
        c, r = rows[seed, candidate], rows[seed, reference]
        if c["valid"] and r["valid"]:
            result["pairs"].append((c["time"] - r["time"], seed, c, r))
        elif c["valid"]:
            result["success_wins"] += 1
        elif r["valid"]:
            result["success_losses"] += 1
        else:
            result["both_failed"] += 1
    return result


def build_report(root, manifest, data, expected_jobs, evidence_files):
    seeds = list(range(len(manifest["seeds"])))
    q3, q4 = data[3], data[4]
    baseline = next(c["name"] for c in q4["configs"] if not c.get("enabled") and not c.get("local_order"))
    route = next(c["name"] for c in q4["configs"] if not c.get("enabled") and c.get("local_order"))
    v1 = next(c["name"] for c in q4["configs"] if c.get("enabled") and c.get("depth") == 1)
    labels = {q3["names"][0]: "Q3当前策略", baseline: "Q4基线", route: "Q4仅路线重排", v1: "Q4诊断v1"}
    pieces = ["# B题还原演练引擎逐种子评测结果",
              f"本报告对应冻结提交 `{manifest['git_commit']}`，网格版本 `{manifest['grid_version']}`。"
              f"共{len(seeds)}个不同原始种子，Q3一种策略、Q4三种策略，合计{expected_jobs}次本地完整计划运行。"
              "每个案例独立子进程，策略只接收观测响应，真值仅用于评价器包含性审计。",
              "**证据范围：还原演练生成器＋独立本地仿真引擎。该种子集包含结构压力输入，不是iid随机样本，"
              "不能据此套用独立同分布的失败率置信上界；不是官方正式种子，也不是历史518种子回执的完整复跑。"
              "没有启动官方App或官方正式测试。**",
              "本轮只接入网格稳定化版本与实验系统修复；没有加入首次命中估价、短程光学尝试或重新调参。"
              f"单案例预算为真实{manifest['limits']['real_s']}秒、虚拟{manifest['limits']['virtual_s']}秒。",
              "## 1. 验收状态与统计口径"]
    for problem in (3, 4):
        acc = data[problem]["acceptance"]
        pieces.append(f"- Q{problem}：`accept={str(acc['accept']).lower()}`；"
                      f"`experiment_valid={str(acc['experiment_valid']).lower()}`；"
                      f"`all_runs_full_clear={str(acc['all_runs_full_clear']).lower()}`；"
                      f"预期/实得{acc['expected_run_count']}/{acc['observed_run_count']}。"
                      f"失败原因：`{json.dumps(acc['failure_reasons'], ensure_ascii=False)}`。")
    pieces.append("上述验收值直接读取各题 `acceptance.json`，本报告不改写验收结果。"
                  "`accept`仅表示冻结计划的数据完整性和全部完成，性能结论单独报告。"
                  "所有耗时分位数只统计有效且全部清除的案例；失败/超时不会被当作较快样本。"
                  "成功率的分母为该方案计划案例数，秒/源均以场景总源数归一化。")
    performance = q4["acceptance"].get("performance", {})
    if v1 in performance:
        item = performance[v1]
        pieces.append(f"评价器记录的v1相对基线性能结论：`valid={str(item['valid']).lower()}`，"
                      f"`outcome={item['outcome']}`，配对均值差{number(item['mean_delta'], signed=True)}秒/源。"
                      "这是描述性配对结果，不是显著性检验。")
    pieces.append("## 2. 总体结果")
    records = []
    for problem in (3, 4):
        for name in data[problem]["names"]:
            s = data[problem]["summary"][name]
            records.append([labels[name], f"{s['all_clear']}/{s['expected_n']}",
                            percent(s["all_clear"] / s["expected_n"]), s["timed_n"],
                            *[number(s[k]) for k in ("mean", "P95", "P99", "max")]])
    pieces.append(table(["方案", "全清除案例", "成功率", "有效耗时n", "均值s/源", "P95", "P99", "最大"], records))
    details = []
    for name in q4["names"]:
        s = q4["summary"][name]
        details.append([labels[name], number(s.get("mean_distance") / 1000 if s.get("mean_distance") is not None else None),
                        percent(s.get("fallback_rate")), s.get("fallback_count"), s.get("diagnostic_count"),
                        s.get("clear_attempts"), s.get("optical_clear_attempts")])
    pieces.append(table(["Q4方案", "平均距离km", "发生兜底的案例比例", "兜底总次数", "诊断测量总数", "清除尝试总数", "光学清除尝试"], details))
    pieces.append("## 3. v1相对两种参照的配对差")
    comparisons = {reference: paired(q4["rows"], v1, reference, seeds) for reference in (baseline, route)}
    pair_rows = []
    for reference, comparison in comparisons.items():
        pairs = comparison["pairs"]
        deltas = [p[0] for p in pairs]
        delta = statistics.fmean(deltas) if deltas else None
        ref_mean = statistics.fmean(p[3]["time"] for p in pairs) if pairs else None
        pair_rows.append([labels[reference], len(pairs), number(delta, signed=True),
                          percent(-delta / ref_mean if ref_mean else None),
                          number(statistics.median(deltas) if deltas else None, signed=True),
                          number(percentile(deltas, 95), signed=True),
                          sum(d < -1e-6 for d in deltas), sum(d > 1e-6 for d in deltas),
                          sum(abs(d) <= 1e-6 for d in deltas)])
    pieces.append(table(["参照", "双方成功配对n", "平均Δs/源", "均值降低比例", "Δ中位数", "Δ的P95", "v1更快", "v1更慢", "持平"], pair_rows))
    pieces.append("Δ定义为v1耗时减参照耗时，负值代表v1更快；降低比例使用同一批双方成功案例的参照均值。"
                  "Δ的P95是逐例差值的分位数，不是两方案P95相减。仅路线重排方案用于分离路线收益，"
                  "不能将v1相对原基线的全部改善都归因于诊断测量。")
    pieces.append(table(["参照", "仅v1成功", "仅参照成功", "双方均未有效成功"],
                        [[labels[r], c["success_wins"], c["success_losses"], c["both_failed"]]
                         for r, c in comparisons.items()]))
    pieces.append("## 4. v1最差10例与最大退化案例")
    worst = sorted((q4["rows"][seed, v1] for seed in seeds if q4["rows"][seed, v1]["valid"]),
                   key=lambda row: (-row["time"], row["seed_number"]))[:10]
    pieces.append("v1最差10例按有效全部清除案例的秒/源排序：")
    pieces.append(table(["seed", "来源族", "源数/定向数", "基线", "仅路线", "v1 s/源", "诊断/兜底次数", "seed_hex"],
                        [[row["seed_number"], FAMILIES.get(row["family"], row["family"]),
                          f"{row['source_count']}/{row.get('directional_count', '—')}",
                          number(q4["rows"][row["seed_number"], baseline]["time"]),
                          number(q4["rows"][row["seed_number"], route]["time"]), number(row["time"]),
                          f"{row.get('diagnostic_count', '—')}/{row.get('fallback_count', '—')}", f"`{row['seed_hex']}`"]
                         for row in worst]))
    for reference, comparison in comparisons.items():
        regressions = sorted((p for p in comparison["pairs"] if p[0] > 1e-6), key=lambda p: (-p[0], p[1]))[:10]
        pieces.append(f"相对{labels[reference]}的最大退化案例（只列正Δ，最多10例）：")
        if not regressions:
            pieces.append("没有双方成功但v1耗时增加超过1e-6秒/源的案例。")
        else:
            pieces.append(table(["seed", "参照s/源", "v1 s/源", "Δs/源", "增幅", "seed_hex"],
                                [[seed, number(r["time"]), number(c["time"]), number(delta, signed=True),
                                  percent(delta / r["time"] if r["time"] else None), f"`{c['seed_hex']}`"]
                                 for delta, seed, c, r in regressions]))
    failures = [row for problem in (3, 4) for row in data[problem]["rows"].values() if not row["valid"]]
    if failures:
        pieces.append(f"另有{len(failures)}条未有效全部清除记录，不进入上述速度榜单。前20条如下，其余见classified_cases.csv：")
        pieces.append(table(["方案", "seed", "状态", "清除/总数", "错误", "seed_hex"],
                            [[labels.get(r["variant"], r["variant"]), r["seed_number"], r["status"],
                              f"{r['cleared']}/{r['total']}", r.get("error", ""), f"`{r['seed_hex']}`"]
                             for r in failures[:20]]))
    pieces.append("## 5. 全部有效案例与尾部案例的阶段占比")
    pieces.append("全体占比＝该阶段耗时总和/全部有效成功案例总耗时；尾部占比采用各方案自身秒/源≥P95的案例，"
                  "并列值全部计入。不同方案尾部集合可能不同，不能把此表当作相同案例的因果分解。"
                  "移动时间记入发起该动作的阶段，证书清除单列。")
    phase_rows = []
    for problem in (3, 4):
        for name in data[problem]["names"]:
            profile = data[problem]["profile"].get(name)
            if not profile:
                continue
            for stage, chinese in STAGES.items():
                s = profile["stages"][stage]
                phase_rows.append([labels[name], chinese, profile["n"], len(profile["tail_cases"]),
                                   percent(s["aggregate_fraction"]), percent(s["tail_aggregate_fraction"]),
                                   number(s.get("P95_seconds_per_source")), number(s.get("P99_seconds_per_source"))])
    pieces.append(table(["方案", "阶段", "全体n", "尾部n", "全体耗时占比", "尾部耗时占比", "阶段P95 s/源", "阶段P99 s/源"], phase_rows))
    v1_profile = q4["profile"].get(v1)
    if v1_profile:
        dominant = max(v1_profile["stages"], key=lambda k: v1_profile["stages"][k]["aggregate_fraction"])
        tail_dominant = max(v1_profile["stages"], key=lambda k: v1_profile["stages"][k]["tail_aggregate_fraction"])
        pieces.append(f"本轮v1全体耗时占比最高的阶段是**{STAGES[dominant]}**，"
                      f"尾部最高的是**{STAGES[tail_dominant]}**。这用于确定后续审计重点，"
                      "不能单凭阶段占比判断该阶段能够被优化的幅度。")
    pieces.append("## 6. 种子来源族与全定向子集")
    family_counts = Counter(item["family"] for item in manifest["seeds"])
    pieces.append("冻结种子组成：" + "；".join(f"{FAMILIES.get(f, f)} {n}个" for f, n in family_counts.items()) + "。"
                  "以下均为该组有效全部清除案例的描述统计；样本数为1的小组不具备分布推断意义。")
    for problem in (3, 4):
        records = []
        for family in family_counts:
            for name in data[problem]["names"]:
                group = [row for row in data[problem]["rows"].values() if row["variant"] == name and row["family"] == family]
                values = [row["time"] for row in group if row["valid"]]
                s = stats(values)
                records.append([FAMILIES.get(family, family), labels[name], f"{len(values)}/{len(group)}",
                                percent(len(values) / len(group)), *[number(s[k]) for k in ("mean", "P95", "P99", "max")]])
        pieces.append(f"Q{problem}分组结果：")
        pieces.append(table(["来源族", "方案", "全清除/组内n", "成功率", "均值s/源", "P95", "P99", "最大"], records))
    directional_seeds = [seed for seed in seeds if q4["rows"][seed, baseline]["all_directional"]]
    pieces.append(f"Q4全定向子集共{len(directional_seeds)}个种子，依据冻结场景的全部源类型筛选；"
                  "该子集与上面的来源族重叠，不是额外独立实验。")
    records = []
    for name in q4["names"]:
        group = [q4["rows"][seed, name] for seed in directional_seeds]
        values = [row["time"] for row in group if row["valid"]]
        s = stats(values)
        records.append([labels[name], f"{len(values)}/{len(group)}", percent(len(values) / len(group)) if group else "—",
                        *[number(s[k]) for k in ("mean", "P95", "P99", "max")]])
    pieces.append(table(["全定向子集方案", "全清除/子集n", "成功率", "均值s/源", "P95", "P99", "最大"], records))
    pieces.append("全定向子集seed编号：" + ", ".join(map(str, directional_seeds)) + "。")
    pieces.append("## 7. 证据文件与复现边界")
    pieces.append("- `manifest.json`：冻结种子、配置、场景与源码指纹、运行环境。\n"
                  "- `scenes/`：Q3/Q4全部冻结场景；包含真值，仅供评价与审计。\n"
                  "- `q3/`、`q4/`：原始/分类CSV、summary、acceptance、stage_profile，以及逐例rows和压缩轨迹。\n"
                  "- `completion.json`、`run_request.json`：完整计划与完成计数。")
    pieces.append(f"全部{expected_jobs}次运行共享{len(seeds)}个种子，并且不同方案、Q3/Q4重复使用种子，不能把运行次数当作独立样本量。"
                  "本轮结果不代表官方正式场景分布，也不证明独立仿真引擎与原版应用在所有数值边界上完全等价。"
                  "保留覆盖与MEC清除证书的理论口径；有限预算内的完成表现以本报告实际记录为准。"
                  "本报告没有使用旧网格版本的数值拼接新版本结果。")
    pieces.append("报告输入文件SHA-256（用于定位本次报告的精确证据版本）：")
    pieces.append(table(["相对路径", "SHA-256"], [[path.relative_to(root).as_posix(), f"`{sha256(path)}`"] for path in evidence_files]))
    return "\n\n".join(pieces) + "\n"


def match_auxiliary(main_manifest, main_data, aux_manifest, aux_data):
    need(main_manifest["source_hashes"] == aux_manifest["source_hashes"], "辅助对照源码与主实验冻结版本不一致")
    matched = []
    for aux_config in aux_data[4]["configs"]:
        stem = aux_config["name"].removesuffix("_" + aux_manifest["grid_version"])
        main_config = next(c for c in main_data[4]["configs"]
                           if c["name"].removesuffix("_" + main_manifest["grid_version"]) == stem)
        normalize = lambda c: {key: value for key, value in c.items() if key not in ("name", "grid_version")}
        need(normalize(main_config) == normalize(aux_config), f"辅助对照算法配置存在额外变化：{stem}")
        for seed in aux_data[4]["indices"]:
            current = main_data[4]["rows"][seed, main_config["name"]]
            other = aux_data[4]["rows"][seed, aux_config["name"]]
            need(current["seed_hex"] == other["seed_hex"] and current["scene_hash"] == other["scene_hash"],
                 f"辅助对照场景或种子不一致：{stem} seed={seed}")
        matched.append((stem, main_config["name"], aux_config["name"]))
    need(len(matched) == len(main_data[4]["configs"]), "辅助对照方案不完整")
    return matched


def auxiliary_evidence(root, acceptance, files):
    return [f"辅助证据目录：`{root}`。其验收原值为 `accept={str(acceptance['accept']).lower()}`，"
            f"失败原因：`{json.dumps(acceptance['failure_reasons'], ensure_ascii=False)}`。",
            table(["辅助输入文件", "SHA-256"],
                  [[path.relative_to(root).as_posix(), f"`{sha256(path)}`"] for path in files])]


def legacy_section(root, main_manifest, main_data):
    manifest, data, jobs, files = load_completed(root, full=False)
    need(manifest["grid_version"] == "grid_v0" and main_manifest["grid_version"] == "grid_v1",
         "legacy对照应为grid_v0到主实验grid_v1")
    need(data[4]["device"] == main_data[4]["device"], "网格版本对照混用了不同设备")
    matches = match_auxiliary(main_manifest, main_data, manifest, data)
    lines = ["## 8. 网格旧版与新版的相同种子对照",
             f"旧网格辅助计划共{len(data[4]['indices'])}个种子、{jobs}次Q4运行，与主实验相同seed、场景、"
             "算法配置及设备逐例配对，配置仅网格版本不同。以下Δ＝grid_v1减grid_v0；负值为新版更快。"
             "该子集与主实验重叠，不是新增独立种子。"]
    records, state_rows = [], []
    for stem, main_name, aux_name in matches:
        pairs = []
        only_new = only_old = both_failed = 0
        for seed in data[4]["indices"]:
            current, old = main_data[4]["rows"][seed, main_name], data[4]["rows"][seed, aux_name]
            if current["valid"] and old["valid"]:
                pairs.append((current["time"] - old["time"], current["time"], old["time"]))
            elif current["valid"]:
                only_new += 1
            elif old["valid"]:
                only_old += 1
            else:
                both_failed += 1
        ds, newer, older = ([p[index] for p in pairs] for index in range(3))
        delta = statistics.fmean(ds) if ds else None
        old_mean = statistics.fmean(older) if older else None
        records.append([stem, len(pairs), number(old_mean), number(statistics.fmean(newer) if newer else None),
                        number(delta, signed=True), percent(-delta / old_mean if old_mean else None),
                        number(percentile(newer, 95) - percentile(older, 95) if pairs else None, signed=True),
                        sum(d < -1e-6 for d in ds), sum(d > 1e-6 for d in ds), sum(abs(d) <= 1e-6 for d in ds)])
        state_rows.append([stem, only_new, only_old, both_failed])
    lines.append(table(["算法", "双方成功n", "旧均值s/源", "新均值s/源", "平均Δ", "均值降低", "新P95−旧P95", "新更快", "新更慢", "持平"], records))
    lines.append(table(["算法", "仅新版成功", "仅旧版成功", "双方均未有效成功"], state_rows))
    lines.extend(auxiliary_evidence(root, data[4]["acceptance"], files))
    return "\n\n".join(lines)


def cuda_section(root, main_manifest, main_data, section_number=9):
    manifest, data, jobs, files = load_completed(root, full=False)
    need(manifest["grid_version"] == main_manifest["grid_version"], "CUDA对照网格版本不一致")
    need(main_data[4]["device"] == "cpu" and data[4]["device"].startswith("cuda"), "CUDA对照设备标记不符")
    matches = match_auxiliary(main_manifest, main_data, manifest, data)
    tolerances = {"virtual_time_s": 1e-6, "distance": 1e-6, "fallback_count": 0,
                  "clear_attempts": 0, "detect_count": 0, "switch_count": 0, "diagnostic_count": 0}
    lines = [f"## {section_number}. CUDA与CPU的相同案例指标一致性",
             f"CUDA辅助计划共{len(data[4]['indices'])}个种子、{jobs}次Q4运行，逐一对应主实验中的CPU案例。"
             "要求相同配置和场景；虚拟时间与距离采用绝对误差≤1e-6，五项计数必须精确相等。"
             "不比较runtime、进程启动或设备初始化耗时，也不据此声称GPU加速比。"]
    rows, differences = [], []
    for stem, main_name, aux_name in matches:
        compared = equal = unavailable = 0
        maximum = dict.fromkeys(tolerances, 0.)
        for seed in data[4]["indices"]:
            cpu, gpu = main_data[4]["rows"][seed, main_name], data[4]["rows"][seed, aux_name]
            if not (cpu["valid"] and gpu["valid"]):
                unavailable += 1
                differences.append([stem, seed, "状态/完成度", cpu["status"], gpu["status"], "不可核验", f"`{cpu['seed_hex']}`"])
                continue
            compared += 1
            pair_equal = True
            for field, tolerance in tolerances.items():
                a, b = finite(cpu[field]), finite(gpu[field])
                delta = abs(a - b)
                maximum[field] = max(maximum[field], delta)
                if delta > tolerance:
                    pair_equal = False
                    differences.append([stem, seed, field, a, b, format(delta, ".12g"), f"`{cpu['seed_hex']}`"])
            equal += pair_equal
        rows.append([stem, len(data[4]["indices"]), compared, equal, unavailable,
                     format(maximum["virtual_time_s"], ".12g"), format(maximum["distance"], ".12g"),
                     max(maximum[k] for k in tolerances if k not in ("virtual_time_s", "distance")),
                     "逐例指标一致" if equal == len(data[4]["indices"]) else "存在差异或不可核验案例"])
    lines.append(table(["算法", "计划n", "双方成功n", "指标一致n", "不可核验n", "最大时间差s", "最大距离差m", "最大计数差", "观测结论"], rows))
    if differences:
        lines.append(f"共{len(differences)}条指标差异或不可核验记录，前30条如下；完整原始数据保留在两侧cases.csv。")
        lines.append(table(["算法", "seed", "字段", "CPU", "CUDA", "绝对差", "seed_hex"], differences[:30]))
    lines.append("这些一致性统计由报告脚本对已完成案例逐例读取比较；不会改写辅助实验或主实验的acceptance.json。")
    lines.extend(auxiliary_evidence(root, data[4]["acceptance"], files))
    return "\n\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path(__file__).resolve().parents[1] / "results/recovered/grid_v1_519")
    parser.add_argument("--output", type=Path, help="Defaults to INPUT/RESULTS.md")
    parser.add_argument("--legacy-root", type=Path, help="Completed Q4 grid_v0 subset, paired against the main CPU run")
    parser.add_argument("--cuda-root", type=Path, help="Completed Q4 CUDA subset, compared against the main CPU run")
    args = parser.parse_args()
    root = args.input.resolve()
    try:
        manifest, data, expected_jobs, files = load_completed(root)
        text = build_report(root, manifest, data, expected_jobs, files)
        if args.legacy_root:
            text += "\n" + legacy_section(args.legacy_root.resolve(), manifest, data) + "\n"
        if args.cuda_root:
            text += "\n" + cuda_section(args.cuda_root.resolve(), manifest, data,
                                        section_number=9 if args.legacy_root else 8) + "\n"
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as error:
        print(f"未生成报告：证据尚未完整或不一致。{error}", file=sys.stderr)
        return 2
    output = args.output.resolve() if args.output else root / "RESULTS.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(f"已生成 {output}；读取验收结果，未运行仿真或修改实验数据。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
