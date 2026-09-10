"""Bounded server postprocessing of completed campaign runs (never Stage07).

``analyze_case(context)`` accepts absolute ``reference_run`` / ``category_runs``
paths, ``case_id``, optional ``data_dir`` / ``reference_critical_time``,
``export_requested`` and a ``limits`` mapping. ``ensure_action(key, fn)`` owns
the journal/cache/deadline and calls ``fn(fresh_attempt_dir)`` exactly once for
an uncached attempt. Its return value is the callable's JSON-safe result.

Only the runner can resume/retry an action, using a new directory. This module
never overwrites a prior run: mutating legacy postprocessors receive an isolated
copy of metadata/checkpoints. Immutable trajectory NPZ chunks may be hardlinked.
Mocked orchestration tests are not numerical or CUDA validation evidence.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import sys

from .events import scan_events, upward_report_time
from .execution import inspect_run
from .export import export_workbooks
from .refinement import (HARD_FAILURES, METRICS, REFERENCE_FIELDS, RefinementError,
    _core_hashes, _load_run, _require_cuda_evidence, _validate_category,
    build_error_evidence, certify_strict_report, compare_runs,
    extend_refinement_run, prepare_strict_report, recompute_balances, refine_event)
from .trajectory import atomic_json, fingerprint


DEFAULT_LIMITS = {
    "comparison_wall_seconds": 300., "comparison_max_points": 200000,
    "comparison_time_levels": 6, "event_wall_seconds": 300.,
    "event_max_levels": 8, "report_wall_seconds": 900.,
    "closure_rounds": 3, "balances_wall_seconds": 300.,
}
EVENT_WIDTHS = (.01, .005, .0025)


class CampaignAnalysisError(ValueError):
    pass


def _limits(values):
    result = dict(DEFAULT_LIMITS)
    if set(values) - set(result):
        raise CampaignAnalysisError("ANALYSIS_CONFIG_INVALID: unknown limit")
    result.update(values)
    integer = {"comparison_max_points", "comparison_time_levels", "event_max_levels", "closure_rounds"}
    for key, value in result.items():
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or
                not math.isfinite(value) or value <= 0 or
                (key in integer and not isinstance(value, int))):
            raise CampaignAnalysisError("ANALYSIS_CONFIG_INVALID: positive finite " + key + " required")
    return result


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _write_new(path, result):
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    atomic_json(path, result)
    return result


def _clone_run(source, destination):
    """Separate every mutable file; share only immutable indexed NPZ chunks."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination == source or source in destination.parents:
        raise CampaignAnalysisError("ANALYSIS_PATH_INVALID: clone must be outside source run")
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    for name in ("config.json", "manifest.json", "metrics.json", "environment.json",
                 "diagnostics.json", "event.json", "checkpoint.json", "phase_diagnostics.json"):
        path = source / name
        if path.exists():
            shutil.copy2(path, destination / name)
    for name in ("checkpoints", "source_snapshot"):
        if (source / name).exists():
            shutil.copytree(source / name, destination / name)
    trajectory = source / "trajectory"
    index = _json(trajectory / "index.json")
    (destination / "trajectory").mkdir()
    shutil.copy2(trajectory / "index.json", destination / "trajectory" / "index.json")
    for entry in index["chunks"]:
        name = entry["file"]
        if Path(name).name != name or not name.endswith(".npz"):
            raise CampaignAnalysisError("TRAJECTORY_INVALID: unexpected immutable chunk path")
        src, dst = trajectory / name, destination / "trajectory" / name
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)
    _write_new(destination / "analysis_lineage.json", {
        "source_run": str(source), "source_identity": _json(source / "manifest.json")["identity"],
        "source_trajectory_fingerprint": fingerprint(index),
        "mutable_metadata": "INDEPENDENT_COPIES", "trajectory_chunks": "IMMUTABLE_LINK_OR_COPY",
        "stage07": "NOT_RUN"})
    return destination


def _comparison_options(limits):
    return {"wall_seconds": limits["comparison_wall_seconds"],
            "max_time_points": limits["comparison_max_points"],
            "max_time_refinements": limits["comparison_time_levels"]}


