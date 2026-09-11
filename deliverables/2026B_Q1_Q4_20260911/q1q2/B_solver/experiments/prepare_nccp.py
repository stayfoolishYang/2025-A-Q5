"""Prepare both frozen NCCP cohorts; never execute a solver or simulator service.

Outputs are compatible with recovered_benchmark.py --resume. The destination
must not exist. Both development and holdout inputs are prepared together before
candidate results are available; PREPARED.json is written only on completion.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import platform
import subprocess
import sys


BASE = Path(__file__).resolve().parents[1]
REPOSITORY = BASE.parent
REFERENCE_COMMIT = "3c4e844a010a36d8a441231025e2c1c9d2bc2cce"
HOLDOUT_NAMESPACE = "2026B-NCCP-holdout-20260911:"
REFERENCE_VARIANTS = {"3": "P3_current_grid_v1", "4": "P4_diagnostic_v1_grid_v1"}
LIMITS = {"real_s": 1200, "virtual_s": 360000}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write_new(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def reference_inputs(reference_root):
    manifest = read_json(reference_root / "manifest.json")
    require(manifest["git_commit"] == REFERENCE_COMMIT, "Reference must be the frozen 3c4e844 experiment")
    require(manifest["grid_version"] == "grid_v1", "Reference grid version must be grid_v1")
    seeds = manifest["seeds"]
    require(len(seeds) == 519 and [item["seed"] for item in seeds] == list(range(519)),
            "Reference must contain the original 519 numbered seeds")
    require(len({item["seed_hex"] for item in seeds}) == 519, "Reference seed_hex values are not unique")
    q3_acceptance = read_json(reference_root / "q3/acceptance.json")
    require(q3_acceptance["accept"] is True and q3_acceptance["all_runs_full_clear"] is True,
            "The reference Q3 evidence must be complete and all-clear")
    with (reference_root / "q3/cases.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    require(len(rows) == 519 and {int(row["seed"]) for row in rows} == set(range(519)),
            "Reference Q3 cases are missing or duplicated")
    for row in rows:
        require(row["variant"] == REFERENCE_VARIANTS["3"] and row["run_status"] == "FULL_CLEAR"
                and not row["error"] and int(row["cleared"]) == int(row["total"]),
                "Reference Q3 row is not a full-clear baseline result")
        require(math.isfinite(float(row["mean_time_per_source"])), "Invalid reference Q3 timing")
        scene_key = f"q3_{int(row['seed']):04d}.json"
        require(row["scene_hash"] == manifest["scene_hashes"][scene_key], "Reference Q3 scene hash mismatch")
    worst = sorted(rows, key=lambda row: (-float(row["mean_time_per_source"]), int(row["seed"])))[:3]
    return manifest, [{"source_seed": int(row["seed"]),
                       "mean_time_per_source": float(row["mean_time_per_source"])} for row in worst]


def development_seeds(reference, worst_q3):
    stride = set(range(0, 519, 6))
    anchors = set(range(6)) | {105, 283, 366, 455, 518}
    q3_tail = {row["source_seed"] for row in worst_q3}
    selected = stride | anchors | q3_tail
    require(len(selected) <= 100, "Fixed development selection exceeds 100; do not silently truncate")
    additions = []
    for source_seed in range(519):
        if len(selected) == 100:
            break
        if source_seed not in selected:
            selected.add(source_seed)
            additions.append(source_seed)
    require(len(selected) == 100, "Development cohort must contain exactly 100 seeds")
    records = []
    for local_seed, source_seed in enumerate(sorted(selected)):
        old = reference["seeds"][source_seed]
        reasons = (["stride6"] if source_seed in stride else [])
        reasons += ["fixed_anchor"] if source_seed in anchors else []
        reasons += ["reference_q3_worst3"] if source_seed in q3_tail else []
        reasons += ["ascending_fill"] if source_seed in additions else []
        records.append({"seed": local_seed, "source_seed": source_seed,
                        "seed_hex": old["seed_hex"], "family": old["family"],
                        "selection_reasons": reasons})
    return records, {"stride": "range(0, 519, 6)", "fixed_anchors": sorted(anchors),
                     "reference_q3_worst3": worst_q3, "ascending_fill": additions,
                     "selected_source_seeds": sorted(selected),
                     "rule": "Union stride, anchors, and three largest Q3 seconds/source; "
                             "break timing ties by old seed ascending; fill smallest missing old indices "
                             "until 100; sort selected old indices; assign new local indices 0..99."}


def holdout_seeds(reference):
    old = {item["seed_hex"] for item in reference["seeds"]}
    records = [{"seed": index, "source_seed": None,
                "seed_hex": hashlib.sha256(f"{HOLDOUT_NAMESPACE}{index}".encode("utf-8")).hexdigest(),
                "family": "sha256_nccp_holdout", "derivation_index": index}
               for index in range(256)]
    values = {item["seed_hex"] for item in records}
    require(len(values) == 256, "Holdout seed collision; do not silently alter the stated derivation")
    require(not values & old, "Holdout overlaps the original 519 seeds; freeze a new explicit experiment")
    return records


def paired_configs(reference):
    result = {}
    for problem, baseline_name in REFERENCE_VARIANTS.items():
        matches = [c for c in reference["configs"][problem] if c["name"] == baseline_name]
        require(len(matches) == 1, f"Missing or ambiguous reference configuration: {baseline_name}")
        baseline = copy.deepcopy(matches[0])
        require("clearance_point" not in baseline, "Reference configuration already selects a clearance point")
        candidate = copy.deepcopy(baseline)
        candidate["name"] += "_nccp"
        candidate["clearance_point"] = "nccp"
        changed = {key for key in set(baseline) | set(candidate) if baseline.get(key) != candidate.get(key)}
        require(changed == {"name", "clearance_point"}, "Candidate changed more than its name and clearance point")
        require(baseline == matches[0] and digest(baseline) == digest(matches[0]), "Reference configuration changed")
        result[problem] = [baseline, candidate]
    return result


def fingerprint_changes(old, current):
    return [{"path": key, "old_sha256": old.get(key), "current_sha256": current.get(key),
             "status": "added" if key not in old else "removed" if key not in current else "modified"}
            for key in sorted(set(old) | set(current)) if old.get(key) != current.get(key)]


def prepare(reference_root, simulator_root, output):
    reference_root, simulator_root, output = (Path(p).resolve() for p in (reference_root, simulator_root, output))
    if output.exists():
        raise FileExistsError(f"Output already exists; no file will be overwritten: {output}")
    # All validation and scenario generation precede the first output write.
    reference, worst_q3 = reference_inputs(reference_root)
    configs = paired_configs(reference)
    development, selection = development_seeds(reference, worst_q3)
    holdout = holdout_seeds(reference)
    cohorts = {"development100": development, "holdout256": holdout}
    require(not {r["seed_hex"] for r in development} & {r["seed_hex"] for r in holdout}, "Cohorts overlap")
    sys.path.insert(0, str(BASE))
    sys.path.insert(0, str(simulator_root))
    import numpy as np
    from recovered_benchmark import source_hashes
    from scenario_io import generate_document, load_scenario

    for module_name in ("engine", "scenario_io", "recovered_generator"):
        # Reject an earlier import from another simulator directory.
        module = __import__(module_name)
        require(Path(module.__file__).resolve() == (simulator_root / f"{module_name}.py").resolve(),
                f"Wrong simulator module loaded: {module_name}")
    current = source_hashes(simulator_root)
    for name in ("engine.py", "scenario_io.py", "recovered_generator.py"):
        require(current[f"engine/{name}"] == reference["source_hashes"][f"engine/{name}"],
                f"Recovered engine differs from reference: {name}")
    script_hash = file_hash(__file__)
    git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPOSITORY, text=True).strip()
    git_status = subprocess.check_output(["git", "status", "--porcelain", "--", "B_solver"],
                                         cwd=REPOSITORY, text=True).splitlines()
    config_hashes = {problem: {config["name"]: digest(config) for config in group}
                     for problem, group in configs.items()}
    shared_seed_plan = {"development100": development, "holdout256": holdout,
                        "development_selection": selection, "holdout_namespace": HOLDOUT_NAMESPACE,
                        "holdout_indices": [0, 255], "overlap_with_reference519": 0}
    shared_seed_plan_hash = digest(shared_seed_plan)
    plan = {"schema": "nccp-paired-plan-v1", "experiment_id": "nccp_20260911",
            "shared_seed_plan": shared_seed_plan, "configs": configs, "config_hashes": config_hashes,
            "solver_reference_commit": REFERENCE_COMMIT, "git_commit": git_commit,
            "source_hashes": current, "reference_source_hashes": reference["source_hashes"],
            "prepare_script_sha256": script_hash, "limits": LIMITS,
            "workers_recommended": 2, "blas_threads_per_worker": 1,
            "execution_order": ["prepare_both_cohorts", "development400", "development_integrity_and_reference_actions_audit",
                                "holdout1024_if_development_gate_passes"],
            "primary_gate": "Failures, protocol/timeout errors, and incomplete clearance precede speed comparisons.",
            "baseline_requirement": "Run reference configurations afresh; development baseline actions must match "
                                    "the original reference traces. Never fill new output with historical rows.",
            "holdout_policy": "Freeze both cohorts before observing candidate results. If candidate code/configuration "
                              "changes after results are inspected, declare a new experiment; continued tuning on this "
                              "holdout cannot be described as independent validation.",
            "evidence_scope": "Recovered practice scenes only; neither official formal cases nor an iid sample."}
    plan_hash = digest(plan)
    scenes, scene_hashes = {}, {}
    for cohort, records in cohorts.items():
        scenes[cohort], scene_hashes[cohort] = {}, {}
        for record in records:
            for problem in (3, 4):
                native = generate_document(problem=problem, seed_hex=record["seed_hex"], format="native")
                load_scenario(native)  # Validate scene structure and recovered rules; no Engine is run.
                filename = f"q{problem}_{record['seed']:04d}.json"
                signature = digest(native)
                if record["source_seed"] is not None:
                    old_filename = f"q{problem}_{record['source_seed']:04d}.json"
                    require(signature == reference["scene_hashes"][old_filename],
                            f"Regenerated reference scene differs: {old_filename}")
                scenes[cohort][filename] = native
                scene_hashes[cohort][filename] = signature
    require(source_hashes(simulator_root) == current and file_hash(__file__) == script_hash,
            "Code changed during preparation; no output has been written")
    blas = io.StringIO()
    with contextlib.redirect_stdout(blas):
        np.show_config()
    prepared_at = datetime.now(timezone.utc).isoformat()
    # exist_ok=False also handles a destination created after the initial check.
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "PLAN.json", plan)
    manifests = {}
    for cohort, records in cohorts.items():
        destination = output / cohort
        destination.mkdir()
        for filename, native in scenes[cohort].items():
            write_new(destination / "scenes" / filename, native)
        manifest = {
            "schema": "recovered-benchmark-v1", "experiment_id": "nccp_20260911", "cohort": cohort,
            "seeds": records, "configs": copy.deepcopy(configs), "config_hashes": config_hashes,
            "grid_version": "grid_v1", "git_commit": git_commit, "git_status_b_solver_at_preparation": git_status,
            "solver_reference_commit": REFERENCE_COMMIT, "reference_dataset_root": str(reference_root),
            "reference_manifest_sha256": file_hash(reference_root / "manifest.json"),
            "reference_q3_cases_sha256": file_hash(reference_root / "q3/cases.csv"),
            "reference_source_hashes": reference["source_hashes"], "source_hashes": current,
            "source_fingerprint_diff": fingerprint_changes(reference["source_hashes"], current),
            "scene_hashes": scene_hashes[cohort], "simulator_root": str(simulator_root),
            "prepare_script_sha256": script_hash, "prepare_script_path": str(Path(__file__).resolve()),
            "plan_hash": plan_hash, "shared_seed_plan_hash": shared_seed_plan_hash,
            "cohort_seed_hash": digest(records), "prepared_at_utc": prepared_at,
            "reference_baseline_variants": REFERENCE_VARIANTS,
            "reference_trace_pattern": "q{problem}/traces/{baseline_variant}_{source_seed:04d}.json.gz",
            "reference_trace_applicability": "exact_actions_required" if cohort == "development100" else "not_applicable_new_seeds",
            "development_cohort_root": str(output / "development100"),
            "development_audit_path": str(output / "development100/NCCP_AUDIT.json"),
            "seed_design": selection if cohort == "development100" else {
                "namespace": HOLDOUT_NAMESPACE, "input": "UTF-8 namespace + decimal i, i=0..255",
                "derivation": "SHA256", "distinct_seed_count": 256, "overlap_with_reference519": 0},
            "python": sys.version, "executable": sys.executable, "numpy": np.__version__,
            "blas": blas.getvalue(), "platform": platform.platform(),
            "evidence": "recovered_practice_engine_local", "formal_tests": 0,
            "limits": LIMITS, "workers_recommended": 2, "blas_threads_per_worker": 1,
            "planned_run_count": len(records) * 4, "prepared_only": True,
            "algorithm_changes": "Reference config is copied unchanged. Candidate differs only by name suffix "
                                 "_nccp and clearance_point=nccp; both run on this same current source snapshot.",
            "holdout_policy": plan["holdout_policy"], "baseline_requirement": plan["baseline_requirement"],
            "acceptance_policy": plan["primary_gate"], "evidence_scope": plan["evidence_scope"],
        }
        write_new(destination / "manifest.json", manifest)
        manifests[cohort] = file_hash(destination / "manifest.json")
    require(source_hashes(simulator_root) == current and file_hash(__file__) == script_hash,
            "Code changed while writing inputs. PREPARED.json was not written; do not run this incomplete preparation")
    write_new(output / "PREPARED.json", {
        "status": "INPUTS_PREPARED_ONLY", "plan_hash": plan_hash,
        "shared_seed_plan_hash": shared_seed_plan_hash, "manifest_sha256": manifests,
        "scene_count": sum(len(group) for group in scenes.values()), "planned_run_count": 1424,
        "candidate_execution_performed": False, "prepared_at_utc": prepared_at,
        "next_step": "Run development400, audit data and exact reference baseline actions, then decide on holdout1024.",
    })
    return {"output": str(output), "plan_hash": plan_hash, "development_seeds": 100,
            "holdout_seeds": 256, "prepared_scenes": 712, "planned_runs": 1424,
            "solver_runs_started": 0, "formal_tests": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-root", type=Path, default=BASE / "results/recovered/grid_v1_519")
    parser.add_argument("--sim-root", type=Path, default=Path("G:/QQ/jammers_linux"))
    parser.add_argument("--output", type=Path, default=Path("J:/2026B_experiments/nccp_20260911"),
                        help="New destination root containing development100 and holdout256; must not exist")
    args = parser.parse_args()
    result = prepare(args.reference_root, args.sim_root, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
