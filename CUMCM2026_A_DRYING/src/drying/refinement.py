"""Executable A26-04-v2 event reintegration and empirical error evidence.

This module never turns a small event bracket into an error bound. Every
refinement run has a separate manifest and an accepted-state trajectory. A
strict certificate is bound to the final trajectory and fails closed when
comparison categories, coverage, conditioning, or provenance are missing.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import time
import numpy as np
from numpy.polynomial import Polynomial

from .config import RunConfig
from .cuda_backend import CudaBackendError
from .integrator import Integrator, Settings
from .trajectory import Trajectory, TrajectoryWriter, fingerprint, atomic_json, save_checkpoint
from .reconstruction import reconstruct
from .events import scan_events, upward_report_time, verify_report


CORE_MODULES = ("config.py", "inputs.py", "physics.py", "spatial.py", "integrator.py",
                "reconstruction.py", "manufactured.py", "cuda_backend.py")
METRICS = ("T", "C", "G")
RESOURCE_FIELDS = {"wall_seconds", "max_steps", "checkpoint_steps", "max_output_rows",
                   "memory_mb", "gpu_memory_mb", "tmax", "case_end_time"}
HARD_FAILURES = {"GPU_BACKEND_FAILURE", "EXECUTION_EXCEPTION", "NUMERICAL_FAILURE", "MEMORY_BUDGET_REACHED"}
REFERENCE_FIELDS = ("route", "question", "geometry", "end_condition", "scenario", "radius_method",
                    "radius_tail", "window_start_h", "model_version", "input_version", "test_case",
                    "linear_backend", "cuda_device")


class RefinementError(ValueError):
    pass


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _core_hashes(manifest):
    recorded = manifest.get("source", {}).get("files", {})
    result = {}
    for name in CORE_MODULES:
        key = "src/drying/" + name
        if key not in recorded:
            raise RefinementError("PROVENANCE_UNRESOLVED: missing numerical source " + key)
        result[name] = recorded[key]
    return result


def _require_cuda_evidence(config, manifest):
    """A formal GPU certificate needs actual solves, not just a CUDA label/probe."""
    if config.linear_backend != "CUDA":
        raise RefinementError("CUDA_EVIDENCE_REQUIRED: CPU_REFERENCE cannot certify formal drying")
    execution = manifest.get("execution", {})
    records = [a.get("linear_backend", {}) for a in execution.get("attempts", [])]
    if execution.get("linear_backend"):
        records.append(execution["linear_backend"])
    if not records:
        raise RefinementError("CUDA_EVIDENCE_REQUIRED: missing executed backend telemetry")
    for record in records:
        if (record.get("backend") != "CUDA" or record.get("dtype") != "float64" or
            record.get("device_id") != config.cuda_device or record.get("cpu_fallback_calls") != 0):
            raise RefinementError("CUDA_EVIDENCE_REQUIRED: incompatible backend/device/float64 telemetry")
    if not any(record.get("successful_solves", 0) > 0 for record in records):
        raise RefinementError("CUDA_EVIDENCE_REQUIRED: no recorded successful GPU linear solve")


def _load_run(run_dir, data_dir=None, system_factory=None, check_live_core=True):
    from .execution import make_system, verify_system_identity
    path = Path(run_dir).resolve()
    config = RunConfig.from_json(path / "config.json")
    manifest = _read(path / "manifest.json")
    trajectory = Trajectory(path / "trajectory", verify=True)
    identity = manifest.get("identity", {})
    if identity != trajectory.index.get("identity") or identity.get("config") != config.fingerprint:
        raise RefinementError("PROVENANCE_UNRESOLVED: config/manifest/trajectory identity mismatch")
    core = _core_hashes(manifest)
    if check_live_core:
        for name, digest in core.items():
            if _file_hash(Path(__file__).parent / name) != digest:
                raise RefinementError("PROVENANCE_UNRESOLVED: live numerical source differs: " + name)
    system = system_factory(config) if system_factory is not None else make_system(config, data_dir)
    if system_factory is None:
        verify_system_identity(manifest, system, config, run_dir=path)
    if system.inputs.fingerprint != identity.get("input"):
        raise RefinementError("PROVENANCE_UNRESOLVED: input fingerprint changed")
    status = manifest.get("solver", {}).get("status", "")
    if status in {"EXECUTION_EXCEPTION", "NUMERICAL_FAILURE", "GPU_BACKEND_FAILURE", "RUNNING"}:
        raise RefinementError("RUN_UNRESOLVED: source solver status " + status)
    return path, config, manifest, system, trajectory


def _accepted_state(trajectory, t):
    for st, sy in trajectory.iter_states():
        if st == t:
            return np.asarray(sy)
        if st > t:
            break
    raise RefinementError("CHECKPOINT_INVALID: time is not an accepted trajectory endpoint")


def select_checkpoint(run_dir, trajectory, system, config, identity, before):
    """Select genuine stored history; interpolation can never supply a restart.

    If no later checkpoint exists, the recorded and independently reproduced
    initial condition is the legal single-state BE startup checkpoint.
    """
    path = Path(run_dir)
    candidates = list((path / "checkpoints").glob("*.json"))
    if (path / "checkpoint.json").exists():
        candidates.append(path / "checkpoint.json")
    selected = None
    for candidate in candidates:
        obj = _read(candidate)
        t = float(obj.get("integrator", {}).get("t", float("inf")))
        if t > before or (selected is not None and t <= selected[0]):
            continue
        if obj.get("identity") != identity:
            raise RefinementError("CHECKPOINT_INVALID: checkpoint identity mismatch")
        s = obj["integrator"]
        if not np.array_equal(_accepted_state(trajectory, t), np.asarray(s["y"])):
            raise RefinementError("CHECKPOINT_INVALID: state differs from accepted trajectory")
        if s.get("y_prev") is not None:
            tp = s.get("t_prev")
            if tp is None or not tp < t or not np.array_equal(_accepted_state(trajectory, tp), np.asarray(s["y_prev"])):
                raise RefinementError("CHECKPOINT_INVALID: previous state is not accepted history")
            if abs((t - tp) - s["h_prev"]) > 8 * np.spacing(max(1., t)):
                raise RefinementError("CHECKPOINT_INVALID: previous accepted step length")
        elif not s.get("needs_be"):
            raise RefinementError("CHECKPOINT_INVALID: missing multistep history without BE restart")
        selected = (t, obj, str(candidate), _file_hash(candidate))
    if selected is not None:
        return selected[1], {"kind": "STORED_ACCEPTED_CHECKPOINT", "path": selected[2], "sha256": selected[3]}
    if trajectory.start_time != 0 or not np.array_equal(_accepted_state(trajectory, 0.), system.initial()):
        raise RefinementError("CHECKPOINT_UNAVAILABLE: no valid preceding accepted checkpoint")
    solver = Integrator(system, Settings.from_config(config))
    return {"identity": identity, "integrator": solver.snapshot(), "extra": {}}, {
        "kind": "VERIFIED_INITIAL_STATE", "time": 0., "state_sha256": fingerprint(solver.y.tolist())}


def _advance_checkpoint_bridge(solver, source_settings, local_settings, *, before, until,
                               forced_nodes=(), wall_seconds, started, callback,
                               persist_bridge, clock=None):
    """Advance real accepted history in two phases under one finite budget.

    The bridge uses the source configuration's approved time control. Only the
    suffix after ``before`` uses the local event hmax. No state is copied from
    an interpolant and the solver's accepted BDF history is never reset.
    ``persist_bridge`` must save/verify the actual accepted endpoint before
    the local phase can begin. Phase diagnostics are solver telemetry, not a
    substitute for independently recomputed whole-trajectory balances.
    """
    clock = time.perf_counter if clock is None else clock
    origin_accepted = int(solver.stats["accepted"])
    max_steps = int(local_settings.max_steps)
    phases = []

    def failure(status, message=None):
        return {"status": status, "t": solver.t, "failure": message,
                "stats": solver.stats, "algorithm": solver.algorithm}

    def phase(name, endpoint, settings, nodes):
        phase_start = float(solver.t)
        accepted_before = int(solver.stats["accepted"])
        remaining_steps = max_steps - (accepted_before - origin_accepted)
        remaining_wall = wall_seconds - (clock() - started)
        record = {"phase": name, "start": phase_start, "end_target": float(endpoint),
                  "hmax": settings.hmax, "requested_settings": asdict(settings),
                  "wall_seconds_available": max(0., remaining_wall),
                  "accepted_steps_available": max(0, remaining_steps),
                  "accepted_steps": 0, "min_h": None, "max_h": 0.,
                  "max_E": 0., "max_newton_residual": 0., "max_linear_residual": 0.,
                  "balances": "NOT_RECOMPUTED_FROM_PHASE_TELEMETRY"}
        phases.append(record)
        phase_started = clock()

        def accepted(t0, y0, t1, y1, info, residual):
            h = float(t1 - t0)
            record["accepted_steps"] += 1
            record["min_h"] = h if record["min_h"] is None else min(record["min_h"], h)
            record["max_h"] = max(record["max_h"], h)
            for target, field in (("max_E", "E"), ("max_newton_residual", "residual"),
                                  ("max_linear_residual", "linear")):
                record[target] = max(record[target], float(info[field]))
            callback(t0, y0, t1, y1, info, residual, phase=name)

        if endpoint == solver.t:
            result = failure("COMPLETED_INTERVAL")
        elif remaining_steps <= 0:
            result = failure("STEP_BUDGET_REACHED")
        elif remaining_wall <= 0:
            result = failure("WALL_BUDGET_REACHED")
        else:
            # Integrator.run counts its own call's accepted steps. Passing the
            # remaining shared count prevents a second full budget at the phase
            # boundary. Tolerances, backend/device and BDF history stay intact.
            solver.cfg = replace(settings, max_steps=remaining_steps, wall_seconds=remaining_wall)
            solver.h_next = min(solver.h_next, settings.hmax)
            record["actual_settings"] = asdict(solver.cfg)
            try:
                result = solver.run(float(endpoint), callback=accepted, forced_nodes=nodes,
                                    wall_seconds=remaining_wall)
            except CudaBackendError as exc:
                result = failure("GPU_BACKEND_FAILURE", str(exc))
            except Exception as exc:
                result = failure("EXECUTION_EXCEPTION", repr(exc))
            finally:
                # A checkpoint at the phase boundary records the configured
                # strategy, not the temporary remaining-call resource caps.
                # The phase record above retains the actual enforced caps.
                solver.cfg = settings
        record.update(status=result["status"], end=float(solver.t),
                      elapsed_seconds=max(0., clock() - phase_started),
                      accepted_steps_committed=int(solver.stats["accepted"]) - accepted_before,
                      failure=result.get("failure"))
        return result

    result = phase("CHECKPOINT_BRIDGE", float(before), source_settings, [float(before)])
    if result["status"] == "COMPLETED_INTERVAL":
        if solver.t != before:
            result = failure("EXECUTION_EXCEPTION", "BRIDGE_ENDPOINT_UNRESOLVED: no exact accepted endpoint")
        else:
            try:
                phases[-1]["accepted_checkpoint"] = persist_bridge()
            except Exception as exc:
                result = failure("EXECUTION_EXCEPTION", "BRIDGE_CHECKPOINT_FAILED: " + repr(exc))
                phases[-1]["checkpoint_failure"] = result["failure"]
    if result["status"] == "COMPLETED_INTERVAL":
        nodes = [float(t) for t in forced_nodes if before < t <= until]
        result = phase("LOCAL_REINTEGRATION", float(until), local_settings, nodes)
    else:
        phases.append({"phase": "LOCAL_REINTEGRATION", "status": "NOT_RUN",
                       "start": None, "end_target": float(until), "hmax": local_settings.hmax,
                       "accepted_steps": 0, "accepted_steps_committed": 0,
                       "reason": "bridge solve/checkpoint did not complete"})
    result = dict(result)
    result.update(phase_diagnostics=phases,
                  accepted_this_call=int(solver.stats["accepted"]) - origin_accepted,
                  wall_seconds=max(0., clock() - started),
                  shared_budget={"wall_seconds": wall_seconds, "max_steps": max_steps,
                                 "scope": "ONE_BRIDGE_AND_LOCAL_SUFFIX_INVOCATION"})
    return result


def _reintegrate_suffix(run_dir, out_dir, *, before, until, forced_nodes=(), hmax=None,
                        width=None, threshold=None, data_dir=None, system_factory=None,
                        wall_seconds=300.):
    """Bridge from a real checkpoint, then solve the requested local suffix."""
    run_started = time.perf_counter()
    from .execution import code_identity, system_identity, _factory_hash, environment
    src, config, manifest, system, old = _load_run(run_dir, data_dir, system_factory, check_live_core=True)
    out = Path(out_dir).resolve()
    if out.exists():
        raise FileExistsError(out)
    if (not np.isfinite(before) or not np.isfinite(until) or until <= before or
            before < old.start_time or until > config.tmax or
            not np.isfinite(wall_seconds) or wall_seconds <= 0):
        raise RefinementError("REPORT_TIME_UNRESOLVED: reintegration outside finite authorized horizon")
    obj, cp_source = select_checkpoint(src, old, system, config, manifest["identity"], before)
    snapshot = obj["integrator"]
    # Restore the actual accepted history. The approved source time strategy
    # first reaches the local interval; a distant checkpoint must not force
    # every preceding step to use a submillisecond event step size.
    solver = Integrator(system, Settings(**snapshot["settings"]))
    solver.restore(snapshot)
    if hmax is not None and (not np.isfinite(hmax) or hmax <= 0):
        raise RefinementError("REPORT_TIME_UNRESOLVED: local hmax must be positive and finite")
    local_hmax = min(config.hmax, float(hmax)) if hmax is not None else config.hmax
    new_config = replace(config, hmax=local_hmax, h0=min(config.h0, local_hmax),
                         case_end_time=float(until), wall_seconds=float(wall_seconds))
    source_settings = Settings.from_config(config)
    local_settings = Settings.from_config(new_config)
    code = code_identity()
    identity = {"config": new_config.fingerprint, "input": system.inputs.fingerprint,
                "code": code["sha256"], "model_version": config.model_version, "dtype": "float64",
                "system": fingerprint(system_identity(system, new_config))}
    out.mkdir(parents=True)
    new_config.to_json(out / "config.json")
    for relative in code["files"]:
        target = out / "source_snapshot" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(__file__).resolve().parents[2] / relative, target)
    start = float(solver.t)
    lineage = {"source_run": str(src), "source_identity": manifest["identity"],
               "source_trajectory_fingerprint": fingerprint(old.index), "checkpoint": cp_source,
               "checkpoint_time": start, "prefix_end": start,
               "method": "ACCEPTED_CHECKPOINT_REINTEGRATION", "local_hmax": local_hmax,
               "target_width": width, "threshold": threshold,
               "forced_nodes": [float(t) for t in forced_nodes],
               "injected_test_system": system_factory is not None,
               "numerical_source_sha256": fingerprint(_core_hashes(manifest)),
               "refinement_module_sha256": _file_hash(__file__)}
    lineage["step_policy"] = {
        "scope": "PIECEWISE_LOCAL_EVENT_CONTROL_NOT_GLOBAL_HMAX_REFINEMENT",
        "inherited_prefix": {"start": old.start_time, "end": start,
                             "source_config_fingerprint": config.fingerprint,
                             "checkpoint_hmax": snapshot["settings"]["hmax"]},
        "checkpoint_bridge": {"start": start, "end_target": float(before),
                              "hmax": source_settings.hmax,
                              "source_config_fingerprint": config.fingerprint,
                              "strategy": "SOURCE_SETTINGS_REAL_ACCEPTED_REINTEGRATION"},
        "reintegrated_suffix": {"start": float(before), "end_target": float(until), "hmax": local_hmax},
        "budget": {"wall_seconds": float(wall_seconds), "max_steps": new_config.max_steps,
                   "scope": "SHARED_BRIDGE_AND_LOCAL_SUFFIX_NOT_PER_PHASE"}}
    new_manifest = deepcopy(manifest)
    new_manifest.update(identity=identity, source=dict(code, snapshot_directory="source_snapshot"),
                        refinement=lineage)
    new_manifest["system_contract"] = system_identity(system, new_config)
    new_manifest["factory_sha256"] = _factory_hash((Path(__file__).parent / "execution.py").read_text(encoding="utf-8"))
    new_manifest["configuration"] = {"config_file": "config.json", "fingerprint": new_config.fingerprint,
                                     "random_seed": new_config.seed}
    new_manifest["experiment"] = {"experiment_id": out.name, "name": out.name,
                                  "status": "RUNNING", "created_at": datetime.now(timezone.utc).isoformat()}
    new_manifest["solver"] = {"name": solver.algorithm, "status": "RUNNING"}
    new_manifest['execution']={
        'execution_backend':new_config.execution_backend,
        'execution_purpose':new_config.execution_purpose,
        'production_eligible':new_config.production_eligible,
        'device':new_config.linear_backend,'command':'ACCEPTED_CHECKPOINT_REINTEGRATION',
        'environment':'environment.json','runtime_seconds':None,
        'inherited_prefix_execution_manifest':str(src/'manifest.json'),
        'attempts':[]}
    env=environment(); env['linear_backend']=solver.linear_backend_metadata()
    atomic_json(out/'environment.json',env)
    new_manifest["outputs"] = {"trajectory": "trajectory/index.json", "checkpoint": "checkpoint.json",
                               "metrics_file": "metrics.json", "event_file": "event.json", "result_files": [],
                               "diagnostics_file": "diagnostics.json",
                               "phase_diagnostics_file": "phase_diagnostics.json"}
    new_manifest["summary"] = {"notes": "Checkpoint-reintegrated trajectory; inherited run balances are not current evidence.",
                               "diagnostics_status": "DIAGNOSTICS_UNRESOLVED"}
    atomic_json(out / "manifest.json", new_manifest)
    writer = TrajectoryWriter(out / "trajectory", identity)
    for t, y in old.iter_states():
        if t > start:
            break
        writer.append(t, y)
    writer.flush()
    save_checkpoint(out / "checkpoints" / "origin.json", solver, identity,
                    {"inherited_accepted_history": cp_source, "source_identity": manifest["identity"]})
    accepted_count = 0
    step_log = (out / "steps.jsonl").open("w", encoding="utf-8")
    def accept(t0, y0, t1, y1, info, residual, *, phase):
        nonlocal accepted_count
        writer.append(t1, y1)
        logged = {k: v for k, v in info.items() if k != "absolute_history"}
        logged["reintegration_phase"] = phase
        step_log.write(json.dumps(logged, allow_nan=False) + "\n")
        accepted_count += 1
        # Event suffixes need a restart before each possible candidate substep.
        # Stream states in bounded chunks; checkpoint files are accepted history.
        save_checkpoint(out / "checkpoints" / f"accepted_{solver.stats['accepted']:09d}.json", solver, identity)
    def persist_bridge():
        writer.flush()
        checkpoint = out / "checkpoints" / "bridge_endpoint.json"
        current_trajectory = Trajectory(out / "trajectory", verify=True)
        if not np.array_equal(_accepted_state(current_trajectory, float(before)), solver.y):
            raise RefinementError("BRIDGE_CHECKPOINT_INVALID: endpoint is not a persisted accepted state")
        save_checkpoint(checkpoint, solver, identity,
                        {"kind": "ACTUAL_ACCEPTED_BRIDGE_ENDPOINT", "source_identity": manifest["identity"],
                         "source_checkpoint": cp_source, "source_settings": asdict(source_settings),
                         "local_settings": asdict(local_settings)})
        return {"kind": "ACTUAL_ACCEPTED_BRIDGE_ENDPOINT", "path": str(checkpoint),
                "sha256": _file_hash(checkpoint), "time": float(solver.t),
                "state_fingerprint": fingerprint(solver.y.tolist()),
                "trajectory_fingerprint": fingerprint(current_trajectory.index)}

    try:
        result = _advance_checkpoint_bridge(solver, source_settings, local_settings,
            before=float(before), until=float(until), forced_nodes=forced_nodes,
            wall_seconds=float(wall_seconds), started=run_started,
            callback=accept, persist_bridge=persist_bridge)
    except CudaBackendError as exc:
        result = {"status": "GPU_BACKEND_FAILURE", "failure": str(exc), "t": solver.t, "stats": solver.stats}
    except Exception as exc:
        result = {"status": "EXECUTION_EXCEPTION", "failure": repr(exc), "t": solver.t, "stats": solver.stats}
    finally:
        step_log.close()
    writer.flush()
    save_checkpoint(out / "checkpoint.json", solver, identity)
    result.update(run_id=out.name, event_reintegration=True, checkpoint_time=start,
                  linear_backend=solver.linear_backend_metadata(),
                  source_run=str(src), stage07="NOT_RUN")
    atomic_json(out / "metrics.json", result)
    phase_diagnostics = result.get("phase_diagnostics", [])
    atomic_json(out / "phase_diagnostics.json", {
        "status": result["status"], "phases": phase_diagnostics,
        "shared_budget": result.get("shared_budget"),
        "scope": "ACCEPTED_STEP_SOLVER_TELEMETRY_NOT_WHOLE_PATH_BALANCE_VALIDATION",
        "stage07": "NOT_RUN"})
    new_manifest["solver"]["status"] = result["status"]
    new_manifest['execution']['runtime_seconds']=time.perf_counter()-run_started
    new_manifest['execution']['linear_backend']=solver.linear_backend_metadata()
    new_manifest['execution']['exit_code']=(1 if result['status'] in HARD_FAILURES else
                                            0 if result['status']=='COMPLETED_INTERVAL' else 2)
    new_manifest["experiment"].update(status=result["status"], completed_at=datetime.now(timezone.utc).isoformat())
    new_manifest["refinement"]["new_accepted_steps"] = accepted_count
    new_manifest["refinement"]["bridge_accepted_steps"] = sum(
        p.get("accepted_steps_committed", 0) for p in phase_diagnostics if p["phase"] == "CHECKPOINT_BRIDGE")
    new_manifest["refinement"]["local_accepted_steps"] = sum(
        p.get("accepted_steps_committed", 0) for p in phase_diagnostics if p["phase"] == "LOCAL_REINTEGRATION")
    new_manifest["refinement"]["phase_diagnostics"] = phase_diagnostics
    new_manifest["refinement"]["bridge_checkpoint"] = next(
        (p["accepted_checkpoint"] for p in phase_diagnostics if "accepted_checkpoint" in p), None)
    new_manifest["refinement"]["actual_restart_settings"] = snapshot["settings"]
    new_manifest["refinement"]["trajectory_fingerprint"] = fingerprint(Trajectory(out / "trajectory").index)
    atomic_json(out / "diagnostics.json", {"status": "DIAGNOSTICS_UNRESOLVED",
        "checks_passed": False, "trajectory_fingerprint": new_manifest["refinement"]["trajectory_fingerprint"],
        "reason": "Run recompute_balances on the complete current accepted trajectory; old run diagnostics are not reused."})
    atomic_json(out / "manifest.json", new_manifest)
    return {"status": result["status"], "exit_code": new_manifest['execution']['exit_code'],
            "run_dir": str(out), "new_accepted_steps": accepted_count,
            "checkpoint_time": start, "result": result}


def refine_event(run_dir, out_dir, threshold=.15, width=.01, max_levels=8,
                 data_dir=None, wall_seconds=300., system_factory=None):
    """Restore and solve new event substeps; never repeatedly bisect one interpolant.

    Returns the final run path, event record, every actual reintegration, and an
    honest unresolved status if a candidate disappears, rebounds or exhausts
    finite coverage/budget. Existing source runs are never overwritten.
    """
    if not np.isfinite(width) or width <= 0 or width > .01 or max_levels < 1:
        raise ValueError("event width must be in (0,.01], max_levels >= 1")
    root = Path(out_dir).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    current = Path(run_dir).resolve()
    rounds = []
    start_wall = time.perf_counter()
    event = None
    original_horizon = None
    for level in range(max_levels):
        _, config, manifest, system, trajectory = _load_run(current, data_dir, system_factory, True)
        if original_horizon is None:
            original_horizon = trajectory.end_time
        event = scan_events(system, trajectory, threshold=threshold)
        if event["status"] == "NO_EVENT" and rounds and trajectory.end_time < original_horizon:
            remaining = wall_seconds - (time.perf_counter() - start_wall)
            if remaining <= 0:
                event["issues"].append("candidate disappeared before finite scan could continue")
                break
            continuation = _reintegrate_suffix(current, root / f"continued_{level + 1:02d}",
                before=trajectory.end_time, until=original_horizon, data_dir=data_dir,
                system_factory=system_factory, wall_seconds=remaining,
                width=width, threshold=threshold)
            rounds.append(continuation); current = Path(continuation["run_dir"])
            if continuation["status"] != "COMPLETED_INTERVAL":
                event["issues"].append("chronological scan continuation failed")
                break
            continue
        if event["status"] != "PROVISIONAL_EVENT" or not event["earliest_verified"] or not event["retention_verified"]:
            break
        # A previously refined narrow bracket may be returned without duplicate
        # work only if its manifest proves actual checkpoint reintegration.
        prior = manifest.get("refinement", {})
        if (event["tR"] - event["tL"] <= width and
                prior.get("method") == "ACCEPTED_CHECKPOINT_REINTEGRATION" and
                prior.get("local_accepted_steps", prior.get("new_accepted_steps", 0)) > 0 and
                prior.get("target_width") is not None and prior["target_width"] <= width):
            break
        left, right = event["candidate_segment"]
        # Constrain a small neighborhood, not millions of post-event seconds.
        # Every accepted segment in the actual reintegrated suffix is rescanned.
        end = min(trajectory.end_time, max(right, event["tR"] + 4 * width))
        nodes = sorted(set([left, (left + right) / 2, right, event["t_hat"], event["tR"]]))
        nodes = [t for t in nodes if 0 < t <= end]
        remaining = wall_seconds - (time.perf_counter() - start_wall)
        if remaining <= 0:
            event["status"] = "EVENT_UNRESOLVED"
            event["issues"].append("event reintegration wall budget reached")
            break
        work = _reintegrate_suffix(current, root / f"level_{level + 1:02d}", before=left, until=end,
                                   forced_nodes=nodes, hmax=width / 2, width=width, threshold=threshold,
                                   data_dir=data_dir, system_factory=system_factory, wall_seconds=remaining)
        rounds.append(work)
        current = Path(work["run_dir"])
        if work["status"] != "COMPLETED_INTERVAL":
            event["status"] = "EVENT_UNRESOLVED"
            event["issues"].append("new event integration did not complete: " + work["status"])
            break
    if rounds and rounds[-1]["status"] == "COMPLETED_INTERVAL":
        _, _, _, system, trajectory = _load_run(current, data_dir, system_factory, True)
        event = scan_events(system, trajectory, threshold=threshold)
    if event is None:
        raise RefinementError("EVENT_UNRESOLVED: no event scan executed")
    if rounds and rounds[-1]["status"] in HARD_FAILURES:
        failed = rounds[-1]
        result = {"status": failed["status"], "exit_code": 1, "run_dir": str(current),
                  "rounds": rounds, "event": {"status": "EVENT_UNRESOLVED", "refinement_verified": False,
                  "issues": ["reintegration failed: " + failed["status"]]}, "stage07": "NOT_RUN"}
        atomic_json(root / "refinement.json", result)
        atomic_json(current / "event.json", result["event"])
        return result
    actual = bool(rounds) or _read(current / "manifest.json").get("refinement", {}).get("method") == "ACCEPTED_CHECKPOINT_REINTEGRATION"
    ready = (event["status"] == "PROVISIONAL_EVENT" and event["earliest_verified"] and
             event["retention_verified"] and event["tR"] - event["tL"] <= width and actual)
    if ready:
        # All full exposed nodes are independently checked, in addition to the
        # affine base-node candidate calculation.
        for key in ("tL", "tR"):
            rr = reconstruct(system, event[key], trajectory.at(event[key]))
            event[key + "_max_C"] = rr.max_C
            event[key + "_max_position"] = rr.max_position
        if not event["tL_max_C"] >= threshold or not event["tR_max_C"] < threshold:
            ready = False
            event["issues"].append("full-node left/right event bracket check failed")
    event.update(refinement_verified=ready, target_width=width,
                 trajectory_fingerprint=fingerprint(trajectory.index), run_dir=str(current))
    result = {"status": "EVENT_BRACKET_REFINED" if ready else "EVENT_UNRESOLVED",
              "run_dir": str(current), "event": event, "rounds": rounds,
              "method": "ACCEPTED_CHECKPOINT_REINTEGRATION", "stage07": "NOT_RUN"}
    atomic_json(root / "refinement.json", result)
    atomic_json(current / "event.json", event)
    return result


def extend_refinement_run(run_dir, out_dir, until, *, data_dir=None, wall_seconds=300., system_factory=None):
    """Continue a refined accepted history to the finite report/evidence horizon."""
    _, cfg, manifest, system, trajectory = _load_run(run_dir, data_dir, system_factory, True)
    local = manifest.get("refinement", {})
    return _reintegrate_suffix(run_dir, out_dir, before=trajectory.end_time, until=float(until),
        forced_nodes=[float(until)], width=local.get("target_width"), threshold=local.get("threshold"),
        data_dir=data_dir, wall_seconds=wall_seconds, system_factory=system_factory)


def recompute_balances(run_dir, out_path=None, *, data_dir=None, wall_seconds=300., system_factory=None):
    """Independent cumulative balances of the *entire current* accepted path.

    The heat derivative is the accepted-state secant; the RHS is never
    substituted for it. BDF layer checks are not reconstructed from nonexistent
    residual logs and are explicitly marked separately.
    """
    from .diagnostics import Diagnostics
    path, cfg, manifest, system, trajectory = _load_run(run_dir, data_dir, system_factory, True)
    result = {"status": "DIAGNOSTICS_UNRESOLVED", "checks_passed": False,
              "trajectory_fingerprint": fingerprint(trajectory.index), "config_fingerprint": cfg.fingerprint,
              "covered_until": 0., "layer_checks": "NOT_RECOMPUTED_FROM_PATH", "stage07": "NOT_RUN"}
    started = time.perf_counter()
    try:
        if trajectory.start_time != 0:
            raise RefinementError("cumulative diagnostic requires the complete prefix from zero")
        d = Diagnostics(system, trajectory.end_time, Settings.from_config(cfg))
        for t0, y0, t1, y1 in trajectory.iter_segments():
            if time.perf_counter()-started > wall_seconds:
                raise RefinementError("independent balance wall budget reached")
            if d.data["covered_until"] != t0:
                raise RefinementError("gap in cumulative diagnostic coverage")
            d.add_segment(t0,y0,t1,y1)
        result.update(d.summary())
        # These zero-valued fields in Diagnostics are initialized counters, not
        # observed layer evidence when info/residual was deliberately absent.
        for name in ("layer_water_max", "layer_heat_max", "layer_bound_violations"):
            result[name] = None
        result["checks_passed"] = (result["covered_until"] == trajectory.end_time and
            result["water_budget_passed"] and result["heat_budget_passed"] and not result["quadrature_unresolved"])
        result["status"] = "CURRENT_CUMULATIVE_BALANCES_CHECKED" if result["checks_passed"] else "DIAGNOSTICS_UNRESOLVED"
    except (ValueError, AttributeError) as exc:
        result["reason"] = str(exc)
    result["wall_seconds"] = time.perf_counter()-started
    atomic_json(out_path or path/"diagnostics.json", result)
    return result


def _real_unit_roots(poly):
    coef = np.asarray(poly.coef, float)
    if not np.any(coef):
        return []
    scale = np.max(np.abs(coef))
    # Trailing cancellation at machine precision is a polynomial evaluation
    # issue, not a tolerance for field/error certification.
    while len(coef) > 1 and abs(coef[-1]) <= 64 * np.finfo(float).eps * scale:
        coef = coef[:-1]
    if len(coef) == 1:
        return []
    roots = Polynomial(coef / scale).roots()
    return [float(z.real) for z in roots if abs(z.imag) <= 1e-8 and 0 < z.real < 1]


def polynomial_rectangle_max(coefficients):
    """Maximum absolute biquadratic on a unit rectangle, incl. stationary roots.

    Each reconstruction patch is bilinear in x or x² and z or z². Their
    difference is biquadratic. Eliminate x from the two partial derivatives;
    the remaining degree <=5 polynomial contains every isolated interior
    stationary point. Degenerate x-flat lines attain the same value on edges.
    """
    c = np.asarray(coefficients, float)
    if c.shape != (3, 3) or np.any(~np.isfinite(c)):
        raise ValueError("expected finite 3x3 biquadratic coefficients")
    def value(x, z):
        return float(np.polynomial.polynomial.polyval2d(x, z, c))
    candidates = [(0., 0.), (0., 1.), (1., 0.), (1., 1.)]
    for x in (0., 1.):
        q = Polynomial(np.array([1., x, x*x]) @ c)
        candidates.extend((x, z) for z in _real_unit_roots(q.deriv()))
    for z in (0., 1.):
        q = Polynomial(c @ np.array([1., z, z*z]))
        candidates.extend((x, z) for x in _real_unit_roots(q.deriv()))
    A, B, C = Polynomial(c[2]), Polynomial(c[1]), Polynomial(c[0])
    stationary = A.deriv()*B*B - 2*B.deriv()*B*A + 4*C.deriv()*A*A
    for z in _real_unit_roots(stationary):
        az = A(z)
        if az != 0:
            x = -B(z)/(2*az)
            if 0 < x < 1:
                candidates.append((float(x), z))
    values = np.array([abs(value(x, z)) for x, z in candidates])
    i = int(np.argmax(values))
    return float(values[i]), candidates[i]


_VANDER_INV = np.linalg.inv(np.array([[1., 0., 0.], [1., .5, .25], [1., 1., 1.]]))


def spatial_difference(first, second):
    """Full reconstructed T/C suprema on the union of all spatial breakpoints."""
    if first.system.grid.route != second.system.grid.route or not np.isclose(first.R, second.R, rtol=2e-14, atol=0):
        raise RefinementError("COMPARISON_UNRESOLVED: unlike route/geometry")
    xs = np.unique(np.r_[first.xi, second.xi])
    zs = np.array([0., 1.]) if first.system.grid.route == "B" else np.unique(np.r_[first.z, second.z])
    maximum, positions = np.zeros(2), [(0., 0.), (0., 0.)]
    fractions = (0., .5, 1.)
    for xl, xr in zip(xs[:-1], xs[1:]):
        for zl, zr in zip(zs[:-1], zs[1:]):
            sample = np.empty((3, 3, 2))
            for i, u in enumerate(fractions):
                for j, v in enumerate(fractions):
                    z = 0. if first.system.grid.route == "B" else zl + v*(zr-zl)
                    x = xl + u*(xr-xl)
                    sample[i, j] = np.subtract(first._query_xi(x, z), second._query_xi(x, z))
            for eq in range(2):
                if first.system.grid.route == "B":
                    p = Polynomial(_VANDER_INV @ sample[:, 0, eq])
                    points = [0., 1.] + _real_unit_roots(p.deriv())
                    vals = [abs(float(p(u))) for u in points]
                    at = int(np.argmax(vals)); val, uv = vals[at], (points[at], 0.)
                else:
                    coeff = _VANDER_INV @ sample[:, :, eq] @ _VANDER_INV.T
                    val, uv = polynomial_rectangle_max(coeff)
                if val > maximum[eq]:
                    maximum[eq] = val
                    positions[eq] = (float(xl + uv[0]*(xr-xl)),
                                     0. if first.system.grid.route == "B" else float(zl + uv[1]*(zr-zl)))
    return {"T": float(maximum[0]), "C": float(maximum[1]),
            "G": abs(first.max_C-second.max_C), "positions": {"T": positions[0], "C": positions[1],
            "G": (first.max_position, second.max_position)}}


def compare_runs(run_a, run_b, *, coverage_end=None, data_dir=None, max_time_refinements=6,
                 max_time_points=200000, stability_tolerances=(1e-5, 1e-8, 1e-8),
                 wall_seconds=300., system_factory=None):
    """Measured adjacent-run differences, including the initial surface layer.

    Time samples are the complete union of accepted endpoints plus recursively
    inserted midpoints. Stability is empirical; neither these differences nor
    the subsequent factor-two allowance are claimed as mathematical bounds.
    """
    pa, ca, ma, sa, ta = _load_run(run_a, data_dir, system_factory)
    pb, cb, mb, sb, tb = _load_run(run_b, data_dir, system_factory)
    if ma["identity"]["input"] != mb["identity"]["input"] or _core_hashes(ma) != _core_hashes(mb):
        raise RefinementError("PROVENANCE_UNRESOLVED: numerical source/input versions differ")
    if ca.route != cb.route or ca.question != cb.question or ca.geometry != cb.geometry:
        raise RefinementError("COMPARISON_UNRESOLVED: unlike physical definitions")
    end = min(ta.end_time, tb.end_time) if coverage_end is None else float(coverage_end)
    if ta.start_time != 0 or tb.start_time != 0 or end > min(ta.end_time, tb.end_time) or end <= 0:
        raise RefinementError("COVERAGE_UNRESOLVED: complete common interval from zero required")
    times = np.unique(np.r_[[float(t) for t, _ in ta.iter_states() if t <= end],
                           [float(t) for t, _ in tb.iter_states() if t <= end], end])
    node_set = set(map(float, sa.inputs.nodes(question=sa.question, geometry=sa.geometry, tmax=end)))
    maximum = np.zeros(3); locations = {}; samples = 0
    start = time.perf_counter()
    history = []
    resolved = False
    reason = "TIME_COMPARISON_UNRESOLVED"
    def inspect(t):
        nonlocal samples, maximum
        sides = ("point", "right") if t == 0 else (("left", "right") if t in node_set else ("point",))
        for side in sides:
            one = reconstruct(sa, t, ta.at(t), side=side)
            two = reconstruct(sb, t, tb.at(t), side=side)
            diff = spatial_difference(one, two)
            for i, name in enumerate(METRICS):
                if diff[name] > maximum[i]:
                    maximum[i] = diff[name]
                    locations[name] = {"time": float(t), "side": side, "position": diff["positions"][name]}
            samples += 1
    try:
        for level in range(max_time_refinements + 1):
            pending = times if level == 0 else (times[:-1] + times[1:]) / 2
            if samples + len(pending) > max_time_points:
                reason = "COMPARISON_POINT_BUDGET_REACHED"; break
            previous = maximum.copy()
            for t in pending:
                if time.perf_counter() - start > wall_seconds:
                    reason = "COMPARISON_WALL_BUDGET_REACHED"; break
                inspect(float(t))
            else:
                history.append(dict(zip(METRICS, map(float, maximum))))
                if level > 0 and np.all(maximum - previous <= np.asarray(stability_tolerances)):
                    resolved = True; reason = "COMPARISON_MEASURED"; break
                if level > 0:
                    times = np.unique(np.r_[times, pending])
                continue
            break
    except ValueError as exc:
        reason = "RECONSTRUCTION_UNRESOLVED: " + str(exc)
    result = {"status": reason, "resolved": resolved, "differences": dict(zip(METRICS, map(float, maximum))),
              "coverage_start": 0., "coverage_end": end, "samples": samples,
              "time_refinement_maxima": history, "maximum_locations": locations,
              "comparison": "UNION_SPATIAL_BREAKPOINTS_AND_STATIONARY_POINTS;UNION_ACCEPTED_TIMES_PLUS_MIDPOINTS",
              "run_ids": [pa.name, pb.name], "run_dirs": [str(pa), str(pb)],
              "trajectory_fingerprints": [fingerprint(ta.index), fingerprint(tb.index)],
              "config_fingerprints": [ca.fingerprint, cb.fingerprint],
              "numerical_source_sha256": fingerprint(_core_hashes(ma)),
              "initial_layer_included": True, "empirical_not_bound": True}
    if resolved:
        ea, eb = scan_events(sa, ta), scan_events(sb, tb)
        valid = all(e["status"] == "PROVISIONAL_EVENT" and e["earliest_verified"] and e["retention_verified"] for e in (ea, eb))
        result["event_difference"] = abs(ea["t_hat"] - eb["t_hat"]) if valid else None
        result["events"] = [ea, eb]
    return result


def plan_refinement_configs(base):
    """Return three approved parameter levels per global numerical category.

    Event widths are local-reintegration commands, not fabricated RunConfig
    fields. Calling this function does not launch any experiment.
    """
    cfg = base if isinstance(base, RunConfig) else RunConfig.from_dict(base)
    fine = replace(cfg, nr=cfg.nr*4, nz=cfg.nz*4 if cfg.route=="C" else 1)
    result = {"radial": [replace(cfg, nr=cfg.nr*2**i).as_dict() for i in range(3)],
              "time": [replace(fine, rtol=cfg.rtol/10**i, atol_t=cfg.atol_t/10**i, atol_c=cfg.atol_c/10**i).as_dict() for i in range(3)],
              "newton": [replace(fine, newton_tol=cfg.newton_tol/10**i, linear_tol=cfg.linear_tol/10**i).as_dict() for i in range(3)],
              "dense": [replace(fine, hmax=cfg.hmax/2**i, h0=min(cfg.h0, cfg.hmax/2**i)).as_dict() for i in range(3)],
              "event": [{"width": .01/2**i, "method": "ACCEPTED_CHECKPOINT_REINTEGRATION"} for i in range(3)]}
    if cfg.route == "C":
        result["axial"] = [replace(cfg, nz=cfg.nz*2**i).as_dict() for i in range(3)]
        result["joint"] = [replace(cfg, nr=cfg.nr*2**i, nz=cfg.nz*2**i).as_dict() for i in range(3)]
    return result


def _validate_category(category, configs, manifests):
    varied = {"radial": {"nr"}, "axial": {"nz"}, "joint": {"nr", "nz"},
              "time": {"rtol", "atol_t", "atol_c"}, "newton": {"newton_tol", "linear_tol"},
              "dense": {"hmax", "h0"}, "event": {"hmax", "h0"}}[category]
    if category != "event" and any("refinement" in m for m in manifests):
        raise RefinementError("CATEGORY_INVALID: locally refined suffix is not a global grid/time/Newton/hmax run")
    initial = configs[0].as_dict()
    for cfg in configs[1:]:
        for name, value in cfg.as_dict().items():
            if name not in varied | RESOURCE_FIELDS and value != initial[name]:
                raise RefinementError(f"CATEGORY_INVALID: {category} also changes {name}")
    for a, b in zip(configs[:-1], configs[1:]):
        names = varied - ({"h0"} if category == "dense" else set())
        if category == "event":
            continue
        factor = 2. if category in {"radial", "axial", "joint"} else (.1 if category in {"time", "newton"} else .5)
        for name in names:
            if not np.isclose(getattr(b, name), factor*getattr(a, name), rtol=2e-13, atol=0):
                raise RefinementError(f"CATEGORY_INVALID: {category} requires prescribed ratio for {name}")
    if category == "event":
        widths = []
        for cfg, m in zip(configs, manifests):
            r = m.get("refinement", {})
            if r.get("method") != "ACCEPTED_CHECKPOINT_REINTEGRATION" or r.get("new_accepted_steps", 0) < 1:
                raise RefinementError("CATEGORY_INVALID: event evidence requires real reintegration")
            if "phase_diagnostics" in r:
                local = [p for p in r["phase_diagnostics"] if p.get("phase") == "LOCAL_REINTEGRATION"]
                if (len(local) != 1 or local[0].get("status") != "COMPLETED_INTERVAL" or
                        r.get("local_accepted_steps", 0) < 1 or
                        local[0].get("accepted_steps_committed", 0) != r["local_accepted_steps"]):
                    raise RefinementError("CATEGORY_INVALID: bridge alone is not local event reintegration")
                hmax = r.get("local_hmax")
                actual_hmax = local[0].get("max_h")
                end = local[0].get("end")
                if (any(not isinstance(v, (int, float)) or not np.isfinite(v) for v in (hmax, actual_hmax, end)) or
                        hmax <= 0 or actual_hmax <= 0 or
                        hmax != cfg.hmax or local[0].get("hmax") != cfg.hmax or
                        actual_hmax > hmax + 64*abs(np.spacing(max(1., abs(end))))):
                    raise RefinementError("CATEGORY_INVALID: local phase exceeds its recorded event hmax")
            widths.append(r.get("target_width"))
        if any(w is None or w <= 0 or w > .01 for w in widths) or any(not np.isclose(b, a/2) for a, b in zip(widths[:-1], widths[1:])):
            raise RefinementError("CATEGORY_INVALID: event widths must halve through at least three levels")


def build_error_evidence(reference_run, category_runs, out_path=None, *, coverage_end=None,
                         data_dir=None, comparison_options=None, system_factory=None):
    """Aggregate measured >=3-level evidence; unknown values remain unknown.

    Required B categories: radial/time/newton/dense/event. C additionally
    requires axial/joint and sums all three spatial estimates. The last two
    adjacent differences give 2*max(delta1,delta2), with no assumed order.
    """
    ref, config, manifest, system, trajectory = _load_run(reference_run, data_dir, system_factory)
    needed = {"radial", "time", "newton", "dense", "event"}
    if config.route == "C":
        needed |= {"axial", "joint"}
    options = dict(comparison_options or {})
    options.update(data_dir=data_dir, system_factory=system_factory)
    end = trajectory.end_time if coverage_end is None else float(coverage_end)
    evidence = {"status": "ERROR_BUDGET_UNRESOLVED", "checks_passed": False, "refinement_verified": False,
                "eT": None, "eC": None, "eG": None, "et_ref": None, "et": None,
                "coverage_end": end, "run_ids": [], "category_runs": {k: [str(Path(x).resolve()) for x in v] for k, v in category_runs.items()},
                "reference_run": str(ref), "config_fingerprint": config.fingerprint,
                "trajectory_fingerprint": fingerprint(trajectory.index), "categories": {}, "issues": [],
                "source_identity": manifest["identity"], "numerical_source_sha256": fingerprint(_core_hashes(manifest)),
                "empirical_not_bound": True, "stage07": "NOT_RUN"}
    if end > trajectory.end_time:
        evidence["issues"].append("reference trajectory does not cover requested interval")
    for category in sorted(needed):
        paths = category_runs.get(category, [])
        if len(paths) < 3:
            evidence["issues"].append(category + ": at least three real levels required")
            continue
        try:
            loaded = [_load_run(p, data_dir, system_factory) for p in paths]
            configs, manifests = [v[1] for v in loaded], [v[2] for v in loaded]
            _validate_category(category, configs, manifests)
            for p, c, m, s, tr in loaded:
                if m["identity"]["input"] != manifest["identity"]["input"] or _core_hashes(m) != _core_hashes(manifest):
                    raise RefinementError("category/reference source or input mismatch")
                if any(getattr(c, k) != getattr(config, k) for k in REFERENCE_FIELDS) or tr.start_time != 0 or tr.end_time < end:
                    raise RefinementError("category/reference physical/backend definition or coverage mismatch")
                if category in {"time", "newton", "dense", "event"} and (c.nr, c.nz) != (config.nr, config.nz):
                    raise RefinementError("nonspatial comparison not performed on reference grid")
                if c.test_case is not None or m.get("refinement", {}).get("injected_test_system"):
                    raise RefinementError("TEST_ONLY trajectory cannot certify formal drying")
            if category in {"radial", "joint"} and configs[-1].nr != config.nr:
                raise RefinementError("finest radial level does not match reference Nr")
            if category in {"axial", "joint"} and configs[-1].nz != config.nz:
                raise RefinementError("finest axial level does not match reference Nz")
            comparisons = [compare_runs(a, b, coverage_end=end, **options) for a, b in zip(paths[:-1], paths[1:])]
            if any(not c["resolved"] for c in comparisons):
                raise RefinementError("adjacent time/spatial comparison unresolved")
            last = comparisons[-2:]
            d = np.array([[x["differences"][name] for name in METRICS] for x in last])
            floor = 64 * np.finfo(float).eps * np.array([324., 2.55, 2.55])
            descending = np.all((d[1] < d[0]) | (np.maximum(d[0], d[1]) <= floor))
            if category in {"radial", "axial", "joint"} and not descending:
                raise RefinementError("SPATIAL_CONVERGENCE_UNRESOLVED: last adjacent differences did not decrease")
            dt = [x.get("event_difference") for x in last]
            estimates = dict(zip(("eT", "eC", "eG"), map(float, 2*np.max(d, axis=0))))
            estimates["et_ref"] = 2*max(dt) if all(v is not None for v in dt) else None
            entry = {"status": "MEASURED", "comparisons": comparisons, "estimates": estimates,
                     "levels": len(paths), "last_differences_descend": bool(descending)}
            if category == "dense":
                entry["hmax_active"] = [(_read(Path(p)/"metrics.json").get("stats", {}).get("max_h", 0.) >= .999999*c.hmax)
                                         for p, c in zip(paths, configs)]
            evidence["categories"][category] = entry
            evidence["run_ids"].extend(Path(p).name for p in paths)
            if estimates["et_ref"] is None:
                evidence["issues"].append(category + ": event differences lack complete earliest/retention evidence")
        except (ValueError, FileNotFoundError, KeyError) as exc:
            evidence["issues"].append(category + ": " + str(exc))
    if needed.issubset(evidence["categories"]):
        for name in ("eT", "eC", "eG"):
            evidence[name] = float(sum(v["estimates"][name] for v in evidence["categories"].values()))
        values = [v["estimates"]["et_ref"] for v in evidence["categories"].values()]
        evidence["et_ref"] = float(sum(values)) if all(x is not None for x in values) else None
        evidence["et"] = evidence["et_ref"]
        # Rebinding to a report-preparation trajectory requires measuring its
        # difference from the finest event trajectory rather than changing a hash.
        finest = Path(category_runs["event"][-1]).resolve()
        if finest != ref:
            try:
                delta = compare_runs(finest, ref, coverage_end=end, **options)
                evidence["protocol_transition"] = delta
                if not delta["resolved"] or delta.get("event_difference") is None:
                    raise RefinementError("final protocol transition comparison unresolved")
                for field, name in zip(("eT", "eC", "eG"), METRICS):
                    evidence[field] += 2*delta["differences"][name]
                if evidence["et_ref"] is not None:
                    evidence["et_ref"] += 2*delta["event_difference"]
                    evidence["et"] = evidence["et_ref"]
            except (ValueError, FileNotFoundError) as exc:
                evidence["issues"].append(str(exc))
        fields_ok = evidence["eT"] <= .05 and max(evidence["eC"], evidence["eG"]) <= .0005
        if not fields_ok:
            evidence["issues"].append("prescribed field error budget exceeded, including initial surface layer")
        evidence["refinement_verified"] = not evidence["issues"]
        evidence["checks_passed"] = not evidence["issues"] and fields_ok
        if evidence["checks_passed"]:
            evidence["status"] = "FIELD_ERROR_EVIDENCE_READY"
    evidence["run_ids"] = sorted(set(evidence["run_ids"] + [ref.name]))
    evidence["evidence_fingerprint"] = fingerprint(evidence)
    if out_path is not None:
        atomic_json(out_path, evidence)
    return evidence


def prepare_strict_report(run_dir, error_evidence, out_dir, *, width=.0025,
                          data_dir=None, wall_seconds=300., system_factory=None):
    """Run threshold shifts and a genuine accepted 0.36-s report endpoint.

    The returned candidate is deliberately PROVISIONAL: preparation changes
    the trajectory. Rebuild error evidence against ``run_dir`` in the result,
    then call ``certify_strict_report``. If the updated margin changes, prepare
    again; no old-trajectory evidence is silently promoted to current evidence.
    """
    _, cfg, manifest, system, tr = _load_run(run_dir, data_dir, system_factory, True)
    root = Path(out_dir).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    result = {"status": "ERROR_BUDGET_UNRESOLVED", "run_dir": str(Path(run_dir).resolve()), "issues": []}
    ev = error_evidence
    if (not ev.get("checks_passed") or not ev.get("refinement_verified") or
            ev.get("trajectory_fingerprint") != fingerprint(tr.index) or
            ev.get("config_fingerprint") != cfg.fingerprint):
        result["issues"].append("current complete field/error evidence is required before choosing strict margin")
        atomic_json(root / "candidate.json", result); return result
    eta = max(2*max(ev["eC"], ev["eG"]), 64*np.finfo(float).eps)
    if .15 - eta <= max(float(np.max(system.inputs.water)), system.inputs.tail_water):
        result["issues"].append("tightened threshold violates environment convexity condition")
        atomic_json(root / "candidate.json", result); return result
    current = Path(run_dir).resolve()
    records = []
    started = time.perf_counter()
    # Each refinement truncates after its event. Integrate back to the original
    # covered endpoint before looking for a later threshold when necessary.
    original_end = tr.end_time
    for label, threshold in (("plus", .15 + eta), ("nominal", .15), ("minus", .15 - eta)):
        _, cc, mm, ss, tt = _load_run(current, data_dir, system_factory, True)
        if tt.end_time < original_end:
            continuation = _reintegrate_suffix(current, root / (label + "_continue"), before=tt.end_time,
                        until=original_end, data_dir=data_dir, system_factory=system_factory,
                        wall_seconds=max(.01, wall_seconds-(time.perf_counter()-started)))
            if continuation["status"] != "COMPLETED_INTERVAL":
                result.update(status=continuation["status"] if continuation["status"] in HARD_FAILURES else "REPORT_TIME_UNRESOLVED",
                              run_dir=continuation["run_dir"])
                result["issues"].append("same-solution coverage continuation failed"); break
            current = Path(continuation["run_dir"])
        rr = refine_event(current, root / label, threshold=threshold, width=width,
                          data_dir=data_dir, system_factory=system_factory,
                          wall_seconds=max(.01, wall_seconds-(time.perf_counter()-started)))
        records.append(rr)
        current = Path(rr["run_dir"])
        if rr["status"] != "EVENT_BRACKET_REFINED":
            result.update(status=rr["status"] if rr["status"] in HARD_FAILURES else "EVENT_UNRESOLVED", run_dir=str(current))
            result["issues"].append(label + " threshold lacks a refined event"); break
    else:
        _, cc, mm, ss, tt = _load_run(current, data_dir, system_factory, True)
        nominal, plus, minus = (scan_events(ss, tt, threshold=x) for x in (.15, .15+eta, .15-eta))
        if any(x["status"] != "PROVISIONAL_EVENT" or x["tR"]-x["tL"] > width for x in (nominal, plus, minus)):
            result["issues"].append("same-final-trajectory threshold rescans are not all refined")
        else:
            eligible = nominal["tR"] if reconstruct(ss, nominal["tR"], tt.at(nominal["tR"])).max_C + eta < .15 else minus["tR"]
            report = upward_report_time(eligible)
            if report > cfg.tmax:
                result.update(status="REPORT_TIME_UNRESOLVED")
                result["issues"].append("required display gridpoint exceeds finite input/run horizon")
            else:
                before = max(0., min(eligible, report) - width)
                ready = _reintegrate_suffix(current, root / "report_endpoint", before=before,
                            until=max(report, tt.end_time), forced_nodes=[report], hmax=width/2,
                            width=width, threshold=.15-eta, data_dir=data_dir, system_factory=system_factory,
                            wall_seconds=max(.01, wall_seconds-(time.perf_counter()-started)))
                current = Path(ready["run_dir"])
                if ready["status"] == "COMPLETED_INTERVAL":
                    _, cc, mm, ss, tt = _load_run(current, data_dir, system_factory, True)
                    nominal, plus, minus = (scan_events(ss, tt, threshold=x) for x in (.15, .15+eta, .15-eta))
                    valid = all(x["status"] == "PROVISIONAL_EVENT" and x["earliest_verified"] and
                                x["retention_verified"] and x["tR"]-x["tL"] <= width for x in (nominal, plus, minus))
                    eligible = nominal["tR"] if valid and reconstruct(ss, nominal["tR"], tt.at(nominal["tR"])).max_C + eta < .15 else minus.get("tR")
                    if valid and eligible is not None and upward_report_time(eligible) == report and reconstruct(ss, report, tt.at(report)).max_C + eta < .15:
                        result.update(status="PROVISIONAL_EVENT", run_dir=str(current), eta_strict=eta,
                            t_hat=nominal["t_hat"], tL=nominal["tL"], tR=nominal["tR"],
                            t_plus=plus["t_hat"], t_minus=minus["t_hat"], t_eligible=eligible,
                            t_report=report, earliest_verified=True, retention_verified=True,
                            config_fingerprint=cc.fingerprint, trajectory_fingerprint=fingerprint(tt.index),
                            preparation_evidence_fingerprint=ev.get("evidence_fingerprint"),
                            error_evidence_refresh_required=True, threshold_records={"nominal": nominal, "plus": plus, "minus": minus})
                    else:
                        result.update(status="REPORT_TIME_UNRESOLVED", run_dir=str(current))
                        result["issues"].append("report reintegration changed the candidate; repeat refinement/evidence loop")
                else:
                    result.update(status=ready["status"] if ready["status"] in HARD_FAILURES else "REPORT_TIME_UNRESOLVED", run_dir=str(current))
                    result["issues"].append("report endpoint integration did not complete")
    result["refinements"] = records
    result["exit_code"] = 1 if result["status"] in HARD_FAILURES else 0 if result["status"] == "PROVISIONAL_EVENT" else 2
    atomic_json(root / "candidate.json", result)
    return result


def certify_strict_report(run_dir, error_evidence, candidate, out_path=None, *,
                          data_dir=None, reference_critical_time=None, system_factory=None):
    """Issue current numeric evidence certification only after all real checks.

    This certifies the specified reconstructed numerical model with empirical
    refinement allowances. It is neither Stage07 nor a true-PDE/physical bound.
    """
    result = deepcopy(candidate)
    result.update(status="ERROR_BUDGET_UNRESOLVED", stage07="NOT_RUN")
    result.setdefault("issues", [])
    try:
        path, cfg, manifest, system, trajectory = _load_run(run_dir, data_dir, system_factory, True)
        if cfg.test_case is not None or system_factory is not None or manifest.get("refinement", {}).get("injected_test_system"):
            raise RefinementError("TEST_ONLY/injected equations cannot receive formal drying certificate")
        _require_cuda_evidence(cfg, manifest)
        if candidate.get("status") != "PROVISIONAL_EVENT":
            raise RefinementError("prepared candidate is unresolved")
        if candidate.get("trajectory_fingerprint") != fingerprint(trajectory.index) or candidate.get("config_fingerprint") != cfg.fingerprint:
            raise RefinementError("prepared candidate identity differs from final trajectory")
        diagnostics = _read(path/"diagnostics.json")
        if (not diagnostics.get("checks_passed") or
            diagnostics.get("status") != "CURRENT_CUMULATIVE_BALANCES_CHECKED" or
            diagnostics.get("trajectory_fingerprint") != fingerprint(trajectory.index) or
            diagnostics.get("config_fingerprint") != cfg.fingerprint or
            diagnostics.get("covered_until", -1) < candidate["t_report"]):
            raise RefinementError("current full-path cumulative balances must be independently recomputed")
        e = deepcopy(error_evidence)
        expected_hash = e.pop("evidence_fingerprint", None)
        if expected_hash != fingerprint(e):
            raise RefinementError("error evidence fingerprint mismatch")
        if not e.get("checks_passed") or not e.get("refinement_verified"):
            raise RefinementError("measured error categories/budgets remain unresolved")
        if e.get("trajectory_fingerprint") != fingerprint(trajectory.index) or e.get("config_fingerprint") != cfg.fingerprint:
            raise RefinementError("error evidence must be recomputed for final trajectory")
        required = {"radial", "time", "newton", "dense", "event"}
        if cfg.route == "C":
            required |= {"axial", "joint"}
        if not required.issubset(e.get("categories", {})) or not required.issubset(e.get("category_runs", {})):
            raise RefinementError("all real three-level error categories are required; flags alone are insufficient")
        expected_estimates = {name: 0. for name in ("eT", "eC", "eG", "et_ref")}
        for category in sorted(required):
            paths = e["category_runs"][category]
            proof = e["categories"][category]
            if len(paths) < 3 or proof.get("levels") != len(paths) or len(proof.get("comparisons", [])) != len(paths)-1:
                raise RefinementError("missing measured three-level comparison: " + category)
            actual = [_load_run(p, data_dir, None, True) for p in paths]
            _validate_category(category, [a[1] for a in actual], [a[2] for a in actual])
            for _, category_cfg, category_manifest, _, category_trajectory in actual:
                _require_cuda_evidence(category_cfg, category_manifest)
                if (any(getattr(category_cfg, k) != getattr(cfg, k) for k in REFERENCE_FIELDS) or
                    category_manifest["identity"]["input"] != manifest["identity"]["input"] or
                    _core_hashes(category_manifest) != _core_hashes(manifest) or
                    category_trajectory.start_time != 0 or category_trajectory.end_time < candidate["t_report"] or
                    category_manifest.get("refinement", {}).get("injected_test_system")):
                    raise RefinementError("category/reference physical/backend/source/coverage mismatch")
            for i, comparison in enumerate(proof["comparisons"]):
                if (not comparison.get("resolved") or comparison.get("coverage_end", -1) < candidate["t_report"] or
                    comparison.get("trajectory_fingerprints") != [fingerprint(actual[i][4].index), fingerprint(actual[i+1][4].index)] or
                    comparison.get("config_fingerprints") != [actual[i][1].fingerprint, actual[i+1][1].fingerprint]):
                    raise RefinementError("comparison proof is incomplete/stale: " + category)
            last = proof["comparisons"][-2:]
            for field, metric in zip(("eT", "eC", "eG"), METRICS):
                expected_estimates[field] += 2*max(float(c["differences"][metric]) for c in last)
            if any(c.get("event_difference") is None for c in last):
                raise RefinementError("missing measured event difference: " + category)
            expected_estimates["et_ref"] += 2*max(float(c["event_difference"]) for c in last)
        if "protocol_transition" in e:
            transition = e["protocol_transition"]
            finest = _load_run(e["category_runs"]["event"][-1], data_dir, None, True)
            if (not transition.get("resolved") or transition.get("coverage_end", -1) < candidate["t_report"] or
                transition.get("trajectory_fingerprints") != [fingerprint(finest[4].index), fingerprint(trajectory.index)]):
                raise RefinementError("final protocol-transition proof is incomplete/stale")
            for field, metric in zip(("eT", "eC", "eG"), METRICS):
                expected_estimates[field] += 2*transition["differences"][metric]
            expected_estimates["et_ref"] += 2*transition["event_difference"]
        for field, expected in expected_estimates.items():
            if e.get(field) is None or not np.isclose(e[field], expected, rtol=2e-13, atol=1e-18):
                raise RefinementError("error aggregation differs from measured comparisons: " + field)
        e["source_evidence_fingerprint"] = expected_hash
        eta = max(2*max(e["eC"], e["eG"]), 64*np.finfo(float).eps)
        if eta != candidate.get("eta_strict"):
            raise RefinementError("refreshed field evidence changed strict margin; repeat preparation")
        threshold_records = [scan_events(system, trajectory, x) for x in (.15, .15+eta, .15-eta)]
        nominal, plus, minus = threshold_records
        if not all(x["status"] == "PROVISIONAL_EVENT" and x["earliest_verified"] and x["retention_verified"] and x["tR"]-x["tL"] <= .01 for x in threshold_records):
            raise RefinementError("same final trajectory has unresolved threshold event or retention")
        for name, value in (("t_hat", nominal["t_hat"]), ("tL", nominal["tL"]), ("tR", nominal["tR"]),
                            ("t_plus", plus["t_hat"]), ("t_minus", minus["t_hat"])):
            if candidate.get(name) != value:
                raise RefinementError("prepared event changed on final trajectory: " + name)
        report = candidate["t_report"]
        _accepted_state(trajectory, report)  # A genuine accepted display endpoint.
        level = max(nominal["t_hat"]-plus["t_hat"], minus["t_hat"]-nominal["t_hat"])
        if e.get("et_ref") is None:
            raise RefinementError("missing event refinement time estimate")
        e["et"] = max(e["et_ref"], level) + nominal["tR"]-nominal["tL"]
        budget = .1*min(.01*nominal["t_hat"], 1800.)
        if candidate["t_eligible"]-nominal["t_hat"] > budget:
            raise RefinementError("strict-margin waiting exceeds own critical-time precheck budget")
        if reference_critical_time is not None:
            if not np.isfinite(reference_critical_time) or reference_critical_time <= 0:
                raise RefinementError("invalid common C reference critical time")
            budget = min(budget, .1*min(.01*reference_critical_time, 1800.))
        if e["et"] > budget:
            raise RefinementError("conditioned critical-time error budget exceeded")
        result.update(status="DRYING_COMPLETE", error_evidence=e, et_ref=e["et_ref"],
                      level_time_uncertainty=level, report_delay=report-nominal["t_hat"],
                      rounding_delay=report-candidate["t_eligible"],
                      margin_waiting=candidate["t_eligible"]-nominal["t_hat"],
                      error_evidence_refresh_required=False,
                      common_reference_checked=reference_critical_time is not None,
                      numeric_certificate_scope="RECONSTRUCTED_NUMERICAL_MODEL_WITH_EMPIRICAL_ALLOWANCE")
        result["verified_report"] = verify_report(system, trajectory, result)
    except (ValueError, FileNotFoundError, KeyError, TypeError) as exc:
        result["status"] = "ERROR_BUDGET_UNRESOLVED"
        result["issues"].append(str(exc))
    if out_path is not None:
        atomic_json(out_path, result)
    return result