def _strict_margin(evidence):
    values = [evidence.get(name) for name in ("eC", "eG")]
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or
           not math.isfinite(x) or x < 0 for x in values):
        raise CampaignAnalysisError("ERROR_BUDGET_UNRESOLVED: measured moisture error missing")
    return max(2 * max(values), 64 * sys.float_info.epsilon)


def _q1_field_evidence(reference_run, category_runs, *, data_dir=None, comparison_options=None):
    """Q1 has no critical drying event; measure every applicable field category."""
    ref, cfg, manifest, _, trajectory = _load_run(reference_run, data_dir)
    if cfg.question != 1 or cfg.test_case is not None or trajectory.start_time != 0 or trajectory.end_time < 1800:
        raise CampaignAnalysisError("Q1_COVERAGE_UNRESOLVED: formal 0..1800 s trajectory required")
    _require_cuda_evidence(cfg, manifest)
    required = {"radial", "time", "newton", "dense"}
    if cfg.route == "C":
        required |= {"axial", "joint"}
    result = {"status": "ERROR_BUDGET_UNRESOLVED", "checks_passed": False,
        "reference_run": str(ref), "source_identity": manifest["identity"],
        "config_fingerprint": cfg.fingerprint, "trajectory_fingerprint": fingerprint(trajectory.index),
        "coverage_start": 0., "coverage_end": 1800., "categories": {}, "issues": [],
        "category_runs": {k: list(map(str, v)) for k, v in category_runs.items()},
        "eT": None, "eC": None, "eG": None, "event_error": "NOT_APPLICABLE_Q1",
        "empirical_not_bound": True, "four_decimal_accuracy_claimed": False,
        "scope": "STAGE06_Q1_NUMERICAL_ACCEPTANCE_ONLY", "stage07": "NOT_RUN"}
    for category in sorted(required):
        try:
            paths = category_runs.get(category, [])
            if len(paths) < 3:
                raise RefinementError("at least three actual levels required")
            actual = [_load_run(p, data_dir) for p in paths]
            configs, manifests = [a[1] for a in actual], [a[2] for a in actual]
            _validate_category(category, configs, manifests)
            for _, c, m, _, tr in actual:
                _require_cuda_evidence(c, m)
                if (c.test_case is not None or any(getattr(c, k) != getattr(cfg, k) for k in REFERENCE_FIELDS) or
                        m["identity"]["input"] != manifest["identity"]["input"] or
                        _core_hashes(m) != _core_hashes(manifest) or tr.start_time != 0 or tr.end_time < 1800):
                    raise RefinementError("physical/backend/source/coverage mismatch")
                if category in {"time", "newton", "dense"} and (c.nr, c.nz) != (cfg.nr, cfg.nz):
                    raise RefinementError("nonspatial category must use reference grid")
            if category in {"radial", "joint"} and configs[-1].nr != cfg.nr:
                raise RefinementError("finest radial level differs from reference")
            if category in {"axial", "joint"} and configs[-1].nz != cfg.nz:
                raise RefinementError("finest axial level differs from reference")
            comparisons = [compare_runs(a, b, coverage_end=1800., data_dir=data_dir,
                **(comparison_options or {})) for a, b in zip(paths[:-1], paths[1:])]
            if any(not c.get("resolved") for c in comparisons):
                raise RefinementError("adjacent reconstructed-field comparison unresolved")
            last = comparisons[-2:]
            estimates, descending = {}, True
            for metric, scale in zip(METRICS, (324., 2.55, 2.55)):
                d1, d2 = (float(c["differences"][metric]) for c in last)
                if any(not math.isfinite(v) or v < 0 for v in (d1, d2)):
                    raise RefinementError("nonfinite or negative measured difference")
                descending &= d2 < d1 or max(d1, d2) <= 64 * sys.float_info.epsilon * scale
                estimates["e" + metric] = 2 * max(d1, d2)
            if category in {"radial", "axial", "joint"} and not descending:
                raise RefinementError("SPATIAL_CONVERGENCE_UNRESOLVED: last differences do not decrease")
            entry = {"status": "MEASURED", "levels": len(paths), "comparisons": comparisons,
                     "estimates": estimates, "last_differences_descend": bool(descending)}
            if category == "dense":
                entry["hmax_active"] = [_json(Path(p)/"metrics.json").get("stats", {}).get("max_h", 0.) >= .999999*c.hmax
                                        for p, c in zip(paths, configs)]
            result["categories"][category] = entry
        except (ValueError, FileNotFoundError, KeyError, TypeError) as exc:
            result["issues"].append(category + ": " + str(exc))
    if required.issubset(result["categories"]):
        for name in ("eT", "eC", "eG"):
            result[name] = sum(c["estimates"][name] for c in result["categories"].values())
        if result["eT"] > .05 or max(result["eC"], result["eG"]) > .0005:
            result["issues"].append("prescribed cumulative field budget exceeded, including initial layer")
        result["checks_passed"] = not result["issues"]
        if result["checks_passed"]:
            result["status"] = "Q1_FIELD_ERROR_EVIDENCE_READY"
    result["evidence_fingerprint"] = fingerprint(result)
    return result


