"""Campaign planning contracts, authored for server execution only.

No tests in this file were run on the local host. Most tests are pure planning;
the final authority comparison imports refinement only when that test executes
on the server, never during campaign_plan module import or test collection.
"""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest

from drying.campaign_plan import (
    BASE_CONFIGS, ROOT, CampaignPlanError, expand_campaign,
    load_campaign_spec, validate_campaign_spec,
)
from drying.config import RunConfig


@pytest.fixture
def campaign_sources(tmp_path):
    (tmp_path / "configs").mkdir()
    for relative in BASE_CONFIGS:
        shutil.copyfile(ROOT / relative, tmp_path / relative)
    spec = load_campaign_spec(ROOT / "configs/server_full.json")
    return tmp_path, spec


def _run_map(plan):
    return {record["run_key"]: record for record in plan["runs"]}


def test_complete_finite_plan_keeps_all_sources_and_deduplicates_shared_runs(campaign_sources):
    root, spec = campaign_sources
    before = {p: (root / p).read_bytes() for p in BASE_CONFIGS}
    plan = expand_campaign(spec, root=root)
    assert plan["execution_status"] == "PLANNED_NOT_EXECUTED"
    assert plan["stage07"] == plan["stage08"] == "NOT_RUN"
    assert len(plan["source_configs"]) == len(plan["base_runs"]) == 11
    assert {row["path"] for row in plan["source_configs"]} == set(BASE_CONFIGS)
    assert plan["run_count"] == len(plan["runs"]) == 67
    assert len({row["config_fingerprint"] for row in plan["runs"]}) == 67
    runs = _run_map(plan)
    q1 = plan["cases"]["Q1"]
    assert q1["categories"]["radial"] == [plan["base_runs"][name] for name in ("B_Q1", "B_Q1_nr40", "B_Q1_nr80")]
    assert q1["reference_run"] == plan["base_runs"]["B_Q1_nr80"]
    for case in plan["cases"].values():
        reference = case["reference_run"]
        assert all(case["categories"][category][0] == reference for category in ("time", "newton", "dense"))
        assert runs[reference]["config"]["nr"] == 80
    assert plan["budget"]["session_wall_seconds"] == 172800
    assert plan["budget"]["max_run_attempts"] == 3
    assert {p: (root / p).read_bytes() for p in BASE_CONFIGS} == before
    assert not (root / "results").exists()
    json.dumps(plan, allow_nan=False)


def test_plan_records_source_bytes_and_effective_configuration_identity(campaign_sources):
    root, spec = campaign_sources
    plan = expand_campaign(spec, root=root)
    runs = _run_map(plan)
    for source in plan["source_configs"]:
        raw = (root / source["path"]).read_bytes()
        original = RunConfig.from_dict(json.loads(raw.decode("utf-8-sig")))
        assert source["file_sha256"] == sha256(raw).hexdigest()
        assert source["source_config_fingerprint"] == original.fingerprint
        assert source["config_fingerprint"] == runs[source["run_key"]]["config_fingerprint"]
    for record in plan["runs"]:
        assert RunConfig.from_dict(record["config"]).fingerprint == record["config_fingerprint"]


def test_hardware_changes_all_jobs_without_promoting_smoke_or_development(campaign_sources):
    root, spec = campaign_sources
    spec["hardware"].update(cuda_device=2, gpu_memory_mb=4096, memory_mb=8192)
    plan = expand_campaign(spec, root=root)
    for record in plan["runs"]:
        assert all(record["config"][name] == value for name, value in spec["hardware"].items())
    runs = _run_map(plan)
    for name in ("smoke", "C0_fixed_short", "C0_moving_short", "C1_short"):
        cfg = runs[plan["base_runs"][name]]["config"]
        assert cfg["production_eligible"] is False
        assert cfg["execution_purpose"] in {"SMOKE", "FRAMEWORK_INTEGRATION"}
    for source in plan["source_configs"]:
        original = RunConfig.from_json(root / source["path"])
        cfg = runs[source["run_key"]]["config"]
        assert cfg["wall_seconds"] == original.wall_seconds
        assert cfg["max_steps"] == original.max_steps


def test_campaign_budget_change_keeps_all_run_fingerprints_and_keys(campaign_sources):
    root, spec = campaign_sources
    first = expand_campaign(spec, root=root)
    changed = deepcopy(spec)
    changed["budget"].update(session_wall_seconds=3600, max_run_attempts=1, report_rounds=1)
    second = expand_campaign(changed, root=root)
    assert first["plan_fingerprint"] != second["plan_fingerprint"]
    assert first["runs"] == second["runs"]
    assert first["cases"] == second["cases"]


def test_c0_comparators_match_question_geometry_and_nonproduction_identity(campaign_sources):
    root, spec = campaign_sources
    plan = expand_campaign(spec, root=root)
    runs = _run_map(plan)
    comparisons = [row for row in plan["comparisons"] if row["kind"] == "C0_DEGENERATION"]
    assert len(comparisons) == 2
    assert {row["question"] for row in comparisons} == {23, 4}
    for row in comparisons:
        left, right = runs[row["left"]]["config"], runs[row["right"]]["config"]
        different = {name for name in left if left[name] != right[name]}
        assert different == {"route", "nz"}
        assert left["nr"] == right["nr"] == 8
        assert left["tmax"] == right["tmax"] == 60
        assert left["wall_seconds"] == right["wall_seconds"] == 180
        assert left["production_eligible"] is right["production_eligible"] is False


