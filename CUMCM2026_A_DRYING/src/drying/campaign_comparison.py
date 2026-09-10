"""Bounded raw campaign comparisons under A26-04-v2 section 16.1.

This is not refinement error evidence and makes no Stage 07 decision. Unlike
``refinement.compare_runs``, it permits B/C structure comparisons or explicit
same-route input/geometry sensitivity. All evaluations use recorded accepted
trajectories; no solver, reintegration, fitting, or extrapolation is performed.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import math
import time

import numpy as np

from .events import scan_events
from .reconstruction import reconstruct
from .refinement import _core_hashes, _load_run
from .trajectory import atomic_json, fingerprint


STABILITY_TOLERANCES = {"T": 1e-5, "C": 1e-8, "G": 1e-8}


class CampaignComparisonError(ValueError):
    """A comparison definition or its provenance is not resolved."""


class _BudgetReached(RuntimeError):
    pass


class _Budget:
    def __init__(self, wall_seconds, max_time_points):
        self.started = time.perf_counter()
        self.wall_seconds = wall_seconds
        self.max_time_points = max_time_points
        self.samples = 0

    def check(self):
        if time.perf_counter() - self.started >= self.wall_seconds:
            raise _BudgetReached("COMPARISON_WALL_BUDGET_REACHED")

    def admit_sample(self):
        self.check()
        if self.samples >= self.max_time_points:
            raise _BudgetReached("COMPARISON_POINT_BUDGET_REACHED")


class _EventTrajectory:
    """Expose complete legal history to the existing scanner with wall checks."""
    def __init__(self, trajectory, budget):
        self.trajectory, self.budget = trajectory, budget
        self.start_time = trajectory.start_time
        self.end_time = trajectory.end_time

    def iter_segments(self):
        for segment in self.trajectory.iter_segments():
            self.budget.check()
            yield segment


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _run_identity(run):
    path, config, manifest, _, trajectory = run
    return {"run_dir": str(path), "run_id": path.name,
            "config_fingerprint": config.fingerprint,
            "input_fingerprint": manifest["identity"]["input"],
            "source_fingerprint": manifest["identity"].get("code"),
            "numerical_source_files": _core_hashes(manifest),
            "numerical_source_fingerprint": fingerprint(_core_hashes(manifest)),
            "trajectory_fingerprint": fingerprint(trajectory.index),
            "trajectory_identity": trajectory.index["identity"],
            "manifest_sha256": _sha256(path / "manifest.json"),
            "route": config.route, "question": config.question,
            "geometry": config.geometry, "end_condition": config.end_condition,
            "execution": {name: getattr(config, name) for name in
                          ("execution_backend", "execution_purpose", "production_eligible")},
            "coverage": [float(trajectory.start_time), float(trajectory.end_time)]}


def _comparison_kind(left, right):
    _, a, ma, _, _ = left
    _, b, mb, _, _ = right
    if _core_hashes(ma) != _core_hashes(mb):
        raise CampaignComparisonError("PROVENANCE_UNRESOLVED: numerical sources differ")
    for key in ("question", "model_version", "input_version", "test_case"):
        if getattr(a, key) != getattr(b, key):
            raise CampaignComparisonError("COMPARISON_UNRESOLVED: unlike " + key)
    same_input = ma["identity"]["input"] == mb["identity"]["input"]
    if a.route != b.route:
        if {a.route, b.route} != {"B", "C"} or not same_input or a.geometry != b.geometry:
            raise CampaignComparisonError("COMPARISON_UNRESOLVED: B/C requires identical input and geometry")
        return "B_C_STRUCTURE"
    if a.end_condition != b.end_condition:
        raise CampaignComparisonError("COMPARISON_UNRESOLVED: same-route input sensitivity changes end condition")
    if a.geometry != b.geometry and a.question != 4:
        raise CampaignComparisonError("COMPARISON_UNRESOLVED: fixed/moving sensitivity requires question 4")
    return "SAME_ROUTE_INPUT_SENSITIVITY" if not same_input or a.geometry != b.geometry else "SAME_ROUTE_RAW_REFERENCE"


def _physical_query(rec, r):
    """Query a float-defined reconstruction at physical r, never beyond R."""
    if not math.isfinite(r) or r < 0 or r > rec.R:
        raise CampaignComparisonError("OUTSIDE_DOMAIN: campaign query outside current material")
    return np.asarray(rec._query_xi(1. if r == rec.R else r / rec.R, 0.), dtype=float)


def _quadratic_extreme(v0, vm, v1):
    """Exact candidate set for |a*u^2+b*u+c| on 0 <= u <= 1."""
    a = 2. * (v1 + v0 - 2. * vm)
    b = 4. * vm - 3. * v0 - v1
    candidates = [(abs(v0), 0.), (abs(v1), 1.)]
    if a != 0:
        stationary = -b / (2. * a)
        if 0. < stationary < 1.:
            candidates.append((abs((a * stationary + b) * stationary + v0), float(stationary)))
    return max(candidates, key=lambda value: value[0])


def midplane_difference(left, right, *, check_budget=None):
    """Radial suprema over the common *physical* domain, including stationary points.

    Each union interval lies in one linear/even-quadratic reconstruction patch
    of each run. Their difference is quadratic in actual r, even when radii
    and first-cell widths differ. G retains each run's own full spatial domain.
    """
    for rec in (left, right):
        if not math.isfinite(rec.R) or rec.R <= 0:
            raise CampaignComparisonError("RECONSTRUCTION_UNRESOLVED: invalid radius")
    common = min(left.R, right.R)
    points = np.unique(np.r_[0., common, left.R * left.xi, right.R * right.xi])
    points = points[(points >= 0.) & (points <= common)]
    maxima = np.zeros(2)
    locations = {"T": {"r_m": 0., "z_m": 0.}, "C": {"r_m": 0., "z_m": 0.}}
    for lo, hi in zip(points[:-1], points[1:]):
        if check_budget is not None:
            check_budget()
        sampled = [_physical_query(left, r) - _physical_query(right, r)
                   for r in (float(lo), float((lo + hi) / 2.), float(hi))]
        if np.any(~np.isfinite(sampled)):
            raise CampaignComparisonError("RECONSTRUCTION_UNRESOLVED: nonfinite field difference")
        for eq, key in enumerate(("T", "C")):
            value, position = _quadratic_extreme(*(float(v[eq]) for v in sampled))
            if value > maxima[eq]:
                maxima[eq] = value
                locations[key] = {"r_m": float(lo + position * (hi - lo)), "z_m": 0.}
    g = abs(float(left.max_C) - float(right.max_C))
    if not math.isfinite(g):
        raise CampaignComparisonError("RECONSTRUCTION_UNRESOLVED: nonfinite global maximum")
    locations["G"] = {
        label: {"r_m": float(rec.R * rec.max_position[0]),
                "xi": float(rec.max_position[0]), "z_m": float(rec.max_position[1])}
        for label, rec in (("left", left), ("right", right))}
    return {"T": float(maxima[0]), "C": float(maxima[1]), "G": g,
            "positions": locations, "common_radius_m": float(common),
            "radii_m": [float(left.R), float(right.R)]}


def axial_departure(rec):
    """Full C-route departure from its own midplane on O1/O2 node extrema.

    Subtracting the midplane preserves tensor convex interpolation on this
    run's own patches, so maximum absolute departure occurs at a full node.
    """
    if rec.system.grid.route != "C":
        return None
    delta = np.abs(rec.nodes - rec.nodes[:, :1, :])
    if np.any(~np.isfinite(delta)):
        raise CampaignComparisonError("RECONSTRUCTION_UNRESOLVED: nonfinite axial departure")
    values = {}
    for eq, key in enumerate(("T", "C")):
        pos = np.unravel_index(np.argmax(delta[..., eq]), delta.shape[:2])
        values[key] = {"value": float(delta[pos[0], pos[1], eq]),
                       "position": {"r_m": float(rec.R * rec.xi[pos[0]]),
                                    "xi": float(rec.xi[pos[0]]), "z_m": float(rec.z[pos[1]])}}
    return values


def _event_time(event):
    value = event.get("t_hat")
    if (event.get("status") == "PROVISIONAL_EVENT" and event.get("earliest_verified")
            and event.get("retention_verified") and value is not None
            and math.isfinite(value) and value >= 0):
        return float(value)
    return None


def _event_summary(events, configs):
    times = [_event_time(event) for event in events]
    has_both = all(value is not None for value in times)
    c_sides = [i for i, cfg in enumerate(configs) if cfg.route == "C"]
    reference = c_sides[-1] if c_sides else None
    difference = abs(times[0] - times[1]) if has_both else None
    denominator = times[reference] if has_both and reference is not None else None
    relative = difference / denominator if denominator is not None and denominator > 0 else None
    return {"absolute_seconds": difference, "relative_to_C": relative,
            "C_denominator_seconds": denominator,
            "C_reference_side": None if reference is None else ("left", "right")[reference],
            "status": "BOTH_EVENTS_MEASURED" if has_both else "EVENT_DIFFERENCE_UNDEFINED",
            "relative_status": "DEFINED" if relative is not None else "UNDEFINED_NO_POSITIVE_C_EVENT",
            "provisional_reconstruction_events_not_certification": True}


def _initial_result(left_run, right_run, budget, max_time_refinements):
    return {"schema_version": "1.0", "status": "COMPARISON_UNRESOLVED", "resolved": False,
            "evidence_scope": "MECHANICAL_RAW_DIFFERENCES_NO_STAGE07_DECISION",
            "run_dirs": [str(Path(left_run).resolve()), str(Path(right_run).resolve())],
            "run_identities": [], "comparison_kind": None, "config_differences": {},
            "differences": None, "C_axial_departure": {}, "maximum_locations": {},
            "events": [], "event_difference": None, "main_window": None,
            "time_coverage_complete": False, "time_stable": False,
            "samples": 0, "sampled_through_time": None, "time_refinement_maxima": [],
            "issues": [], "empirical_not_bound": True,
            "field_comparison": "MIDPLANE_COMMON_PHYSICAL_RADIUS_UNION_BREAKPOINTS_AND_STATIONARY_POINTS",
            "G_comparison": "EACH_RUN_FULL_CURRENT_DOMAIN_MAXIMUM",
            "time_comparison": "UNION_ACCEPTED_AND_INPUT_NODES_WITH_ONE_SIDED_LIMITS_PLUS_MIDPOINTS",
            "units": {"T": "K", "C": "kg_water/kg_dry_matter", "G": "kg_water/kg_dry_matter",
                      "time": "s", "position": "m", "relative_to_C": "dimensionless"},
            "stability_tolerances": dict(STABILITY_TOLERANCES),
            "budgets": {"wall_seconds": budget.wall_seconds, "max_time_points": budget.max_time_points,
                        "max_time_refinements": max_time_refinements},
            "comparison_source_sha256": _sha256(__file__),
            "comparison_source_files": {name: _sha256(Path(__file__).parent / name) for name in
                                        ("campaign_comparison.py", "events.py", "reconstruction.py",
                                         "refinement.py", "trajectory.py", "execution.py")}}


def compare_campaign_runs(left_run, right_run, out_path=None, wall_seconds=1200,
                          max_time_points=200000, max_time_refinements=6):
    """Return/save raw field, global-maximum, axial, and event differences.

    Sources are verified against their recorded input/core identities. B/C
    needs equal input and geometry. Same-route question-4 fixed/moving runs
    are supported through physical-r reconstruction, without extrapolation.
    Event differences are undefined unless both complete legal histories have
    usable events; a relative difference is reported only with a positive C
    reference (right C for C/C). B/B sensitivity retains absolute event change.

    Resource limits and malformed sources return unresolved JSON with partial
    evidence explicitly identified. Invalid API budgets raise ValueError.
    """
    if isinstance(wall_seconds, bool) or not isinstance(wall_seconds, (int, float)) or not math.isfinite(wall_seconds) or wall_seconds <= 0:
        raise ValueError("wall_seconds must be positive and finite")
    for key, value, minimum in (("max_time_points", max_time_points, 1),
                                ("max_time_refinements", max_time_refinements, 0)):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(key + " is outside its integer budget domain")
    budget = _Budget(float(wall_seconds), max_time_points)
    result = _initial_result(left_run, right_run, budget, max_time_refinements)
    maxima, locations, axial = {}, {}, {}
    try:
        budget.check()
        left = _load_run(left_run)
        budget.check()
        right = _load_run(right_run)
        budget.check()
        result["run_identities"] = [_run_identity(left), _run_identity(right)]
        result["comparison_kind"] = _comparison_kind(left, right)
        configs = [left[1], right[1]]
        values = [cfg.as_dict() for cfg in configs]
        result["config_differences"] = {key: [values[0][key], values[1][key]]
                                        for key in values[0] if values[0][key] != values[1][key]}
        systems, trajectories = [left[3], right[3]], [left[4], right[4]]
        for cfg, trajectory in zip(configs, trajectories):
            if (trajectory.start_time != 0 or not math.isfinite(trajectory.end_time)
                    or trajectory.end_time > cfg.tmax or trajectory.end_time < 0):
                raise CampaignComparisonError("COVERAGE_UNRESOLVED: need complete legal trajectory from zero")
            if cfg.geometry == "moving" and cfg.radius_tail == "NONE" and trajectory.end_time > 259200:
                raise CampaignComparisonError("COVERAGE_UNRESOLVED: radius input horizon exceeded")
        events = []
        for system, trajectory in zip(systems, trajectories):
            event = scan_events(system, _EventTrajectory(trajectory, budget))
            budget.check()
            json.dumps(event, allow_nan=False)
            events.append(event)
            result["events"] = events.copy()
        result["event_difference"] = _event_summary(events, configs)
        event_times = [_event_time(event) for event in events]
        event_window_resolved = all(event.get("earliest_verified") and
                                    (event.get("status") == "NO_EVENT" or _event_time(event) is not None)
                                    for event in events)
        common_end = float(min(trajectory.end_time for trajectory in trajectories))
        end = min([common_end] + [value for value in event_times if value is not None])
        result["main_window"] = {
            "start_seconds": 0., "end_seconds": end, "common_legal_end_seconds": common_end,
            "rule": "EARLIEST_USABLE_EVENT_OR_COMMON_LEGAL_END", "event_window_resolved": event_window_resolved,
            "usable_event_count": sum(value is not None for value in event_times),
            "post_end_reference_included": False, "paper_continuation_included": False,
            "common_radius_min_m": None, "common_radius_max_m": None}
        if not event_window_resolved:
            result["issues"].append("EVENT_WINDOW_UNRESOLVED: missing usable event/no-event classification")
        times = {0., end}
        node_set = set()
        for system, trajectory in zip(systems, trajectories):
            for t, _ in trajectory.iter_states():
                budget.check()
                if not np.isfinite(t) or t < 0 or t > trajectory.end_time:
                    raise CampaignComparisonError("COVERAGE_UNRESOLVED: invalid accepted time")
                if t > end:
                    break
                times.add(float(t))
                if len(times) > max_time_points:
                    raise _BudgetReached("COMPARISON_POINT_BUDGET_REACHED")
            for t in system.inputs.nodes(question=system.question, geometry=system.geometry, tmax=end):
                budget.check()
                if 0 <= t <= end:
                    times.add(float(t))
                    node_set.add(float(t))
        if len(times) > max_time_points:
            raise _BudgetReached("COMPARISON_POINT_BUDGET_REACHED")
        times = np.asarray(sorted(times), dtype=float)
        keys = ["T", "C", "G"]
        for label, cfg in zip(("left", "right"), configs):
            if cfg.route == "C":
                keys.extend([label + "_axial_T", label + "_axial_C"])
                axial[label] = {"T": 0., "C": 0.}
        maxima = dict.fromkeys(keys, 0.)

        def inspect(t):
            sides = ("point", "right") if t == 0 else (("left", "right") if t in node_set else ("point",))
            for side in sides:
                budget.admit_sample()
                recs = [reconstruct(s, t, tr.at(t), side=side) for s, tr in zip(systems, trajectories)]
                if result["comparison_kind"] == "B_C_STRUCTURE" and not np.isclose(recs[0].R, recs[1].R, rtol=2e-14, atol=0.):
                    raise CampaignComparisonError("COMPARISON_UNRESOLVED: B/C radii differ despite common input")
                diff = midplane_difference(*recs, check_budget=budget.check)
                for key in ("T", "C", "G"):
                    if key not in locations or diff[key] > maxima[key]:
                        maxima[key] = diff[key]
                        locations[key] = {"time_seconds": t, "side": side, "position": diff["positions"][key]}
                for label, rec in zip(("left", "right"), recs):
                    departure = axial_departure(rec)
                    if departure is None:
                        continue
                    for key in ("T", "C"):
                        name = label + "_axial_" + key
                        if name not in locations or departure[key]["value"] > maxima[name]:
                            maxima[name] = departure[key]["value"]
                            axial[label][key] = departure[key]["value"]
                            locations[name] = {"time_seconds": t, "side": side, "position": departure[key]["position"]}
                window = result["main_window"]
                radius = diff["common_radius_m"]
                for name, operation in (("common_radius_min_m", min), ("common_radius_max_m", max)):
                    window[name] = radius if window[name] is None else operation(window[name], radius)
                budget.samples += 1
                result["sampled_through_time"] = max(t, result["sampled_through_time"] or 0.)

        tolerances = {key: STABILITY_TOLERANCES[key[-1] if "_axial_" in key else key] for key in keys}
        for level in range(max_time_refinements + 1):
            pending = times if level == 0 else (times[:-1] + times[1:]) / 2.
            if level > 0:
                pending = pending[~np.isin(pending, times)]
            previous = dict(maxima)
            for t in pending:
                inspect(float(t))
            budget.check()
            result["time_refinement_maxima"].append({"level": level, "maxima": dict(maxima), "samples": budget.samples})
            result["time_coverage_complete"] = True
            if end == 0 or (level > 0 and all(maxima[key] - previous[key] <= tolerances[key] for key in keys)):
                result["time_stable"] = True
                break
            if level > 0:
                times = np.unique(np.r_[times, pending])
        result["resolved"] = bool(result["time_stable"] and event_window_resolved)
        result["status"] = ("COMPARISON_MEASURED" if result["resolved"] else
                            "EVENT_WINDOW_UNRESOLVED" if not event_window_resolved else "TIME_COMPARISON_UNRESOLVED")
    except _BudgetReached as exc:
        result["status"] = str(exc)
        result["issues"].append(str(exc))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        result["status"] = "COMPARISON_UNRESOLVED"
        result["issues"].append(type(exc).__name__ + ": " + str(exc))
    result["samples"] = budget.samples
    if budget.samples:
        result["differences"] = {key: float(maxima[key]) for key in ("T", "C", "G")}
        result["C_axial_departure"] = axial
        result["maximum_locations"] = locations
    result["partial_evidence"] = not result["resolved"]
    result["elapsed_wall_seconds"] = float(time.perf_counter() - budget.started)
    if out_path is not None:
        output = Path(out_path).resolve()
        for source in result["run_dirs"]:
            run = Path(source)
            if output in {run / "config.json", run / "manifest.json", run / "metrics.json", run / "checkpoint.json"} or any(
                    output.is_relative_to(run / child) for child in ("trajectory", "source_snapshot", "checkpoints")):
                raise ValueError("comparison output cannot overwrite a source run artifact")
        atomic_json(output, result)
    return result