def _action(context, key, function):
    result = context["ensure_action"](key, function)
    if not isinstance(result, dict):
        raise CampaignAnalysisError("ACTION_PROTOCOL_INVALID: JSON object result required")
    return result


def _balances_action(run_dir, work, data_dir, limits):
    final = _clone_run(run_dir, Path(work)/"run")
    diagnostics = recompute_balances(final, data_dir=data_dir,
                                    wall_seconds=limits["balances_wall_seconds"])
    return {"status": diagnostics["status"], "checks_passed": diagnostics["checks_passed"],
            "run_dir": str(final), "diagnostics": diagnostics,
            "diagnostics_path": str(final/"diagnostics.json")}


def _export_action(run_dir, work, data_dir, question, certificate=None, q1_accepted=False):
    system, trajectory, config = inspect_run(run_dir, data_dir)
    if config.route != "B":
        raise CampaignAnalysisError("REFERENCE_ONLY: C does not export formal question workbooks")
    result = export_workbooks(system, trajectory, Path(work)/"workbooks", question,
                              event_record=certificate, developer_approved=q1_accepted)
    return dict(result, status="CANDIDATE_EXPORTED", stage07="NOT_RUN")


def _event_action(source, work, width, data_dir, limits):
    staged = _clone_run(source, Path(work)/"source")
    return refine_event(staged, Path(work)/"refined", width=width,
        max_levels=limits["event_max_levels"], data_dir=data_dir,
        wall_seconds=limits["event_wall_seconds"])


def _prepare_action(source, evidence, work, data_dir, limits):
    staged = _clone_run(source, Path(work)/"source")
    return prepare_strict_report(staged, evidence, Path(work)/"prepared", width=EVENT_WIDTHS[-1],
        data_dir=data_dir, wall_seconds=limits["report_wall_seconds"])


def _coverage_request(system, trajectory, evidence, limit):
    """Choose finite coverage from the measured margin on the full source.

    The scanned endpoint is a planning observation, not a certified report.
    Actual threshold reintegration and final evidence checks still follow.
    """
    eta = _strict_margin(evidence)
    event = scan_events(system, trajectory, threshold=.15-eta)
    result = {"status": "REPORT_TIME_UNRESOLVED", "eta_strict": eta,
              "threshold_event": event, "coverage_limit": limit,
              "source_coverage_end": trajectory.end_time, "stage07": "NOT_RUN"}
    if (event.get("status") != "PROVISIONAL_EVENT" or not event.get("earliest_verified") or
            not event.get("retention_verified")):
        result["issues"] = ["measured strict margin has no resolved event on the complete source"]
        return result
    # A coarse accepted right endpoint may exceed the allowed waiting range
    # even when its interpolated crossing lies inside it. Cover only up to the
    # finite limit in that case; actual local reintegration decides feasibility.
    target = min(upward_report_time(event["tR"]), limit)
    if target <= event["t_hat"]:
        result["issues"] = ["strict-margin event lies beyond the finite permitted coverage"]
        return result
    result.update(status="COVERAGE_REQUEST_READY", coverage_end=target)
    return result