def test_sensitivities_are_eight_one_factor_variants_without_tail_extension(campaign_sources):
    root, spec = campaign_sources
    plan = expand_campaign(spec, root=root)
    runs = _run_map(plan)
    assert len(plan["sensitivities"]) == 8
    factors = {}
    for item in plan["sensitivities"]:
        factors.setdefault(item["case"], set()).add(item["factor"])
        base, variant = runs[item["base_run"]]["config"], runs[item["variant_run"]]["config"]
        assert {key for key in base if base[key] != variant[key]} == set(item["changes"])
        assert len(item["changes"]) == 1
        assert variant["tmax"] == 259200 and variant["radius_tail"] == "NONE"
        assert variant["question"] == base["question"]
    common = {"environment_S1", "window_2p5h", "window_3p5h"}
    assert factors == {"B_Q23": common, "B_Q4": common | {"radius_pchip", "geometry_fixed"}}
    for record in plan["runs"]:
        assert record["config"]["tmax"] <= 259200
        assert record["config"]["radius_tail"] == "NONE"


def test_case_category_and_comparison_references_resolve_to_real_planned_jobs(campaign_sources):
    root, spec = campaign_sources
    plan = expand_campaign(spec, root=root)
    runs = _run_map(plan)
    for name, case in plan["cases"].items():
        assert case["base_run"] in runs and case["reference_run"] in runs
        expected = {"radial", "time", "newton", "dense"}
        if case["route"] == "C":
            expected |= {"axial", "joint"}
        assert set(case["categories"]) == expected
        assert all(len(keys) == 3 and all(key in runs for key in keys) for keys in case["categories"].values())
        reference = runs[case["reference_run"]]["config"]
        assert runs[case["categories"]["radial"][-1]]["config"]["nr"] == reference["nr"]
        if case["route"] == "C":
            assert runs[case["categories"]["axial"][-1]]["config"]["nz"] == reference["nz"]
        if name == "Q1":
            assert case["event_levels"] == [] and not case["requires_event"]
        else:
            assert [level["width"] for level in case["event_levels"]] == [.01, .005, .0025]
            assert all(level["method"] == "ACCEPTED_CHECKPOINT_REINTEGRATION" for level in case["event_levels"])
    for comparison in plan["comparisons"]:
        assert comparison["left"] in runs and comparison["right"] in runs
    assert len([row for row in plan["comparisons"] if row["kind"] == "BC_STRUCTURE"]) == 4
    assert all("event" not in record["config"] and "width" not in record["config"] for record in plan["runs"])


@pytest.mark.parametrize("section,key,value", [
    ("budget", "session_wall_seconds", float("inf")),
    ("budget", "tests_timeout_seconds", 0),
    ("budget", "max_run_attempts", True),
    ("budget", "max_run_attempts", 1.5),
    ("budget", "event_max_levels", 2),
    ("budget", "report_rounds", 0),
    ("hardware", "linear_backend", "CPU_REFERENCE"),
    ("hardware", "cuda_device", -1),
    ("hardware", "gpu_memory_mb", 0),
])
def test_invalid_budgets_and_hardware_fail_before_source_reads(campaign_sources,section,key,value):
    root, spec = campaign_sources
    spec[section][key] = value
    with pytest.raises(CampaignPlanError):
        expand_campaign(spec, root=root / "nonexistent")


def test_missing_duplicate_or_external_sources_and_unsafe_name_fail(campaign_sources):
    root, spec = campaign_sources
    for replacement in (spec["base_configs"][:-1],
                        spec["base_configs"][:-1] + [spec["base_configs"][0]],
                        spec["base_configs"][:-1] + ["../outside.json"]):
        changed = deepcopy(spec); changed["base_configs"] = replacement
        with pytest.raises(CampaignPlanError, match="SOURCES_INVALID"):
            validate_campaign_spec(changed)
    spec["name"] = "../outside"
    with pytest.raises(CampaignPlanError, match="NAME_INVALID"):
        expand_campaign(spec, root=root)


def test_mislabelled_source_cannot_silently_change_the_selected_physics(campaign_sources):
    root, spec = campaign_sources
    path = root / "configs/B_Q4_S0.json"
    original = RunConfig.from_json(path)
    replace(original, geometry="fixed").to_json(path)
    with pytest.raises(CampaignPlanError, match="SOURCE_ROLE_MISMATCH"):
        expand_campaign(spec, root=root)


def test_plan_is_deterministic_json_and_rejects_unsupported_version(campaign_sources):
    root, spec = campaign_sources
    assert expand_campaign(spec, root=root) == expand_campaign(deepcopy(spec), root=root)
    spec["version"] = "future-version"
    with pytest.raises(CampaignPlanError, match="VERSION_UNSUPPORTED"):
        validate_campaign_spec(spec)


def test_server_crosscheck_matches_existing_refinement_planner(campaign_sources):
    # Deliberately inside the test: campaign planning itself must not import
    # NumPy/refinement or execute its module-level numerical initialization.
    from drying.refinement import plan_refinement_configs
    root, spec = campaign_sources
    plan = expand_campaign(spec, root=root)
    runs = _run_map(plan)
    for case in plan["cases"].values():
        base = runs[case["base_run"]]["config"]
        expected = plan_refinement_configs(base)
        for category, keys in case["categories"].items():
            assert [runs[key]["config"] for key in keys] == expected[category]
        if case["requires_event"]:
            assert case["event_levels"] == expected["event"]
