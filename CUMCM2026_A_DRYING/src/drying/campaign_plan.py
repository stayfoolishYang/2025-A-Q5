"""Pure, finite server campaign planning for the unchanged A26-04-v2 model.

Only standard-library modules and RunConfig are imported. No numerical module,
device probe, solver, subprocess or filesystem writer is used here. The runner
owns execution budgets, attempts, output paths and all observed result claims.
"""
from dataclasses import replace
from hashlib import sha256
import json
import math
from pathlib import Path, PureWindowsPath
import re

from .config import RunConfig


ROOT = Path(__file__).resolve().parents[2]
VERSION = "A26-FULL-v1"
BASE_CONFIGS = (
    "configs/smoke.json", "configs/B_Q1.json", "configs/B_Q1_nr40.json",
    "configs/B_Q1_nr80.json", "configs/B_Q23_S0.json", "configs/B_Q4_S0.json",
    "configs/C0_fixed_short.json", "configs/C0_moving_short.json",
    "configs/C1_short.json", "configs/C1_Q23.json", "configs/C1_Q4.json",
)
CASE_SOURCES = {
    "Q1": "configs/B_Q1.json", "B_Q23": "configs/B_Q23_S0.json",
    "B_Q4": "configs/B_Q4_S0.json", "C1_Q23": "configs/C1_Q23.json",
    "C1_Q4": "configs/C1_Q4.json",
}
# Each named source has a fixed role. Wall/step budgets and approved numerical
# settings remain in that source RunConfig; campaign-wide hardware is explicit.
SOURCE_ROLES = {
    "smoke": ("B", 1, 20, 1, "fixed", "C0", 60, "SMOKE", False),
    "B_Q1": ("B", 1, 20, 1, "fixed", "C0", 1800, "PRODUCTION", True),
    "B_Q1_nr40": ("B", 1, 40, 1, "fixed", "C0", 1800, "PRODUCTION", True),
    "B_Q1_nr80": ("B", 1, 80, 1, "fixed", "C0", 1800, "PRODUCTION", True),
    "B_Q23_S0": ("B", 23, 20, 1, "fixed", "C0", 259200, "PRODUCTION", True),
    "B_Q4_S0": ("B", 4, 20, 1, "moving", "C0", 259200, "PRODUCTION", True),
    "C0_fixed_short": ("C", 23, 8, 8, "fixed", "C0", 60, "FRAMEWORK_INTEGRATION", False),
    "C0_moving_short": ("C", 4, 8, 8, "moving", "C0", 60, "FRAMEWORK_INTEGRATION", False),
    "C1_short": ("C", 23, 8, 8, "fixed", "C1", 60, "FRAMEWORK_INTEGRATION", False),
    "C1_Q23": ("C", 23, 20, 20, "fixed", "C1", 259200, "PRODUCTION", True),
    "C1_Q4": ("C", 4, 20, 20, "moving", "C1", 259200, "PRODUCTION", True),
}
SECONDS_FIELDS = {
    "session_wall_seconds", "tests_timeout_seconds", "postprocess_wall_seconds",
    "event_wall_seconds",
}
COUNT_FIELDS = {
    "max_run_attempts", "event_max_levels", "report_rounds",
    "comparison_max_points", "comparison_time_levels",
}


class CampaignPlanError(ValueError):
    """Malformed, unsafe or unsupported campaign definition."""