def _cover_event_and_current(context, key, event_paths, current, end, data_dir, limits):
    """Extend only paths lacking the actual requested coverage, with new IDs."""
    paths, records = [], []
    previous_finest = event_paths[-1]
    for i, path in enumerate(event_paths):
        _, _, _, _, trajectory = _load_run(path, data_dir)
        if trajectory.end_time < end:
            extension = _action(context, key+f"event_{i}_coverage", lambda work, path=path:
                extend_refinement_run(path, Path(work)/"run", end, data_dir=data_dir,
                                      wall_seconds=limits["event_wall_seconds"]))
            records.append(extension)
            if extension.get("status") != "COMPLETED_INTERVAL":
                return {"status": extension.get("status", "COVERAGE_UNRESOLVED"), "extensions": records}
            path = extension["run_dir"]
        paths.append(path)
    if current == previous_finest:
        current = paths[-1]
    else:
        _, _, _, _, trajectory = _load_run(current, data_dir)
        if trajectory.end_time < end:
            extension = _action(context, key+"current_coverage", lambda work:
                extend_refinement_run(current, Path(work)/"run", end, data_dir=data_dir,
                                      wall_seconds=limits["event_wall_seconds"]))
            records.append(extension)
            if extension.get("status") != "COMPLETED_INTERVAL":
                return {"status": extension.get("status", "COVERAGE_UNRESOLVED"), "extensions": records}
            current = extension["run_dir"]
    return {"status": "COVERAGE_READY", "event_paths": paths, "current": current,
            "changed": bool(records), "extensions": records, "coverage_end": end}


def _stop(result, status, issue=None):
    result["status"] = status
    result["exit_code"] = 1 if status in HARD_FAILURES or status == "ANALYSIS_FAILED" else 2
    if issue:
        result["issues"].append(issue)
    return result


