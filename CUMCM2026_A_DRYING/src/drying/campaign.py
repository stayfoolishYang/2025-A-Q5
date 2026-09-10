"""Bounded, resumable server campaign. Importing this file starts no work.

One owner writes a campaign, each numerical task has its own immutable identity,
and subprocess timeouts leave recorded checkpoints available for an explicit
resume. This is Stage06 execution automation, never a Stage07/model-freeze gate.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback


ROOT = Path(__file__).resolve().parents[2]
HARD = {"GPU_BACKEND_FAILURE", "NUMERICAL_FAILURE", "EXECUTION_EXCEPTION", "MEMORY_BUDGET_REACHED"}
COMPLETE = {"Q1_WINDOW_COMPLETE", "TIME_LIMIT_REACHED", "INPUT_HORIZON_REACHED", "COMPLETED_INTERVAL"}


class CampaignDeadline(RuntimeError):
    pass


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)


def _digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _exclusive_lock(root):
    """OS locks release on interruption; no unsafe PID killing/stale-lock delete."""
    path = Path(root) / ".campaign.lock"
    with path.open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0"); stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("CAMPAIGN_ALREADY_RUNNING: output directory has another owner") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _artifact_inventory(root):
    """Hash actual output bytes, including accepted blocks, without loading arrays."""
    root = Path(root)
    return {p.relative_to(root).as_posix(): _digest(p) for p in sorted(root.rglob("*"))
            if p.is_file() and not p.name.endswith(".tmp")}


def _artifacts_match(root, inventory):
    return all((Path(root) / p).is_file() and _digest(Path(root) / p) == digest
               for p, digest in inventory.items())


def _retryable(result):
    status = str(result.get("status", ""))
    return (result.get("exit_code", 0) != 0 or status in HARD or
            any(word in status for word in ("UNRESOLVED", "BUDGET", "FAILED", "FAILURE")))


class ActionStore:
    """Transactional analytical actions with fresh directories after interruption."""
    def __init__(self, root, identity, deadline):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "actions.json"
        self.identity = identity; self.deadline = deadline
        self.dependency = _fingerprint(identity)
        self.state = _read(self.path) if self.path.exists() else {"identity": identity, "actions": {}}
        if self.state["identity"] != identity:
            raise ValueError("ACTION_IDENTITY_CHANGED: use a new analysis directory")

    def __call__(self, key, function):
        if time.time() >= self.deadline:
            raise CampaignDeadline("CAMPAIGN_BUDGET_REACHED before " + str(key))
        token = re.sub(r"[^A-Za-z0-9_.-]", "_", str(key))[:70] + "_" + _fingerprint(str(key))[:10]
        history = self.state["actions"].setdefault(str(key), [])
        if history:
            last = history[-1]
            if (last.get("status") == "RECORDED" and last.get("dependency") == self.dependency and
                    not _retryable(last["result"]) and
                    _artifacts_match(last["directory"], last["artifacts"])):
                self.dependency = _fingerprint(last)
                return last["result"]
        directory = self.root / token / f"attempt_{len(history) + 1:03d}"
        directory.mkdir(parents=True, exist_ok=False)
        record = {"status": "RUNNING", "directory": str(directory), "started_at": _now(),
                  "dependency": self.dependency}
        history.append(record); _write(self.path, self.state)
        try:
            result = function(directory)
            if not isinstance(result, dict):
                raise TypeError("action must return a JSON object")
            _write(directory / "action_result.json", result)
            record.update(status="RECORDED", finished_at=_now(), result=result,
                          artifacts=_artifact_inventory(directory))
            _write(self.path, self.state)
            self.dependency = _fingerprint(record)
            return result
        except BaseException as exc:
            record.update(status="INTERRUPTED_OR_FAILED", finished_at=_now(), error=str(exc))
            _write(self.path, self.state)
            raise


def _identity(expanded):
    from .execution import code_identity
    raw = ROOT / "data/raw"
    manifest = _read(raw / "source_manifest.json")
    actual = {}
    for entry in manifest["files"]:
        path = (raw / entry["relative_path"]).resolve()
        if raw.resolve() not in path.parents or _digest(path) != entry["sha256"]:
            raise ValueError("INPUT_IDENTITY_MISMATCH: " + entry["relative_path"])
        actual[entry["relative_path"]] = entry["sha256"]
    return {"plan": expanded["plan_fingerprint"], "code": code_identity()["sha256"],
            "raw": _fingerprint(actual), "authority": _digest(ROOT / "workspace/04_model_specification.md")}


def _invoke(command, log, timeout, env=None):
    """Only called by the server entrypoint; child output persists on failure."""
    log = Path(log); log.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with log.open("wb") as stream:
        try:
            done = subprocess.run(command, cwd=ROOT, env=env, stdout=stream,
                                  stderr=subprocess.STDOUT, timeout=max(0.01, timeout), check=False)
            return {"returncode": done.returncode, "timed_out": False,
                    "wall_seconds": time.monotonic() - started, "log": str(log)}
        except subprocess.TimeoutExpired:
            return {"returncode": 2, "timed_out": True,
                    "wall_seconds": time.monotonic() - started, "log": str(log)}


def _current_run(run_dir, config):
    """Verify cached solver evidence against the current source and actual blocks."""
    from .config import RunConfig
    from .execution import inspect_run, code_identity
    path = Path(run_dir)
    if not (path / "manifest.json").exists():
        return None
    stored = RunConfig.from_json(path / "config.json")
    if stored.fingerprint != RunConfig.from_dict(config).fingerprint:
        raise ValueError("RUN_CONFIG_CHANGED: " + str(path))
    manifest = _read(path / "manifest.json")
    if manifest["source"]["sha256"] != code_identity()["sha256"]:
        raise ValueError("RUN_SOURCE_CHANGED: " + str(path))
    if not (path / "trajectory/index.json").exists() or not _read(path / "trajectory/index.json").get("chunks"):
        return {"status": "RUNNING", "coverage_end": 0.0}
    _, trajectory, _ = inspect_run(path)
    return {"status": manifest["solver"]["status"], "coverage_end": trajectory.end_time,
            "manifest_sha256": _digest(path / "manifest.json"),
            "trajectory_index_sha256": _digest(path / "trajectory/index.json")}


def _worker(request):
    """Internal subprocess dispatch; never called by import or plan expansion."""
    payload = _read(request)
    output = Path(payload["output"])
    try:
        if payload["operation"] == "preflight":
            from .preflight import run_preflight
            result = run_preflight(output=output, cuda_requests_override=payload["cuda_requests"])
            code = 0 if result["status"] == "PASS" else 1
        elif payload["operation"] == "analysis":
            from .campaign_analysis import analyze_case
            context = payload["context"]
            context["ensure_action"] = ActionStore(payload["action_root"], payload["identity"], payload["deadline"])
            result = analyze_case(context)
            code = result.get("exit_code", 0 if not _retryable(result) else 2)
        elif payload["operation"] == "comparison":
            from .campaign_comparison import compare_campaign_runs
            result = compare_campaign_runs(**payload["arguments"])
            code = 0 if result.get("resolved") else 2
        elif payload["operation"] == "summary":
            from .reporting import summarize_run
            result = summarize_run(payload["run_dir"]); code = 0
        elif payload["operation"] == "pack":
            from .reporting import pack_return
            result = pack_return(payload["root"], payload["zip_path"], full=False); code = 0
        else:
            raise ValueError("unknown internal campaign operation")
    except CampaignDeadline as exc:
        result = {"status": "CAMPAIGN_BUDGET_REACHED", "exit_code": 2, "error": str(exc)}; code = 2
    except Exception as exc:
        result = {"status": "GPU_BACKEND_FAILURE" if type(exc).__name__ == "CudaBackendError" else "EXECUTION_EXCEPTION",
                  "exit_code": 1, "error": str(exc), "traceback": traceback.format_exc()}; code = 1
    result["stage07"] = "NOT_RUN"
    _write(output, result)
    return code


class Campaign:
    def __init__(self, expanded, output, resume):
        self.expanded = expanded; self.root = Path(output).resolve(); self.resume = resume
        self.budget = expanded["budget"]; self.deadline = time.time() + self.budget["session_wall_seconds"]
        self.path = self.root / "campaign_state.json"
        self.identity = _identity(expanded)
        if self.path.exists():
            if not resume:
                raise FileExistsError("campaign exists; use --resume or a new --out")
            self.state = _read(self.path)
            if self.state["identity"] != self.identity:
                raise ValueError("CAMPAIGN_IDENTITY_CHANGED: plan/source/input differs; use a new campaign")
        else:
            if resume:
                raise FileNotFoundError("--resume requires campaign_state.json")
            self.state = {"identity": self.identity, "created_at": _now(), "invocations": [],
                          "runs": {}, "actions": {}, "stage07": "NOT_RUN", "stage08": "NOT_RUN"}
        self.invocation = len(self.state["invocations"]) + 1
        self.state["invocations"].append({"started_at": _now(), "status": "RUNNING", "session_budget": self.budget["session_wall_seconds"]})
        self.logs = self.root / "logs" / f"invocation_{self.invocation:03d}"
        self.logs.mkdir(parents=True, exist_ok=True)
        self.save()
        _write(self.root / "expanded_plan.json", expanded)

    def save(self):
        _write(self.path, self.state)

    def remaining(self):
        remaining = self.deadline - time.time()
        if remaining <= 0:
            raise CampaignDeadline("CAMPAIGN_BUDGET_REACHED; resume preserves completed tasks")
        return remaining

    def action(self, key, payload, timeout, cache=True, finalization=False):
        history = self.state["actions"].setdefault(key, [])
        if cache and history:
            last = history[-1]
            if (last.get("finished") and last.get("returncode") == 0 and
                    _artifacts_match(last["directory"], last["artifacts"])):
                return _read(last["output"])
        directory = self.root / "operations" / key / f"attempt_{len(history) + 1:03d}"
        directory.mkdir(parents=True, exist_ok=False)
        output = directory / "result.json"
        request = dict(payload, output=str(output), deadline=self.deadline)
        _write(directory / "request.json", request)
        entry = {"directory": str(directory), "output": str(output), "started_at": _now(), "finished": False}
        history.append(entry); self.save()
        process = _invoke([sys.executable, "-m", "drying", "_campaign-worker", "--request", str(directory / "request.json")],
                          directory / "worker.log", min(timeout, 300.0) if finalization else min(timeout, self.remaining()))
        result = _read(output) if output.exists() else {"status": "ACTION_TIMEOUT" if process["timed_out"] else "EXECUTION_EXCEPTION",
                                                       "exit_code": 2 if process["timed_out"] else 1}
        if (not process["timed_out"] and process["returncode"] not in (0, 2) and
                result.get("status") in HARD | {"FAIL", "ANALYSIS_FAILED"}):
            result = dict(result, exit_code=1, worker_returncode=process["returncode"])
        elif process["timed_out"] or process["returncode"] not in (0, 2):
            result = {"status": "ACTION_TIMEOUT" if process["timed_out"] else "EXECUTION_EXCEPTION",
                      "exit_code": 2 if process["timed_out"] else 1, "partial_record": result,
                      "error": "Worker did not finish successfully; see " + str(directory / "worker.log")}
        elif process["returncode"] == 2 and result.get("exit_code", 0) == 0:
            result = {"status": "ACTION_UNRESOLVED", "exit_code": 2, "partial_record": result}
        _write(output, result)
        entry.update(process, finished=True, finished_at=_now(), artifacts=_artifact_inventory(directory))
        self.save()
        if result.get("status") in HARD:
            raise RuntimeError(result["status"] + ": " + str(result.get("error", "see " + str(directory))))
        return result

    def preflight(self):
        requests = [{"cuda_device": self.expanded["hardware"]["cuda_device"],
                     "gpu_memory_mb": self.expanded["hardware"]["gpu_memory_mb"]}]
        result = self.action("preflight", {"operation": "preflight", "cuda_requests": requests},
                             self.budget["tests_timeout_seconds"], cache=False)
        if result.get("status") != "PASS":
            raise RuntimeError("PREFLIGHT_FAILED; no numerical campaign task started")
        xml = self.logs / "server_tests.xml"
        env = dict(os.environ, DRYING_REQUIRE_CUDA="1", DRYING_CUDA_TEST_REQUESTS=json.dumps(requests))
        process = _invoke([sys.executable, "-m", "pytest", "-q", "--junitxml=" + str(xml)],
                          self.logs / "server_tests.log", min(self.budget["tests_timeout_seconds"], self.remaining()), env)
        self.state["invocations"][-1]["tests"] = dict(process, xml=str(xml)); self.save()
        if process["returncode"] != 0:
            raise RuntimeError("GPU_TESTS_FAILED_OR_TIMED_OUT; no numerical campaign task started")

    def run_one(self, specification):
        key = specification["run_key"]; config = specification["config"]
        path = self.root / "runs" / key
        cfg_path = self.root / "run_configs" / (key + ".json")
        if cfg_path.exists() and _read(cfg_path) != config:
            raise ValueError("GENERATED_CONFIG_CHANGED: " + key)
        _write(cfg_path, config)
        record = self.state["runs"].setdefault(key, {"directory": str(path), "attempts": []})
        path = Path(record["directory"])
        target = config.get("case_end_time") or config["tmax"]
        for _ in range(self.budget["max_run_attempts"]):
            current = _current_run(path, config) if path.exists() else None
            if current and current["status"] in COMPLETE and current["coverage_end"] >= target:
                record.update(current, complete=True); self.save(); return
            if current and current["status"] in HARD:
                raise RuntimeError("RUN_HARD_FAILURE: " + key + " " + current["status"])
            if path.exists() and not (path / "checkpoint.json").exists():
                # Crash during initial setup has nothing safely resumable. Keep
                # that directory intact and start a fresh, identified attempt.
                record.setdefault("orphan_directories", []).append(str(path))
                number = len(record["attempts"]) + 1
                path = self.root / "runs" / (key + f"_fresh_{number:03d}")
                while path.exists():
                    number += 1
                    path = self.root / "runs" / (key + f"_fresh_{number:03d}")
                record.update(directory=str(path), status="INITIAL_SETUP_RETRY", complete=False)
                self.save()
            command = [sys.executable, "-m", "drying", "run", "--config", str(cfg_path), "--out", str(path)]
            if path.exists():
                command.append("--resume")
            number = len(record["attempts"]) + 1
            attempt = {"started_at": _now(), "status": "RUNNING", "invocation": self.invocation}
            record["attempts"].append(attempt); self.save()
            print(f"[full-run] {key} attempt {number} -> {target:g} s", flush=True)
            result = _invoke(command, self.logs / f"{key}_{number:03d}.log", min(config["wall_seconds"] + 120, self.remaining()))
            current = _current_run(path, config) if path.exists() else None
            attempt.update(result, finished_at=_now(), status=(current or {}).get("status", "NO_RUN_RECORD"))
            record.update(current or {}, complete=bool(current and current["status"] in COMPLETE and current["coverage_end"] >= target))
            if result["timed_out"] or result["returncode"] != 0:
                record["complete"] = False
            self.save()
            if (current and current["status"] in HARD) or (result["returncode"] not in (0, 2) and not result["timed_out"]):
                raise RuntimeError("RUN_FAILED: " + key + "; see " + result["log"])
            if record["complete"]:
                return
            if result["timed_out"]:
                record.update(status="RUN_PROCESS_TIMEOUT", complete=False); self.save(); return
            self.remaining()
        record.setdefault("status", "RUN_BUDGET_UNRESOLVED"); record["complete"] = False; self.save()

    def run_paths(self):
        return {key: value["directory"] for key, value in self.state["runs"].items() if value.get("complete")}

    def summarize(self):
        # Partial observations are useful evidence too. This writes observation
        # files only; solver identity/manifests/accepted trajectories stay intact.
        summaries = {}
        for key, record in self.state["runs"].items():
            if not record.get("coverage_end", 0) > 0:
                continue
            dependency = _fingerprint({k: record.get(k) for k in
                ("manifest_sha256", "trajectory_index_sha256", "coverage_end")})
            summaries[key] = self.action("summary_" + key + "_" + dependency[:16],
                {"operation": "summary", "run_dir": record["directory"]},
                self.budget["postprocess_wall_seconds"], cache=False)
            self.state["observations"] = summaries; self.save()

    def analyze(self):
        paths = self.run_paths()
        source_states = {key: {k: value.get(k) for k in ("manifest_sha256", "trajectory_index_sha256", "complete")}
                         for key, value in self.state["runs"].items()}
        dependency = _fingerprint(source_states)
        self.state["analysis_dependency"] = dependency
        limits = {"comparison_wall_seconds": self.budget["postprocess_wall_seconds"],
                  "comparison_max_points": self.budget["comparison_max_points"],
                  "comparison_time_levels": self.budget["comparison_time_levels"],
                  "event_wall_seconds": self.budget["event_wall_seconds"],
                  "event_max_levels": self.budget["event_max_levels"],
                  "report_wall_seconds": self.budget["event_wall_seconds"],
                  "closure_rounds": self.budget["report_rounds"],
                  "balances_wall_seconds": self.budget["postprocess_wall_seconds"]}
        outputs = {}
        for name in ("Q1", "C1_Q23", "C1_Q4", "B_Q23", "B_Q4"):
            case = self.expanded["cases"][name]
            required = {case["reference_run"]} | {x for values in case["categories"].values() for x in values}
            missing = sorted(required - paths.keys())
            if missing:
                outputs[name] = {"status": "RUN_COVERAGE_UNRESOLVED", "exit_code": 2, "missing_runs": missing}; continue
            context = {"case_id": name, "reference_run": paths[case["reference_run"]],
                       "category_runs": {k: [paths[x] for x in values] for k, values in case["categories"].items()},
                       "data_dir": str(ROOT / "data/raw"), "limits": limits, "export_requested": not name.startswith("C1_")}
            counterpart = "C1_" + name[2:] if name.startswith("B_") else None
            reference_certificate = outputs.get(counterpart, {}).get("certificate", {})
            if isinstance(reference_certificate, dict) and reference_certificate.get("status") == "DRYING_COMPLETE":
                context["reference_critical_time"] = reference_certificate["t_hat"]
            analysis_identity = dict(self.identity, runs=dependency, context=_fingerprint(context))
            analysis_key = _fingerprint(analysis_identity)[:16]
            payload = {"operation": "analysis", "context": context, "identity": analysis_identity,
                       "action_root": str(self.root / "analysis" / analysis_key / name)}
            outputs[name] = self.action("analysis_" + name + "_" + analysis_key, payload, self.remaining(), cache=False)
            self.state["case_results"] = outputs; self.save()
        self.state["case_results"] = outputs; self.save()
        comparisons = {}
        for index, item in enumerate(self.expanded["comparisons"]):
            key = item.get("comparison_id", f"comparison_{index:03d}")
            if item["left"] not in paths or item["right"] not in paths:
                comparisons[key] = {"status": "RUN_COVERAGE_UNRESOLVED", "resolved": False, "plan": item}; continue
            arguments = {"left_run": paths[item["left"]], "right_run": paths[item["right"]],
                         "wall_seconds": self.budget["postprocess_wall_seconds"],
                         "max_time_points": self.budget["comparison_max_points"],
                         "max_time_refinements": self.budget["comparison_time_levels"]}
            result = self.action("comparison_" + str(index) + "_" + dependency[:16],
                                 {"operation": "comparison", "arguments": arguments},
                                 self.budget["postprocess_wall_seconds"] + 120)
            comparisons[key] = dict(result, plan=item)
            self.state["comparisons"] = comparisons; self.save()
        self.state["comparisons"] = comparisons; self.save()

    def finish(self, failure=None):
        complete_runs = all(self.state["runs"].get(r["run_key"], {}).get("complete") for r in self.expanded["runs"])
        cases = self.state.get("case_results", {})
        case_ok = (cases.get("Q1", {}).get("status") == "Q1_CANDIDATE_EXPORTED" and
                   all(cases.get(k, {}).get("status") == "DRYING_COMPLETE" for k in ("B_Q23", "B_Q4")) and
                   all(cases.get(k, {}).get("status") == "REFERENCE_NUMERICS_READY" for k in ("C1_Q23", "C1_Q4")))
        comparisons = self.state.get("comparisons", {})
        comparison_ok = len(comparisons) == len(self.expanded["comparisons"]) and all(c.get("resolved") for c in comparisons.values())
        observations = self.state.get("observations", {})
        observations_ok = len(observations) == len(self.expanded["runs"]) and all(not _retryable(s) for s in observations.values())
        action_hard_failure = any(c.get("exit_code") == 1 for c in cases.values())
        code = 1 if (failure and not isinstance(failure, CampaignDeadline)) or action_hard_failure else 0 if not failure and complete_runs and case_ok and comparison_ok and observations_ok else 2
        result = {"status": "CAMPAIGN_COMPUTATION_COMPLETE" if code == 0 else "CAMPAIGN_FAILED" if code == 1 else "CAMPAIGN_PARTIAL_OR_UNRESOLVED",
                  "exit_code": code, "campaign_dir": str(self.root), "identity": self.identity,
                  "run_count": len(self.expanded["runs"]), "completed_run_count": sum(bool(r.get("complete")) for r in self.state["runs"].values()),
                  "case_results": cases, "comparisons": comparisons,
                  "observations": observations,
                  "failure": str(failure) if failure else None, "stage07": "NOT_RUN", "stage08": "NOT_RUN",
                  "model_frozen": False, "scope": "AUTOMATED_STAGE06_NUMERICAL_EVIDENCE_NOT_INDEPENDENT_VALIDATION"}
        self.state["invocations"][-1].update(finished_at=_now(), status=result["status"], exit_code=code)
        self.state["status"] = result["status"]; self.save()
        _write(self.root / "campaign_summary.json", result)
        _write(self.root / f"campaign_summary_invocation_{self.invocation:03d}.json", result)
        # Packing is best effort even when a run is partial. Its own result and
        # timeout are recorded; a missing archive cannot turn failures into PASS.
        target = self.root.parent / (self.root.name + f"_return_{self.invocation:03d}.zip")
        try:
            packed = self.action("return_" + str(self.invocation),
                                 {"operation": "pack", "root": str(self.root), "zip_path": str(target)},
                                 300, cache=False, finalization=True)
            result["return_package"] = packed
        except Exception as exc:
            result["return_package"] = {"status": "NOT_PACKED", "reason": str(exc)}
        if not result["return_package"].get("path"):
            result["handoff_status"] = "RETURN_PACKAGE_UNRESOLVED"
            if result["exit_code"] == 0:
                result.update(exit_code=2, status="CAMPAIGN_PARTIAL_OR_UNRESOLVED")
        else:
            result["handoff_status"] = "RETURN_PACKAGE_READY"
        self.state["invocations"][-1].update(status=result["status"], exit_code=result["exit_code"],
                                             return_package=result["return_package"])
        self.state["status"] = result["status"]; self.save()
        _write(self.root / "campaign_summary.json", result)
        _write(self.root / f"campaign_summary_invocation_{self.invocation:03d}.json", result)
        return result


def run_campaign(plan, output, *, resume=False, plan_only=False):
    from .campaign_plan import expand_campaign
    expanded = expand_campaign(plan, root=ROOT)
    if plan_only:
        return {"status": "PLAN_ONLY_NO_EXECUTION", "expanded_plan": expanded, "exit_code": 0}
    out = Path(output).resolve()
    if out == ROOT or any(out == (ROOT / d).resolve() or (ROOT / d).resolve() in out.parents
                          for d in ("src", "tests", "configs", "data", "workspace")):
        raise ValueError("CAMPAIGN_OUTPUT_INVALID: choose a separate results directory")
    if out.exists() and not resume:
        raise FileExistsError("new campaign output must not already exist")
    out.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock(out):
        campaign = Campaign(expanded, out, resume)
        failure = None
        try:
            campaign.preflight()
            for specification in expanded["runs"]:
                campaign.run_one(specification)
            campaign.summarize()
            campaign.analyze()
        except (Exception, KeyboardInterrupt) as exc:
            failure = CampaignDeadline("USER_INTERRUPTED; completed work and checkpoints preserved") if isinstance(exc, KeyboardInterrupt) else exc
        return campaign.finish(failure)