def _json_hash(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def validate_campaign_spec(value):
    """Validate a JSON-compatible specification without touching source files."""
    keys = {"kind", "name", "version", "budget", "hardware", "base_configs"}
    if not isinstance(value, dict) or set(value) != keys:
        raise CampaignPlanError("CAMPAIGN_SPEC_INVALID: unexpected or missing top-level fields")
    if value["kind"] != "CAMPAIGN_PLAN" or value["version"] != VERSION:
        raise CampaignPlanError("CAMPAIGN_VERSION_UNSUPPORTED")
    if not isinstance(value["name"], str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value["name"]) is None:
        raise CampaignPlanError("CAMPAIGN_NAME_INVALID: use a portable name of at most 80 characters")
    budget = value["budget"]
    if not isinstance(budget, dict) or set(budget) != SECONDS_FIELDS | COUNT_FIELDS:
        raise CampaignPlanError("CAMPAIGN_BUDGET_INVALID: all finite budget fields are required")
    for key in SECONDS_FIELDS:
        number = budget[key]
        if (isinstance(number, bool) or not isinstance(number, (int, float)) or
                not math.isfinite(number) or number <= 0):
            raise CampaignPlanError("CAMPAIGN_BUDGET_INVALID: " + key + " must be positive finite seconds")
    for key in COUNT_FIELDS:
        number = budget[key]
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise CampaignPlanError("CAMPAIGN_BUDGET_INVALID: " + key + " must be a positive integer")
    if budget["event_max_levels"] < 3 or budget["comparison_time_levels"] < 2 or budget["comparison_max_points"] < 3:
        raise CampaignPlanError("CAMPAIGN_BUDGET_INVALID: too few event/comparison levels or points")
    hardware = value["hardware"]
    if (not isinstance(hardware, dict) or
            set(hardware) != {"linear_backend", "cuda_device", "gpu_memory_mb", "memory_mb"} or
            hardware["linear_backend"] != "CUDA"):
        raise CampaignPlanError("CAMPAIGN_HARDWARE_INVALID: explicit CUDA device and budgets required")
    for key in ("cuda_device", "gpu_memory_mb", "memory_mb"):
        number = hardware[key]
        minimum = 0 if key == "cuda_device" else 1
        if isinstance(number, bool) or not isinstance(number, int) or number < minimum:
            raise CampaignPlanError("CAMPAIGN_HARDWARE_INVALID: " + key)
    sources = value["base_configs"]
    if (not isinstance(sources, list) or not all(isinstance(path, str) for path in sources) or
            len(sources) != len(BASE_CONFIGS) or set(sources) != set(BASE_CONFIGS)):
        raise CampaignPlanError("CAMPAIGN_SOURCES_INVALID: require each of the 11 approved source configs exactly once")
    # Round-trip to prevent caller mutation from changing a previously checked
    # specification. Source order is meaningful for the first wave of jobs.
    return json.loads(json.dumps(value, allow_nan=False))


def load_campaign_spec(path):
    """Read and validate server_full.json; do not expand or execute its jobs."""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise CampaignPlanError("CAMPAIGN_SPEC_UNREADABLE: " + str(exc)) from exc
    return validate_campaign_spec(value)


def _source_path(root, relative):
    path, windows = Path(relative), PureWindowsPath(relative)
    if path.is_absolute() or windows.is_absolute() or ".." in path.parts or ".." in windows.parts:
        raise CampaignPlanError("CAMPAIGN_SOURCE_PATH_INVALID: " + relative)
    resolved = (root / path).resolve()
    if (root not in resolved.parents or (root / "configs").resolve() not in resolved.parents or
            not resolved.is_file()):
        raise CampaignPlanError("CAMPAIGN_SOURCE_PATH_INVALID: " + relative)
    return resolved


def _validate_source(relative, cfg):
    expected = SOURCE_ROLES[Path(relative).stem]
    actual = (cfg.route, cfg.question, cfg.nr, cfg.nz, cfg.geometry, cfg.end_condition,
              cfg.tmax, cfg.execution_purpose, cfg.production_eligible)
    if actual != expected:
        raise CampaignPlanError("CAMPAIGN_SOURCE_ROLE_MISMATCH: " + relative)
    if (cfg.scenario != "S0" or cfg.window_start_h != 3.0 or cfg.radius_method != "linear" or
            cfg.radius_tail != "NONE" or cfg.case_end_time is not None or cfg.test_case is not None):
        raise CampaignPlanError("CAMPAIGN_SOURCE_PHYSICS_MISMATCH: " + relative)
    if cfg.linear_backend != "CUDA":
        raise CampaignPlanError("CAMPAIGN_SOURCE_REQUIRES_CUDA: " + relative)


def _refinement_configs(cfg):
    """Exact pure planning mirror of refinement.plan_refinement_configs.

    Importing refinement would import numerical code. The server-side planning
    tests compare these dictionaries against that existing authority function.
    No equation, factor, tolerance or event method is redefined here.
    """
    fine = replace(cfg, nr=cfg.nr * 4, nz=cfg.nz * 4 if cfg.route == "C" else 1)
    result = {
        "radial": [replace(cfg, nr=cfg.nr * 2**i) for i in range(3)],
        "time": [replace(fine, rtol=cfg.rtol / 10**i, atol_t=cfg.atol_t / 10**i,
                         atol_c=cfg.atol_c / 10**i) for i in range(3)],
        "newton": [replace(fine, newton_tol=cfg.newton_tol / 10**i,
                           linear_tol=cfg.linear_tol / 10**i) for i in range(3)],
        "dense": [replace(fine, hmax=cfg.hmax / 2**i,
                          h0=min(cfg.h0, cfg.hmax / 2**i)) for i in range(3)],
    }
    if cfg.route == "C":
        result["axial"] = [replace(cfg, nz=cfg.nz * 2**i) for i in range(3)]
        result["joint"] = [replace(cfg, nr=cfg.nr * 2**i, nz=cfg.nz * 2**i) for i in range(3)]
    return result


def expand_campaign(spec_or_path, root=None):
    """Return serializable configs, deduplicated runs and analysis mappings.

    ``root`` is the portable project root, not an output directory. No files
    are created. Event levels describe future accepted-checkpoint reintegration
    and never masquerade as independently executed full-horizon RunConfigs.
    """
    spec = (validate_campaign_spec(spec_or_path) if isinstance(spec_or_path, dict)
            else load_campaign_spec(spec_or_path))
    root = Path(ROOT if root is None else root).resolve()
    runs, by_fingerprint, by_key = [], {}, {}
    sources, configs, base_runs = [], {}, {}

    def add(cfg, role, source):
        fingerprint = cfg.fingerprint
        if fingerprint not in by_fingerprint:
            key = f"R_{cfg.route}_Q{cfg.question}_{fingerprint[:16]}"
            if key in by_key:
                raise CampaignPlanError("CAMPAIGN_RUN_KEY_COLLISION")
            record = {"run_key": key, "config_fingerprint": fingerprint, "config": cfg.as_dict(),
                      "roles": [], "source_configs": []}
            runs.append(record); by_fingerprint[fingerprint] = record; by_key[key] = record
        record = by_fingerprint[fingerprint]
        if role not in record["roles"]:
            record["roles"].append(role)
        if source not in record["source_configs"]:
            record["source_configs"].append(source)
        return record["run_key"]

    for relative in spec["base_configs"]:
        path = _source_path(root, relative)
        # Hash the same byte snapshot that is parsed, avoiding split provenance
        # if a source file is modified concurrently with planning.
        content = path.read_bytes()
        try:
            original = RunConfig.from_dict(json.loads(content.decode("utf-8-sig")))
            _validate_source(relative, original)
            cfg = replace(original, **spec["hardware"])
        except (ValueError, TypeError) as exc:
            raise CampaignPlanError("CAMPAIGN_SOURCE_INVALID: " + relative + ": " + str(exc)) from exc
        key = add(cfg, "base:" + Path(relative).stem, relative)
        configs[relative] = cfg
        base_runs[Path(relative).stem] = key
        sources.append({"path": relative, "file_sha256": sha256(content).hexdigest(),
                        "source_config_fingerprint": original.fingerprint,
                        "config_fingerprint": cfg.fingerprint, "run_key": key})

    comparisons = []
    # C0 fixed is the existing question=23 short test, so its B comparator must
    # also be Q23. A Q1/smoke trajectory is not an interchangeable reference.
    for stem in ("C0_fixed_short", "C0_moving_short"):
        relative = "configs/" + stem + ".json"
        cfg = replace(configs[relative], route="B", nz=1)
        key = add(cfg, "matched:" + stem, relative)
        comparisons.append({"comparison_id": stem, "kind": "C0_DEGENERATION",
                            "left": key, "right": base_runs[stem], "question": cfg.question,
                            "geometry": cfg.geometry, "coverage_end": cfg.tmax,
                            "expected_difference_fields": ["route", "nz"],
                            "evidence_scope": "DEVELOPMENT_SHORT_TEST_NOT_FULL_STRUCTURAL_VALIDATION"})

    cases = {}
    for case, relative in CASE_SOURCES.items():
        cfg = configs[relative]
        levels = _refinement_configs(cfg)
        categories = {category: [add(level, f"refinement:{case}:{category}:{i}", relative)
                                 for i, level in enumerate(values)]
                      for category, values in levels.items()}
        reference = categories["time"][0]
        cases[case] = {
            "case": case, "question": cfg.question, "route": cfg.route,
            "geometry": cfg.geometry, "source_config": relative,
            "base_run": base_runs[Path(relative).stem], "reference_run": reference,
            "categories": categories, "coverage_end": cfg.tmax,
            "event_levels": ([] if cfg.question == 1 else [
                {"width": .01 / 2**i, "method": "ACCEPTED_CHECKPOINT_REINTEGRATION"}
                for i in range(3)]),
            "requires_event": cfg.question != 1,
            "reference_policy": "FINEST_SPATIAL_GRID_WITH_BASE_TOLERANCES",
            "validation_status": "NOT_RUN",
        }

    sensitivities = []
    for case in ("B_Q23", "B_Q4"):
        relative = CASE_SOURCES[case]
        cfg = configs[relative]
        variants = [("environment_S1", {"scenario": "S1"}),
                    ("window_2p5h", {"window_start_h": 2.5}),
                    ("window_3p5h", {"window_start_h": 3.5})]
        if case == "B_Q4":
            variants += [("radius_pchip", {"radius_method": "pchip"}),
                         ("geometry_fixed", {"geometry": "fixed"})]
        for factor, changes in variants:
            variant = replace(cfg, **changes)
            key = add(variant, "sensitivity:" + case + ":" + factor, relative)
            entry = {"sensitivity_id": case + "_" + factor, "case": case, "factor": factor,
                     "base_run": cases[case]["base_run"], "variant_run": key, "changes": changes,
                     "scope": "FINITE_OAT_BASE_GRID_NOT_AN_ERROR_CERTIFICATE",
                     "requires_controlled_numerical_error_for_interpretation": True}
            sensitivities.append(entry)
            comparisons.append({"comparison_id": entry["sensitivity_id"], "kind": "SENSITIVITY",
                                "left": entry["base_run"], "right": key, "case": case,
                                "factor": factor, "changes": changes, "coverage_end": cfg.tmax})

    for question in (23, 4):
        left, right = "B_Q" + str(question), "C1_Q" + str(question)
        for level, field in (("base", "base_run"), ("reference", "reference_run")):
            comparisons.append({"comparison_id": f"BC_Q{question}_{level}", "kind": "BC_STRUCTURE",
                                "left": cases[left][field], "right": cases[right][field],
                                "left_case": left, "right_case": right, "level": level,
                                "question": question, "coverage_end": cases[left]["coverage_end"],
                                "requires_separate_numerical_error_control": True})

    result = {
        "kind": "EXPANDED_CAMPAIGN_PLAN", "name": spec["name"], "version": VERSION,
        "model_version": "A26-04-v2", "input_version": "A26-INPUT-v1",
        "budget": spec["budget"], "hardware": spec["hardware"],
        "spec_fingerprint": _json_hash(spec), "source_configs": sources,
        "runs": runs, "run_count": len(runs), "base_runs": base_runs,
        "cases": cases, "sensitivities": sensitivities, "comparisons": comparisons,
        "budget_semantics": {
            "session_wall_seconds": "PER_FULL_RUN_INVOCATION_NOT_AN_UNLIMITED_RESUME_ALLOWANCE",
            "max_run_attempts": "PER_UNIQUE_RUN_PER_INVOCATION",
            "per_run_wall_seconds": "UNCHANGED_FROM_SOURCE_RUNCONFIG",
            "completion": "FINITE_BUDGET_CAN_LEAVE_PARTIAL_OR_UNRESOLVED_RESULTS",
        },
        "event_planning": "ANALYSIS_REINTEGRATES_ACCEPTED_CHECKPOINTS_NO_SYNTHETIC_EVENT_RUNS",
        "radius_tail_policy": "NONE_NO_AUTOMATIC_EXTENSION_AFTER_72_HOURS",
        "execution_status": "PLANNED_NOT_EXECUTED", "stage07": "NOT_RUN", "stage08": "NOT_RUN",
    }
    result["plan_fingerprint"] = _json_hash(result)
    return result