def analyze_case(context):
    """Execute only a case's finite analysis chain via the parent's journal.

    The runner must invalidate cached actions if source/config/trajectory/input
    hashes change. A C certificate is numerical reference evidence only. Missing
    C reference time leaves the separate structural comparison explicitly open.
    """
    result = {"case_id": context.get("case_id"), "status": "ANALYSIS_UNRESOLVED",
              "exit_code": 2, "stage07": "NOT_RUN", "issues": []}
    try:
        limits = _limits(context.get("limits", {}))
        source = str(Path(context["reference_run"]).resolve())
        data_dir = context.get("data_dir")
        categories = {k: [str(Path(p).resolve()) for p in paths]
                      for k, paths in context["category_runs"].items() if k != "event"}
        _, cfg, manifest, system, trajectory = _load_run(source, data_dir)
        if cfg.test_case is not None or manifest.get("refinement"):
            raise CampaignAnalysisError("ANALYSIS_INPUT_INVALID: unmodified formal global run required")
        _require_cuda_evidence(cfg, manifest)
        result.update(question=cfg.question, route=cfg.route, reference_run=source, final_run=source,
                      source_identity=manifest["identity"],
                      common_reference_checked=False, structural_validation="NOT_RUN")
        prefix = str(context["case_id"]) + "/analysis/"
        options = _comparison_options(limits)
        export_requested = bool(context.get("export_requested", cfg.route == "B")) and cfg.route == "B"
        if cfg.question == 1:
            evidence = _action(context, prefix+"q1_fields", lambda work: _write_new(
                Path(work)/"q1_error_evidence.json", _q1_field_evidence(source, categories,
                    data_dir=data_dir, comparison_options=options)))
            result["error_evidence"] = evidence
            if not evidence.get("checks_passed"):
                return _stop(result, evidence.get("status", "ERROR_BUDGET_UNRESOLVED"))
            balances = _action(context, prefix+"q1_balances", lambda work:
                _balances_action(source, work, data_dir, limits))
            result.update(balances=balances, final_run=balances.get("run_dir", source))
            if not balances.get("checks_passed"):
                return _stop(result, balances.get("status", "DIAGNOSTICS_UNRESOLVED"))
            result["development_acceptance"] = {
                "status": "Q1_NUMERICAL_CHECKS_PASSED", "field_evidence_fingerprint": evidence["evidence_fingerprint"],
                "diagnostics_path": balances["diagnostics_path"], "coverage_end": 1800.,
                "scope": "STAGE06_NUMERICAL_CHECKS_NOT_STAGE07", "four_decimal_accuracy_claimed": False}
            if export_requested:
                result["export"] = _action(context, prefix+"q1_export", lambda work:
                    _export_action(result["final_run"], work, data_dir, 1, q1_accepted=True))
                if result["export"].get("status") != "CANDIDATE_EXPORTED":
                    return _stop(result, result["export"].get("status", "OUTPUT_UNRESOLVED"))
            result.update(status="Q1_CANDIDATE_EXPORTED" if export_requested else "Q1_NUMERICS_READY", exit_code=0)
            return result

        nominal = scan_events(system, trajectory)
        result["nominal_event"] = nominal
        if (nominal.get("status") != "PROVISIONAL_EVENT" or
                not nominal.get("earliest_verified") or not nominal.get("retention_verified")):
            return _stop(result, "NO_EVENT" if nominal.get("status") == "NO_EVENT" else "EVENT_UNRESOLVED")
        # The maximum permissible window is a cap, not an instruction to solve
        # the full maximum waiting interval at the event's smallest time step.
        budget = .1 * min(.01 * nominal["t_hat"], 1800.)
        coverage_limit = min(trajectory.end_time, cfg.tmax, nominal["tR"] + budget + .36 + .01)
        for paths in categories.values():
            for path in paths:
                _, _, _, _, tr = _load_run(path, data_dir)
                coverage_limit = min(coverage_limit, tr.end_time)
        if coverage_limit <= nominal["t_hat"]:
            return _stop(result, "COVERAGE_UNRESOLVED", "global refinement trajectories do not cover candidate waiting window")
        result["analysis_coverage_limit"] = coverage_limit
        event_paths = []
        for i, width in enumerate(EVENT_WIDTHS):
            refined = _action(context, prefix+f"event_{i}", lambda work, width=width:
                _event_action(source, work, width, data_dir, limits))
            result.setdefault("event_levels", []).append(refined)
            if refined.get("status") != "EVENT_BRACKET_REFINED":
                return _stop(result, refined.get("status", "EVENT_UNRESOLVED"))
            event_paths.append(refined["run_dir"])
        latest_right = max(item["event"]["tR"] for item in result["event_levels"])
        end = min(coverage_limit, latest_right + .36 + .01)
        if end <= latest_right:
            return _stop(result, "COVERAGE_UNRESOLVED", "refined event lacks legal initial comparison coverage")
        current = event_paths[-1]
        covered = _cover_event_and_current(context, prefix+"initial/", event_paths, current, end, data_dir, limits)
        result["coverage_extensions"] = [covered]
        if covered["status"] != "COVERAGE_READY":
            return _stop(result, covered["status"])
        event_paths, current = covered["event_paths"], covered["current"]
        categories["event"] = event_paths
        result.update(analysis_coverage_end=end, final_run=current)
        evidence = _action(context, prefix+"initial_error_evidence", lambda work:
            build_error_evidence(current, categories, Path(work)/"error_evidence.json",
                coverage_end=end, data_dir=data_dir, comparison_options=options))
        result["error_evidence"] = evidence
        if not evidence.get("checks_passed"):
            return _stop(result, evidence.get("status", "ERROR_BUDGET_UNRESOLVED"))
        for iteration in range(limits["closure_rounds"]):
            key = prefix+f"closure_{iteration}/"
            request = _action(context, key+"coverage_request", lambda work: _write_new(
                Path(work)/"coverage_request.json", _coverage_request(system, trajectory, evidence, coverage_limit)))
            result.setdefault("coverage_requests", []).append(request)
            if request.get("status") != "COVERAGE_REQUEST_READY":
                return _stop(result, request.get("status", "REPORT_TIME_UNRESOLVED"))
            requested_end = max(end, request["coverage_end"])
            covered = _cover_event_and_current(context, key, event_paths, current, requested_end, data_dir, limits)
            result["coverage_extensions"].append(covered)
            if covered["status"] != "COVERAGE_READY":
                return _stop(result, covered["status"])
            event_paths, current = covered["event_paths"], covered["current"]
            categories["event"] = event_paths
            if (covered["changed"] or requested_end > end or
                    evidence.get("coverage_end", -1) < requested_end):
                end = requested_end
                evidence = _action(context, key+"coverage_error_evidence", lambda work:
                    build_error_evidence(current, categories, Path(work)/"error_evidence.json",
                        coverage_end=end, data_dir=data_dir, comparison_options=options))
                result.update(error_evidence=evidence, analysis_coverage_end=end, final_run=current)
                if not evidence.get("checks_passed"):
                    return _stop(result, evidence.get("status", "ERROR_BUDGET_UNRESOLVED"))
                # A changed error estimate requires a new measured-threshold
                # coverage request, not preparation with the previous margin.
                if _strict_margin(evidence) != request["eta_strict"]:
                    result.setdefault("closure_updates", []).append({"round": iteration,
                        "reason": "coverage extension changed measured strict margin",
                        "previous_margin": request["eta_strict"], "refreshed_margin": _strict_margin(evidence)})
                    continue
            candidate = _action(context, key+"prepare", lambda work:
                _prepare_action(current, evidence, work, data_dir, limits))
            result["candidate"] = candidate
            current = candidate.get("run_dir", current)
            result["final_run"] = current
            if candidate.get("status") != "PROVISIONAL_EVENT":
                return _stop(result, candidate.get("status", "REPORT_TIME_UNRESOLVED"))
            if candidate["t_report"] > coverage_limit:
                return _stop(result, "COVERAGE_UNRESOLVED", "prepared report exceeds finite permitted coverage")
            if candidate["t_report"] > end:
                end = candidate["t_report"]
                covered = _cover_event_and_current(context, key+"final/", event_paths, current, end, data_dir, limits)
                result["coverage_extensions"].append(covered)
                if covered["status"] != "COVERAGE_READY":
                    return _stop(result, covered["status"])
                event_paths, current = covered["event_paths"], covered["current"]
                categories["event"] = event_paths
                result.update(final_run=current, analysis_coverage_end=end)
            refreshed = _action(context, key+"refresh_error_evidence", lambda work:
                build_error_evidence(current, categories, Path(work)/"error_evidence.json",
                    coverage_end=candidate["t_report"], data_dir=data_dir, comparison_options=options))
            result["error_evidence"] = refreshed
            if not refreshed.get("checks_passed"):
                return _stop(result, refreshed.get("status", "ERROR_BUDGET_UNRESOLVED"))
            if _strict_margin(refreshed) != candidate.get("eta_strict"):
                result.setdefault("closure_updates", []).append({"round": iteration,
                    "previous_margin": candidate.get("eta_strict"), "refreshed_margin": _strict_margin(refreshed)})
                evidence = refreshed
                continue
            balances = _action(context, key+"balances", lambda work:
                _balances_action(current, work, data_dir, limits))
            result.update(balances=balances, final_run=balances.get("run_dir", current))
            if not balances.get("checks_passed"):
                return _stop(result, balances.get("status", "DIAGNOSTICS_UNRESOLVED"))
            final_run = result["final_run"]
            certificate = _action(context, key+"certify", lambda work:
                certify_strict_report(final_run, refreshed, candidate, Path(work)/"certificate.json",
                    data_dir=data_dir, reference_critical_time=context.get("reference_critical_time")))
            result["certificate"] = certificate
            if certificate.get("status") != "DRYING_COMPLETE":
                return _stop(result, certificate.get("status", "ERROR_BUDGET_UNRESOLVED"))
            result["common_reference_checked"] = certificate.get("common_reference_checked", False)
            if export_requested:
                result["export"] = _action(context, key+"export", lambda work:
                    _export_action(final_run, work, data_dir, cfg.question, certificate))
                if result["export"].get("status") != "CANDIDATE_EXPORTED":
                    return _stop(result, result["export"].get("status", "OUTPUT_UNRESOLVED"))
            result.update(status="REFERENCE_NUMERICS_READY" if cfg.route == "C" else "DRYING_COMPLETE", exit_code=0)
            return result
        return _stop(result, "ERROR_BUDGET_UNRESOLVED", "finite closure rounds exhausted; refreshed strict margin did not stabilize")
    except (ValueError, KeyError, TypeError, FileNotFoundError, OSError) as exc:
        return _stop(result, "ANALYSIS_FAILED", str(exc))
