"""TEST_ONLY campaign orchestration with mocked execution and file-only evidence.

No test in this module launches a subprocess, probes CUDA, imports a solver,
integrates a PDE, or installs a dependency. Actual execution is reserved for
the authorized server test suite; local authoring checks are AST-only.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from drying import campaign, campaign_plan


def forbidden(*args, **kwargs):
    raise AssertionError("TEST_ISOLATION: an unmocked execution/provenance entrypoint was called")


@pytest.fixture(autouse=True)
def execution_isolation(monkeypatch, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(campaign, "ROOT", project)
    monkeypatch.setattr(campaign, "_invoke", forbidden)
    monkeypatch.setattr(campaign, "_current_run", forbidden)
    monkeypatch.setattr(campaign.subprocess, "run", forbidden)
    monkeypatch.setattr(campaign, "_identity", lambda plan: {
        "plan": plan["plan_fingerprint"], "code": "MOCK_SOURCE_V1",
        "raw": "MOCK_RAW_V1", "authority": "MOCK_AUTHORITY_V1"})


@pytest.fixture
def expanded():
    # Deliberately minimal orchestration input: no source config expansion or
    # numerical RunConfig construction is needed to exercise the state machine.
    return {
        "plan_fingerprint": "MOCK_PLAN_V1",
        "budget": {"session_wall_seconds": 60., "max_run_attempts": 2,
                   "tests_timeout_seconds": 15., "postprocess_wall_seconds": 10.,
                   "comparison_max_points": 100, "comparison_time_levels": 2,
                   "event_wall_seconds": 10., "event_max_levels": 2, "report_rounds": 2},
        "hardware": {"cuda_device": 2, "gpu_memory_mb": 1024},
        "runs": [{"run_key": "MOCK_RUN", "config": {
            "tmax": 20., "case_end_time": None, "wall_seconds": 2.}}],
        "cases": {name: {"reference_run": name + "_REF", "categories": {}}
                  for name in ("Q1", "C1_Q23", "C1_Q4", "B_Q23", "B_Q4")},
        "comparisons": [],
    }


def make_campaign(tmp_path, expanded):
    return campaign.Campaign(deepcopy(expanded), tmp_path / "campaign", resume=False)


def process_result(log, *, returncode=0, timed_out=False):
    return {"returncode": returncode, "timed_out": timed_out,
            "wall_seconds": .01, "log": str(log)}


def completed_record(end=20.):
    return {"status": "TIME_LIMIT_REACHED", "coverage_end": end,
            "manifest_sha256": "MOCK_MANIFEST", "trajectory_index_sha256": "MOCK_TRAJECTORY"}


@pytest.mark.parametrize("changed", ["plan", "code", "raw", "authority"])
def test_resume_rejects_changed_identity_without_rewriting_previous_state(monkeypatch, tmp_path, expanded, changed):
    first = make_campaign(tmp_path, expanded)
    original = first.path.read_bytes()
    altered = dict(first.identity, **{changed: "CHANGED"})
    monkeypatch.setattr(campaign, "_identity", lambda plan: altered)
    with pytest.raises(ValueError, match="CAMPAIGN_IDENTITY_CHANGED"):
        campaign.Campaign(expanded, first.root, resume=True)
    assert first.path.read_bytes() == original


def test_resume_is_explicit_and_adds_an_invocation_only_when_identity_matches(tmp_path, expanded):
    first = make_campaign(tmp_path, expanded)
    with pytest.raises(FileExistsError, match="use --resume"):
        campaign.Campaign(expanded, first.root, resume=False)
    resumed = campaign.Campaign(expanded, first.root, resume=True)
    assert resumed.invocation == 2
    assert resumed.state["identity"] == first.identity
    assert len(resumed.state["invocations"]) == 2
    with pytest.raises(FileNotFoundError, match="requires campaign_state"):
        campaign.Campaign(expanded, tmp_path / "absent", resume=True)


def test_verified_complete_run_is_cached_without_starting_a_child(monkeypatch, tmp_path, expanded):
    runner = make_campaign(tmp_path, expanded)
    spec = expanded["runs"][0]
    path = runner.root / "runs" / spec["run_key"]
    path.mkdir(parents=True)
    checks = []
    def current(run_path, config):
        checks.append((Path(run_path), deepcopy(config)))
        return completed_record()
    monkeypatch.setattr(campaign, "_current_run", current)
    runner.run_one(spec)
    assert checks == [(path, spec["config"])]
    assert runner.state["runs"][spec["run_key"]]["complete"]
    assert runner.state["runs"][spec["run_key"]]["attempts"] == []
    assert runner.run_paths() == {spec["run_key"]: str(path)}


def test_partial_run_has_finite_attempts_and_resume_preserves_checkpoint(monkeypatch, tmp_path, expanded):
    runner = make_campaign(tmp_path, expanded)
    spec = expanded["runs"][0]
    path = runner.root / "runs" / spec["run_key"]
    commands = []
    checkpoint = '{"identity":"MOCK_ACCEPTED_CHECKPOINT"}'
    def invoke(command, log, timeout, env=None):
        commands.append(list(command))
        path.mkdir(parents=True, exist_ok=True)
        if not (path / "checkpoint.json").exists():
            (path / "checkpoint.json").write_text(checkpoint, encoding="utf-8")
        return process_result(log, returncode=2, timed_out=False)
    monkeypatch.setattr(campaign, "_invoke", invoke)
    monkeypatch.setattr(campaign, "_current_run", lambda p, c: {
        "status": "WALL_BUDGET_REACHED", "coverage_end": 4.})
    runner.run_one(spec)
    assert len(commands) == expanded["budget"]["max_run_attempts"]
    assert "--resume" not in commands[0]
    assert "--resume" in commands[1]
    record = runner.state["runs"][spec["run_key"]]
    assert not record["complete"]
    assert len(record["attempts"]) == 2
    assert (path / "checkpoint.json").read_text() == checkpoint
    resumed = campaign.Campaign(expanded, runner.root, resume=True)
    resumed.run_one(spec)
    assert len(commands) == 4
    assert all("--resume" in command for command in commands[1:])
    assert [a["invocation"] for a in resumed.state["runs"][spec["run_key"]]["attempts"]] == [1, 1, 2, 2]
    assert not resumed.state["runs"][spec["run_key"]]["complete"]
    assert (path / "checkpoint.json").read_text() == checkpoint


def test_retry_stops_immediately_after_actual_coverage_reaches_target(monkeypatch, tmp_path, expanded):
    expanded["budget"]["max_run_attempts"] = 5
    runner = make_campaign(tmp_path, expanded)
    spec = expanded["runs"][0]
    path = runner.root / "runs" / spec["run_key"]
    attempts = []
    def invoke(command, log, timeout, env=None):
        attempts.append(list(command))
        path.mkdir(parents=True, exist_ok=True)
        (path / "checkpoint.json").write_text("{}", encoding="utf-8")
        return process_result(log, returncode=0 if len(attempts) == 2 else 2)
    monkeypatch.setattr(campaign, "_invoke", invoke)
    monkeypatch.setattr(campaign, "_current_run", lambda p, c: completed_record() if len(attempts) == 2 else {
        "status": "WALL_BUDGET_REACHED", "coverage_end": 5.})
    runner.run_one(spec)
    assert len(attempts) == 2
    assert runner.state["runs"][spec["run_key"]]["complete"]


@pytest.mark.parametrize("failure", sorted(campaign.HARD))
def test_existing_hard_failure_is_not_retried(monkeypatch, tmp_path, expanded, failure):
    runner = make_campaign(tmp_path, expanded)
    spec = expanded["runs"][0]
    (runner.root / "runs" / spec["run_key"]).mkdir(parents=True)
    monkeypatch.setattr(campaign, "_current_run", lambda p, c: {"status": failure, "coverage_end": 1.})
    with pytest.raises(RuntimeError, match="RUN_HARD_FAILURE"):
        runner.run_one(spec)
    assert runner.state["runs"][spec["run_key"]]["attempts"] == []


def test_child_hard_failure_stops_after_first_attempt(monkeypatch, tmp_path, expanded):
    runner = make_campaign(tmp_path, expanded)
    spec = expanded["runs"][0]
    path = runner.root / "runs" / spec["run_key"]
    calls = []
    def invoke(command, log, timeout, env=None):
        calls.append(list(command))
        path.mkdir(parents=True)
        (path / "checkpoint.json").write_text("{}", encoding="utf-8")
        return process_result(log, returncode=1)
    monkeypatch.setattr(campaign, "_invoke", invoke)
    monkeypatch.setattr(campaign, "_current_run", lambda p, c: {
        "status": "GPU_BACKEND_FAILURE", "coverage_end": 0.})
    with pytest.raises(RuntimeError, match="RUN_FAILED"):
        runner.run_one(spec)
    assert len(calls) == 1
    assert not runner.state["runs"][spec["run_key"]]["complete"]


def test_setup_directory_without_checkpoint_is_preserved_and_retried_fresh(monkeypatch, tmp_path, expanded):
    runner = make_campaign(tmp_path, expanded)
    spec = expanded["runs"][0]
    orphan = runner.root / "runs" / spec["run_key"]
    orphan.mkdir(parents=True)
    (orphan / "partial_setup.txt").write_text("preserve this setup evidence", encoding="utf-8")
    children = []
    def invoke(command, log, timeout, env=None):
        children.append(list(command))
        fresh = Path(command[command.index("--out") + 1])
        fresh.mkdir(parents=True)
        (fresh / "checkpoint.json").write_text("{}", encoding="utf-8")
        return process_result(log)
    monkeypatch.setattr(campaign, "_invoke", invoke)
    monkeypatch.setattr(campaign, "_current_run", lambda p, c: {
        "status": "RUNNING", "coverage_end": 0.} if Path(p) == orphan else completed_record())
    runner.run_one(spec)
    record = runner.state["runs"][spec["run_key"]]
    assert record["complete"]
    assert record["orphan_directories"] == [str(orphan)]
    assert Path(record["directory"]) != orphan
    assert (orphan / "partial_setup.txt").read_text() == "preserve this setup evidence"
    assert len(children) == 1 and "--resume" not in children[0]


def test_external_process_timeout_stops_this_invocation_without_retry_storm(monkeypatch, tmp_path, expanded):
    runner = make_campaign(tmp_path, expanded)
    spec = expanded["runs"][0]
    path = runner.root / "runs" / spec["run_key"]
    calls = []
    def invoke(command, log, timeout, env=None):
        calls.append(list(command))
        path.mkdir(parents=True)
        (path / "checkpoint.json").write_text("MOCK_PRESERVED_CHECKPOINT", encoding="utf-8")
        return process_result(log, returncode=2, timed_out=True)
    monkeypatch.setattr(campaign, "_invoke", invoke)
    monkeypatch.setattr(campaign, "_current_run", lambda p, c: {"status": "RUNNING", "coverage_end": 3.})
    runner.run_one(spec)
    record = runner.state["runs"][spec["run_key"]]
    assert len(calls) == 1
    assert record["status"] == "RUN_PROCESS_TIMEOUT"
    assert not record["complete"]
    assert (path / "checkpoint.json").read_text() == "MOCK_PRESERVED_CHECKPOINT"


@pytest.mark.parametrize("failure_stage,timed_out", [("preflight", False), ("tests", False), ("tests", True)])
def test_failed_cuda_preflight_or_required_tests_block_all_numerical_jobs(monkeypatch, tmp_path, expanded, failure_stage, timed_out):
    monkeypatch.setattr(campaign_plan, "expand_campaign", lambda plan, root: deepcopy(expanded))
    numerical_calls, process_calls, failures = [], [], []
    monkeypatch.setattr(campaign.Campaign, "run_one", lambda self, spec: numerical_calls.append(spec))
    monkeypatch.setattr(campaign.Campaign, "analyze", lambda self: numerical_calls.append("analysis"))
    def finish(self, failure=None):
        failures.append(failure)
        return {"status": "MOCK_FINISH", "failure": str(failure)}
    monkeypatch.setattr(campaign.Campaign, "finish", finish)
    def invoke(command, log, timeout, env=None):
        process_calls.append((list(command), env))
        if "_campaign-worker" in command:
            payload = campaign._read(command[command.index("--request") + 1])
            assert payload["operation"] == "preflight"
            assert payload["cuda_requests"] == [{"cuda_device": 2, "gpu_memory_mb": 1024}]
            failed = failure_stage == "preflight"
            campaign._write(payload["output"], {"status": "FAIL" if failed else "PASS"})
            return process_result(log, returncode=1 if failed else 0)
        assert "pytest" in command
        assert env["DRYING_REQUIRE_CUDA"] == "1"
        assert json.loads(env["DRYING_CUDA_TEST_REQUESTS"]) == [{"cuda_device": 2, "gpu_memory_mb": 1024}]
        return process_result(log, returncode=2 if timed_out else 1, timed_out=timed_out)
    monkeypatch.setattr(campaign, "_invoke", invoke)
    campaign.run_campaign({}, tmp_path / "full_run")
    assert not numerical_calls
    assert len(process_calls) == (1 if failure_stage == "preflight" else 2)
    expected = "PREFLIGHT_FAILED" if failure_stage == "preflight" else "GPU_TESTS_FAILED_OR_TIMED_OUT"
    assert len(failures) == 1 and expected in str(failures[0])


def action_writer(role, calls):
    def execute(directory):
        calls.append(Path(directory))
        (Path(directory) / "proof.txt").write_text("same immutable " + role + " proof", encoding="utf-8")
        return {"status": "MOCK_COMPLETE", "role": role}
    return execute


def store(root, identity=None):
    return campaign.ActionStore(root, identity or {"campaign": "MOCK"}, campaign.time.time() + 60.)


@pytest.mark.parametrize("artifact", ["proof.txt", "action_result.json"])
def test_action_store_tampered_artifacts_force_a_new_attempt(tmp_path, artifact):
    root, calls = tmp_path / "actions", []
    first = store(root)
    expected = first("measure", action_writer("measure", calls))
    cached = store(root)
    assert cached("measure", forbidden) == expected
    (calls[0] / artifact).write_text("tampered bytes", encoding="utf-8")
    repaired = store(root)
    assert repaired("measure", action_writer("measure", calls)) == expected
    assert len(calls) == 2
    assert calls[0] != calls[1]
    assert len(campaign._read(root / "actions.json")["actions"]["measure"]) == 2


def test_action_store_redoing_upstream_invalidates_downstream_even_with_identical_new_bytes(tmp_path):
    root, upstream, downstream = tmp_path / "actions", [], []
    initial = store(root)
    initial("upstream", action_writer("upstream", upstream))
    initial("downstream", action_writer("downstream", downstream))
    unchanged = store(root)
    unchanged("upstream", forbidden)
    unchanged("downstream", forbidden)
    assert len(upstream) == len(downstream) == 1
    (upstream[0] / "proof.txt").write_text("corrupted", encoding="utf-8")
    refreshed = store(root)
    refreshed("upstream", action_writer("upstream", upstream))
    refreshed("downstream", action_writer("downstream", downstream))
    assert len(upstream) == len(downstream) == 2
    assert upstream[0] != upstream[1] and downstream[0] != downstream[1]
    # The downstream payload is unchanged; its previous dependency is what
    # became stale. Old attempts remain available and the next replay caches.
    assert (downstream[0] / "proof.txt").read_bytes() == (downstream[1] / "proof.txt").read_bytes()
    stable_again = store(root)
    stable_again("upstream", forbidden)
    stable_again("downstream", forbidden)


def test_action_store_failed_or_unresolved_work_is_not_a_successful_cache(tmp_path):
    root = tmp_path / "actions"
    calls = []
    def unresolved(directory):
        calls.append(Path(directory))
        return {"status": "ERROR_BUDGET_UNRESOLVED", "exit_code": 2}
    first = store(root)
    first("event", unresolved)
    second = store(root)
    second("event", action_writer("event", calls))
    assert len(calls) == 2
    third = store(root)
    assert third("event", forbidden)["status"] == "MOCK_COMPLETE"


def test_action_store_interruption_preserves_partial_directory_and_restarts_fresh(tmp_path):
    root, interrupted = tmp_path / "actions", []
    def stop(directory):
        interrupted.append(Path(directory))
        (Path(directory) / "partial.txt").write_text("partial evidence", encoding="utf-8")
        raise KeyboardInterrupt("MOCK_INTERRUPTION")
    with pytest.raises(KeyboardInterrupt):
        store(root)("measure", stop)
    done = []
    store(root)("measure", action_writer("measure", done))
    records = campaign._read(root / "actions.json")["actions"]["measure"]
    assert [record["status"] for record in records] == ["INTERRUPTED_OR_FAILED", "RECORDED"]
    assert interrupted[0] != done[0]
    assert (interrupted[0] / "partial.txt").read_text() == "partial evidence"


def test_action_store_identity_change_requires_a_distinct_analysis_directory(tmp_path):
    root = tmp_path / "actions"
    store(root, {"identity": 1})("measure", action_writer("measure", []))
    original = (root / "actions.json").read_bytes()
    with pytest.raises(ValueError, match="ACTION_IDENTITY_CHANGED"):
        store(root, {"identity": 2})
    assert (root / "actions.json").read_bytes() == original


def test_session_budget_stops_before_child_launch_and_resume_gets_new_session(monkeypatch, tmp_path, expanded):
    clock = [1000.]
    monkeypatch.setattr(campaign.time, "time", lambda: clock[0])
    expanded["budget"]["session_wall_seconds"] = 1.
    runner = make_campaign(tmp_path, expanded)
    clock[0] = 1002.
    with pytest.raises(campaign.CampaignDeadline, match="CAMPAIGN_BUDGET_REACHED"):
        runner.run_one(expanded["runs"][0])
    resumed = campaign.Campaign(expanded, runner.root, resume=True)
    assert resumed.remaining() == 1.
    assert resumed.invocation == 2
    assert resumed.state["identity"] == runner.identity


def test_action_budget_exhaustion_prevents_callback_even_if_action_was_cached(tmp_path):
    root = tmp_path / "actions"
    store(root)("measure", action_writer("measure", []))
    expired = campaign.ActionStore(root, {"campaign": "MOCK"}, campaign.time.time() - 1.)
    with pytest.raises(campaign.CampaignDeadline, match="CAMPAIGN_BUDGET_REACHED"):
        expired("measure", forbidden)


def test_C_critical_time_is_part_of_B_analysis_cache_identity(monkeypatch, tmp_path, expanded):
    runner = make_campaign(tmp_path, expanded)
    for name, case in expanded["cases"].items():
        runner.state["runs"][case["reference_run"]] = dict(
            completed_record(), complete=True, directory=str(tmp_path / name))
    critical_time = [100.]
    captured = []
    def action(key, payload, timeout, cache=True):
        assert payload["operation"] == "analysis"
        captured.append(deepcopy(payload))
        name = payload["context"]["case_id"]
        if name.startswith("C1_"):
            return {"status": "REFERENCE_NUMERICS_READY", "certificate": {
                "status": "DRYING_COMPLETE", "t_hat": critical_time[0] if name == "C1_Q23" else 200.}}
        return {"status": "MOCK_ANALYSIS_RECORDED"}
    monkeypatch.setattr(runner, "action", action)
    runner.analyze()
    critical_time[0] = 150.
    runner.analyze()
    b_payloads = [payload for payload in captured if payload["context"]["case_id"] == "B_Q23"]
    assert [payload["context"]["reference_critical_time"] for payload in b_payloads] == [100., 150.]
    assert b_payloads[0]["identity"] != b_payloads[1]["identity"]
    assert b_payloads[0]["action_root"] != b_payloads[1]["action_root"]
    # The source run identities did not change; only the reference time did.
    assert b_payloads[0]["context"]["reference_run"] == b_payloads[1]["context"]["reference_run"]


@pytest.mark.parametrize("failure,exit_code", [(None, 2), (RuntimeError("MOCK_HARD_FAILURE"), 1),
                                               (campaign.CampaignDeadline("MOCK_SESSION_END"), 2)])
def test_finish_preserves_partial_failure_and_never_claims_Stage07(monkeypatch, tmp_path, expanded, failure, exit_code):
    runner = make_campaign(tmp_path, expanded)
    monkeypatch.setattr(runner, "action", lambda *args, **kwargs: {"status": "MOCK_PACKED"})
    summary = runner.finish(failure)
    assert summary["exit_code"] == exit_code
    assert summary["stage07"] == "NOT_RUN"
    assert summary["stage08"] == "NOT_RUN"
    assert summary["model_frozen"] is False
    assert summary["status"] != "CAMPAIGN_COMPUTATION_COMPLETE"


@pytest.mark.parametrize("returncode,timed_out",[(1,False),(2,True)])
def test_success_payload_cannot_hide_worker_failure(monkeypatch,tmp_path,expanded,returncode,timed_out):
    runner=make_campaign(tmp_path,expanded)
    def invoke(command,log,timeout,env=None):
        request=campaign._read(command[command.index("--request")+1])
        campaign._write(request["output"],{"status":"PASS","exit_code":0})
        return process_result(log,returncode=returncode,timed_out=timed_out)
    monkeypatch.setattr(campaign,"_invoke",invoke)
    if timed_out:
        result=runner.action("mock_worker",{"operation":"preflight"},10)
        assert result["exit_code"]==2 and result["status"]=="ACTION_TIMEOUT"
    else:
        with pytest.raises(RuntimeError,match="EXECUTION_EXCEPTION"):
            runner.action("mock_worker",{"operation":"preflight"},10)
    assert runner.state["actions"]["mock_worker"][-1]["returncode"]==returncode
