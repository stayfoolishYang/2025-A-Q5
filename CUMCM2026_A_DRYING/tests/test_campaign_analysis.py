"""SERVER ONLY orchestration tests; stubbed outcomes are not CUDA/PDE evidence.

Do not execute locally under the user's prohibition. Numerical solver accuracy
is tested by the separate real CUDA/refinement suites, never by these stubs.
"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from drying import campaign_analysis as analysis
from drying.config import RunConfig


@pytest.fixture
def flow(tmp_path, monkeypatch):
    calls = []
    route = ["B"]
    question = [23]
    manifest = {"identity": {"input": "fixture-only-input", "config": "fixture-only-config"}}
    def load(path, data_dir=None):
        cfg = SimpleNamespace(route=route[0], question=question[0], test_case=None, tmax=2000.)
        trajectory = SimpleNamespace(start_time=0., end_time=2000., index={"fixture": True})
        return Path(path), cfg, manifest, object(), trajectory
    monkeypatch.setattr(analysis, "_load_run", load)
    monkeypatch.setattr(analysis, "_require_cuda_evidence", lambda *a: None)
    monkeypatch.setattr(analysis, "scan_events", lambda *a, **k: {
        "status": "PROVISIONAL_EVENT", "earliest_verified": True,
        "retention_verified": True, "t_hat": 1000., "tR": 1000.005})
    def ensure(key, function):
        calls.append(key)
        work = tmp_path / ("action_" + str(len(calls)))
        work.mkdir()
        return function(work)
    context = {"case_id": "B_Q23", "reference_run": str(tmp_path/"reference"),
        "category_runs": {k: [str(tmp_path/(k+str(i))) for i in range(3)]
                          for k in ("radial", "time", "newton", "dense")},
        "ensure_action": ensure, "limits": {"closure_rounds": 2}, "export_requested": True}
    monkeypatch.setattr(analysis, "_event_action", lambda source, work, width, data, limits: {
        "status": "EVENT_BRACKET_REFINED", "run_dir": str(work/"refined"), "width": width,
        "event": {"tR": 1000.005}})
    evidence = {"status": "FIELD_ERROR_EVIDENCE_READY", "checks_passed": True,
                "refinement_verified": True, "eC": 1e-5, "eG": 1e-5,
                "evidence_fingerprint": "fixture-only-evidence", "coverage_end": 2000.}
    monkeypatch.setattr(analysis, "build_error_evidence", lambda *a, **k: deepcopy(evidence))
    monkeypatch.setattr(analysis, "_prepare_action", lambda source, ev, work, data, limits: {
        "status": "PROVISIONAL_EVENT", "run_dir": str(work/"prepared"),
        "eta_strict": 2e-5, "t_report": 1000.08, "t_hat": 1000.})
    monkeypatch.setattr(analysis, "_balances_action", lambda source, work, data, limits: {
        "status": "CURRENT_CUMULATIVE_BALANCES_CHECKED", "checks_passed": True,
        "run_dir": str(work/"run"), "diagnostics_path": str(work/"run"/"diagnostics.json")})
    monkeypatch.setattr(analysis, "certify_strict_report", lambda *a, **k: {
        "status": "DRYING_COMPLETE", "t_hat": 1000.,
        "common_reference_checked": k.get("reference_critical_time") is not None})
    monkeypatch.setattr(analysis, "_export_action", lambda *a, **k: {"status": "CANDIDATE_EXPORTED"})
    return SimpleNamespace(context=context, calls=calls, route=route, question=question, evidence=evidence)


def test_strict_chain_refreshes_final_evidence_before_balances_certificate_export(flow):
    result = analysis.analyze_case(flow.context)
    assert result["status"] == "DRYING_COMPLETE" and result["stage07"] == "NOT_RUN"
    assert [r["width"] for r in result["event_levels"]] == [.01, .005, .0025]
    tail = [key.rsplit("/", 1)[-1] for key in flow.calls[-5:]]
    assert tail == ["prepare", "refresh_error_evidence", "balances", "certify", "export"]
    assert result["common_reference_checked"] is False
    assert result["structural_validation"] == "NOT_RUN"


def test_missing_measured_error_never_prepares_margin_or_exports(flow):
    flow.evidence.update(status="ERROR_BUDGET_UNRESOLVED", checks_passed=False)
    result = analysis.analyze_case(flow.context)
    assert result["status"] == "ERROR_BUDGET_UNRESOLVED"
    assert not any("prepare" in k or "certify" in k or "export" in k for k in flow.calls)


def test_changed_refreshed_margin_repeats_and_stops_at_finite_budget(flow, monkeypatch):
    sequence = iter([deepcopy(flow.evidence), dict(flow.evidence, eC=2e-5), dict(flow.evidence, eC=3e-5)])
    monkeypatch.setattr(analysis, "build_error_evidence", lambda *a, **k: next(sequence))
    result = analysis.analyze_case(flow.context)
    assert result["status"] == "ERROR_BUDGET_UNRESOLVED"
    assert len(result["closure_updates"]) == 2
    assert sum(key.endswith("/prepare") for key in flow.calls) == 2
    assert not any(key.endswith("/balances") or key.endswith("/certify") or key.endswith("/export") for key in flow.calls)


def test_failed_current_balances_block_certificate_and_export(flow, monkeypatch):
    monkeypatch.setattr(analysis, "_balances_action", lambda *a: {
        "status": "DIAGNOSTICS_UNRESOLVED", "checks_passed": False})
    result = analysis.analyze_case(flow.context)
    assert result["status"] == "DIAGNOSTICS_UNRESOLVED"
    assert not any(key.endswith("/certify") or key.endswith("/export") for key in flow.calls)


def test_reference_gets_same_chain_but_never_formal_exports(flow):
    flow.route[0] = "C"
    flow.context["case_id"] = "C1_Q23"
    flow.context["category_runs"].update(axial=["a0", "a1", "a2"], joint=["j0", "j1", "j2"])
    result = analysis.analyze_case(flow.context)
    assert result["status"] == "REFERENCE_NUMERICS_READY"
    assert any(key.endswith("/certify") for key in flow.calls)
    assert "export" not in result and not any(key.endswith("/export") for key in flow.calls)


def test_common_reference_time_is_passed_to_existing_certifier(flow, monkeypatch):
    received = []
    flow.context["reference_critical_time"] = 990.
    def certify(*args, **kwargs):
        received.append(kwargs["reference_critical_time"])
        return {"status": "DRYING_COMPLETE", "common_reference_checked": True}
    monkeypatch.setattr(analysis, "certify_strict_report", certify)
    result = analysis.analyze_case(flow.context)
    assert received == [990.] and result["common_reference_checked"]


def test_no_event_or_unverified_earliest_event_never_reintegrates(flow, monkeypatch):
    monkeypatch.setattr(analysis, "scan_events", lambda *a: {"status": "NO_EVENT"})
    assert analysis.analyze_case(flow.context)["status"] == "NO_EVENT"
    assert not flow.calls


def test_gpu_failure_and_global_deadline_do_not_get_softened(flow, monkeypatch):
    monkeypatch.setattr(analysis, "_event_action", lambda *a: {"status": "GPU_BACKEND_FAILURE"})
    result = analysis.analyze_case(flow.context)
    assert result["status"] == "GPU_BACKEND_FAILURE" and result["exit_code"] == 1
    def deadline(*args):
        raise RuntimeError("fixture global deadline")
    flow.context["ensure_action"] = deadline
    with pytest.raises(RuntimeError, match="global deadline"):
        analysis.analyze_case(flow.context)


def test_q1_needs_actual_fields_and_balances_before_automatic_acceptance(flow, monkeypatch):
    flow.question[0] = 1
    flow.context["case_id"] = "Q1"
    monkeypatch.setattr(analysis, "_q1_field_evidence", lambda *a, **k: deepcopy(flow.evidence))
    result = analysis.analyze_case(flow.context)
    assert result["status"] == "Q1_CANDIDATE_EXPORTED"
    assert result["development_acceptance"]["status"] == "Q1_NUMERICAL_CHECKS_PASSED"
    assert [k.rsplit("/", 1)[-1] for k in flow.calls] == ["q1_fields", "q1_balances", "q1_export"]
    assert not result["development_acceptance"]["four_decimal_accuracy_claimed"]


def test_q1_insufficient_measured_fields_produce_no_development_acceptance(flow, monkeypatch):
    flow.question[0] = 1
    monkeypatch.setattr(analysis, "_q1_field_evidence", lambda *a, **k: {
        "status": "ERROR_BUDGET_UNRESOLVED", "checks_passed": False})
    result = analysis.analyze_case(flow.context)
    assert "development_acceptance" not in result and "export" not in result
    assert len(flow.calls) == 1


@pytest.mark.parametrize("limits", [{"closure_rounds": 0}, {"event_max_levels": 1.5},
                                   {"comparison_wall_seconds": float("inf")}, {"fixed_eta": .00001}])
def test_invalid_limits_and_fixed_margin_option_are_rejected(limits):
    with pytest.raises(analysis.CampaignAnalysisError):
        analysis._limits(limits)


def test_clone_copies_mutable_metadata_and_refuses_overwrite(tmp_path):
    source = tmp_path/"source"
    (source/"trajectory").mkdir(parents=True)
    (source/"checkpoints").mkdir()
    (source/"source_snapshot").mkdir()
    (source/"manifest.json").write_text(json.dumps({"identity": {"config": "fixture"}}))
    (source/"event.json").write_text('{"status":"ORIGINAL"}')
    (source/"checkpoints"/"a.json").write_text('{"accepted":"original"}')
    (source/"source_snapshot"/"model.py").write_text("# original\n")
    (source/"trajectory"/"index.json").write_text(json.dumps({"chunks": [{"file": "chunk_000000.npz"}]}))
    # Bytes are a filesystem fixture only; no numerical trajectory is asserted.
    (source/"trajectory"/"chunk_000000.npz").write_bytes(b"immutable fixture bytes")
    cloned = analysis._clone_run(source, tmp_path/"clone")
    (cloned/"event.json").write_text('{"status":"CHANGED"}')
    (cloned/"checkpoints"/"a.json").write_text("changed")
    (cloned/"source_snapshot"/"model.py").write_text("changed")
    assert json.loads((source/"event.json").read_text())["status"] == "ORIGINAL"
    assert "original" in (source/"checkpoints"/"a.json").read_text()
    assert "original" in (source/"source_snapshot"/"model.py").read_text()
    with pytest.raises(FileExistsError):
        analysis._clone_run(source, cloned)
    with pytest.raises(analysis.CampaignAnalysisError, match="outside source"):
        analysis._clone_run(source, source/"nested")


def test_write_new_does_not_overwrite_completed_action_output(tmp_path):
    output = tmp_path/"result.json"
    analysis._write_new(output, {"status": "original"})
    with pytest.raises(FileExistsError):
        analysis._write_new(output, {"status": "replacement"})
    assert json.loads(output.read_text())["status"] == "original"


@pytest.fixture
def q1_fields(tmp_path, monkeypatch):
    """Exercise aggregation rules with explicitly synthetic comparison records."""
    cfg = RunConfig(question=1, nr=80)
    manifest = {"identity": {"input": "synthetic", "config": cfg.fingerprint}}
    tr = SimpleNamespace(start_time=0., end_time=1800., index={"synthetic": True})
    monkeypatch.setattr(analysis, "_load_run", lambda path, data=None: (Path(path), cfg, manifest, None, tr))
    monkeypatch.setattr(analysis, "_require_cuda_evidence", lambda *args: None)
    monkeypatch.setattr(analysis, "_core_hashes", lambda *args: {"synthetic": "no-numerical-proof"})
    monkeypatch.setattr(analysis, "_validate_category", lambda *args: None)
    categories = {name: [str(tmp_path/(name+str(i))) for i in range(3)]
                  for name in ("radial", "time", "newton", "dense")}
    for path in categories["dense"]:
        Path(path).mkdir()
        (Path(path)/"metrics.json").write_text('{"stats":{"max_h":1}}')
    calls = []
    def measured(a, b, **options):
        calls.append((a, b, options))
        factor = 1. if str(a).endswith("0") else .5
        return {"resolved": True, "differences": {"T": .001*factor, "C": 1e-6*factor, "G": 2e-6*factor},
                "event_difference": None, "comparison_scope": "SYNTHETIC_TEST_RECORD"}
    monkeypatch.setattr(analysis, "compare_runs", measured)
    return SimpleNamespace(categories=categories, calls=calls, reference=str(tmp_path/"reference"), measured=measured)


def test_q1_sums_two_times_max_adjacent_differences_without_inventing_event(q1_fields):
    result = analysis._q1_field_evidence(q1_fields.reference, q1_fields.categories)
    assert result["status"] == "Q1_FIELD_ERROR_EVIDENCE_READY" and result["checks_passed"]
    assert result["eT"] == pytest.approx(.008)
    assert result["eC"] == pytest.approx(8e-6) and result["eG"] == pytest.approx(16e-6)
    assert result["event_error"] == "NOT_APPLICABLE_Q1"
    assert len(q1_fields.calls) == 8
    assert all(call[2]["coverage_end"] == 1800. for call in q1_fields.calls)


def test_q1_non_decreasing_radial_differences_block_acceptance(q1_fields, monkeypatch):
    def increasing(a, b, **kwargs):
        result = q1_fields.measured(a, b, **kwargs)
        if "radial1" in str(a):
            result["differences"]["C"] = .000002
        return result
    monkeypatch.setattr(analysis, "compare_runs", increasing)
    result = analysis._q1_field_evidence(q1_fields.reference, q1_fields.categories)
    assert not result["checks_passed"]
    assert any("SPATIAL_CONVERGENCE_UNRESOLVED" in issue for issue in result["issues"])


def test_q1_missing_levels_and_unresolved_comparison_remain_unqualified(q1_fields, monkeypatch):
    q1_fields.categories["radial"] = q1_fields.categories["radial"][:2]
    monkeypatch.setattr(analysis, "compare_runs", lambda *a, **k: {"resolved": False})
    result = analysis._q1_field_evidence(q1_fields.reference, q1_fields.categories)
    assert not result["checks_passed"] and result["eC"] is None
    assert any("three actual levels" in issue for issue in result["issues"])
    assert any("comparison unresolved" in issue for issue in result["issues"])


def test_initial_evidence_window_does_not_spend_maximum_allowed_waiting(flow, monkeypatch):
    requests = []
    def evidence(*args, **kwargs):
        requests.append(kwargs["coverage_end"])
        return deepcopy(flow.evidence)
    monkeypatch.setattr(analysis, "build_error_evidence", evidence)
    result = analysis.analyze_case(flow.context)
    assert result["status"] == "DRYING_COMPLETE"
    assert requests[0] == pytest.approx(1000.005 + .36 + .01)
    assert requests[0] < result["analysis_coverage_limit"]


def test_coverage_request_uses_actual_measured_margin_on_complete_source(monkeypatch):
    seen = []
    trajectory = SimpleNamespace(end_time=259200.)
    def scan(system, tr, threshold):
        seen.append((tr.end_time, threshold))
        return {"status": "PROVISIONAL_EVENT", "earliest_verified": True,
                "retention_verified": True, "t_hat": 200000.001, "tR": 200000.005}
    monkeypatch.setattr(analysis, "scan_events", scan)
    result = analysis._coverage_request(object(), trajectory, {"eC": .00003, "eG": .00002}, 200180.)
    assert result["status"] == "COVERAGE_REQUEST_READY"
    assert seen == [(259200., .15-.00006)]
    assert 200000.005 <= result["coverage_end"] < 200000.365
    assert result["coverage_end"] < result["coverage_limit"]


def test_short_prepared_path_is_extended_even_when_event_levels_already_cover_target(flow, monkeypatch):
    original_load = analysis._load_run
    def load(path, data_dir=None):
        values = list(original_load(path, data_dir))
        if str(path).endswith("short_prepared"):
            values[-1] = SimpleNamespace(end_time=1000.08)
        return tuple(values)
    monkeypatch.setattr(analysis, "_load_run", load)
    extensions = []
    def extend(path, output, until, **kwargs):
        extensions.append((str(path), until))
        return {"status": "COMPLETED_INTERVAL", "run_dir": str(output)}
    monkeypatch.setattr(analysis, "extend_refinement_run", extend)
    event_paths = ["event0", "event1", "event2"]
    result = analysis._cover_event_and_current(flow.context, "closure_1/", event_paths,
        "short_prepared", 1000.44, None, analysis._limits({}))
    assert result["status"] == "COVERAGE_READY" and result["changed"]
    assert extensions == [("short_prepared", 1000.44)]
    assert result["current"] != "short_prepared" and result["event_paths"] == event_paths


def test_tightened_threshold_missing_on_complete_source_stays_unresolved(monkeypatch):
    monkeypatch.setattr(analysis, "scan_events", lambda *a, **k: {"status": "NO_EVENT"})
    result = analysis._coverage_request(object(), SimpleNamespace(end_time=72*3600),
        {"eC": .00003, "eG": .00002}, 200180.)
    assert result["status"] == "REPORT_TIME_UNRESOLVED"
    assert "coverage_end" not in result
