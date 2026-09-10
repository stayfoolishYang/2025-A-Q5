"""TEST_ONLY real implicit re-integrations and fail-closed evidence handling."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import json
import numpy as np
import pytest
from scipy.sparse import diags

from drying.config import RunConfig
from drying.execution import code_identity
from drying.integrator import Integrator, Settings
from drying.physics import properties
from drying.spatial import Grid, DryingSystem
from drying.manufactured import ManufacturedCase
from drying.reconstruction import reconstruct
from drying.trajectory import Trajectory, TrajectoryWriter, atomic_json, fingerprint, save_checkpoint
from drying.refinement import (refine_event, select_checkpoint, compare_runs, spatial_difference,
    polynomial_rectangle_max, plan_refinement_configs, build_error_evidence,
    prepare_strict_report, certify_strict_report, extend_refinement_run, _reintegrate_suffix,
    _validate_category, recompute_balances, RefinementError)


class TestInputs:
    __test__ = False
    fingerprint = "TEST_ONLY_SYNTHETIC_INPUT"
    water = np.array([.02])
    tail_water = .02
    def at(self, t, question=23, geometry="fixed", side="point"):
        return SimpleNamespace(T_inf=310., C_eq=.02, R=.02, Rdot=0.)
    def nodes(self, question=23, geometry="fixed", tmax=1.):
        return []
    def node_kind(self, *args, **kwargs):
        return "NONE"


class DecayCells:
    """Independent T'=0, C'=-(C-.02), real sparse implicit solves."""
    def __init__(self, config):
        self.grid = Grid(config.nr, config.nz, config.route)
        self.inputs = TestInputs()
        self.question, self.geometry, self.end_condition = config.question, config.geometry, config.end_condition
        self.test_case, self.h, self.hm = None, 25., 8e-7
        self.rhs_calls = 0
    def initial(self):
        return np.tile([310., .2], self.grid.ncell)
    def boundary(self, t, side="point"):
        return self.inputs.at(t)
    def boundary_environments(self, t, side="point"):
        return np.tile([310., .02], (self.grid.nz, 1)), np.tile([310., .02], (self.grid.nr, 1))
    def material(self, T, C):
        return properties(1, T, C)
    def evaluate(self, t, y, side="point", jacobian=True):
        self.rhs_calls += 1
        f = np.zeros_like(y); f[1::2] = -(y[1::2]-.02)
        diagonal = np.zeros_like(y); diagonal[1::2] = -1.
        return SimpleNamespace(f=f, jac=diags(diagonal, format="csc") if jacobian else None)


def mms_factory(config):
    return DryingSystem(Grid(config.nr, config.nz, config.route), TestInputs(),
                        test_case=ManufacturedCase(route=config.route), end_condition=config.end_condition)


def write_run(path, config, factory=DecayCells, until=.7, checkpoint_interval=10):
    path = Path(path); path.mkdir()
    system = factory(config)
    solver = Integrator(system, Settings.from_config(config))
    identity = {"config": config.fingerprint, "input": system.inputs.fingerprint,
                "code": code_identity()["sha256"], "model_version": config.model_version, "dtype": "float64"}
    writer = TrajectoryWriter(path/"trajectory", identity, chunk_size=16)
    writer.append(0., solver.y)
    if checkpoint_interval:
        save_checkpoint(path/"checkpoints"/"initial.json", solver, identity)
    def accept(a, b, c, d, info, residual):
        writer.append(c, d)
        if checkpoint_interval and solver.stats["accepted"] % checkpoint_interval == 0:
            save_checkpoint(path/"checkpoints"/f"accepted_{solver.stats['accepted']:06d}.json", solver, identity)
    result = solver.run(until, callback=accept)
    assert result["status"] == "COMPLETED_INTERVAL"
    writer.flush()
    save_checkpoint(path/"checkpoint.json", solver, identity)
    config.to_json(path/"config.json")
    atomic_json(path/"manifest.json", {"identity": identity, "source": code_identity(),
        "solver": {"name": solver.algorithm, "status": "COMPLETED_INTERVAL"},
        "experiment": {"name": path.name}, "execution": {"execution_purpose": "TEST_ONLY"}})
    atomic_json(path/"metrics.json", result)
    return system, solver, identity


@pytest.fixture
def config():
    return RunConfig(nr=3, tmax=1., rtol=2e-4, atol_t=2e-5, atol_c=2e-7,
                     h0=.001, hmax=.04, execution_purpose="TEST_ONLY", wall_seconds=30.,linear_backend="CPU_REFERENCE")


def test_real_event_reintegration_has_new_accepted_states_and_preserves_prefix(tmp_path, config):
    src = tmp_path/"source"
    write_run(src, config)
    original = Trajectory(src/"trajectory", verify=True)
    before_digest = fingerprint(original.index)
    result = refine_event(src, tmp_path/"refine", width=.01, system_factory=DecayCells, wall_seconds=30.)
    assert result["status"] == "EVENT_BRACKET_REFINED"
    assert result["rounds"] and result["rounds"][0]["new_accepted_steps"] > 1
    current = Trajectory(Path(result["run_dir"])/"trajectory", verify=True)
    start = result["rounds"][0]["checkpoint_time"]
    old_prefix = [(t, y) for t, y in original.iter_states() if t <= start]
    new_prefix = [(t, y) for t, y in current.iter_states() if t <= start]
    assert [x[0] for x in old_prefix] == [x[0] for x in new_prefix]
    for (_, a), (_, b) in zip(old_prefix, new_prefix):
        np.testing.assert_array_equal(a, b)
    old_times = {float(t) for t, _ in original.iter_states()}
    assert any(float(t) not in old_times for t, _ in current.iter_states() if t > start)
    event = result["event"]
    assert event["tR"]-event["tL"] <= .01
    assert event["tL_max_C"] >= .15 and event["tR_max_C"] < .15
    assert abs(event["t_hat"]-np.log(.18/.13)) < .003
    assert fingerprint(Trajectory(src/"trajectory").index) == before_digest
    manifest = json.loads((Path(result["run_dir"])/"manifest.json").read_text())
    assert manifest["refinement"]["method"] == "ACCEPTED_CHECKPOINT_REINTEGRATION"
    assert manifest["refinement"]["injected_test_system"] is True


def test_event_width_three_levels_and_real_continuation_to_evidence_horizon(tmp_path, config):
    src = tmp_path/"source"; write_run(src, config)
    paths = []
    for i, width in enumerate((.01, .005, .0025)):
        rr = refine_event(src, tmp_path/f"level{i}", width=width, system_factory=DecayCells, wall_seconds=30.)
        assert rr["status"] == "EVENT_BRACKET_REFINED"
        ext = extend_refinement_run(rr["run_dir"], tmp_path/f"extended{i}", .7,
                                   system_factory=DecayCells, wall_seconds=30.)
        assert ext["status"] == "COMPLETED_INTERVAL"
        paths.append(Path(ext["run_dir"]))
    configs = [RunConfig.from_json(p/"config.json") for p in paths]
    manifests = [json.loads((p/"manifest.json").read_text()) for p in paths]
    _validate_category("event", configs, manifests)
    assert all(Trajectory(p/"trajectory").end_time == .7 for p in paths)


def test_checkpoint_interpolation_forgery_is_rejected(tmp_path, config):
    src = tmp_path/"source"; system, solver, identity = write_run(src, config)
    trajectory = Trajectory(src/"trajectory")
    snapshot = solver.snapshot()
    snapshot.update(t=.300012345, y=trajectory.at(.300012345).tolist(), y_prev=None,
                    t_prev=None, h_prev=None, needs_be=True)
    atomic_json(src/"checkpoints"/"forged.json", {"identity": identity, "integrator": snapshot})
    with pytest.raises(RefinementError, match="accepted"):
        select_checkpoint(src, trajectory, system, config, identity, .31)


def test_no_stored_preceding_checkpoint_uses_verified_true_initial_state(tmp_path, config):
    src = tmp_path/"source"; system, solver, identity = write_run(src, config, checkpoint_interval=0)
    obj, provenance = select_checkpoint(src, Trajectory(src/"trajectory"), system, config, identity, .3)
    assert provenance["kind"] == "VERIFIED_INITIAL_STATE"
    assert obj["integrator"]["t"] == 0 and obj["integrator"]["y_prev"] is None


def test_actual_MMS_PDE_suffix_can_restart_from_accepted_checkpoint(tmp_path, config):
    cfg = replace(config, nr=4, test_case="MMS_FIXED", case_end_time=.2, hmax=.01)
    src = tmp_path/"mms"; write_run(src, cfg, factory=mms_factory, until=.2, checkpoint_interval=2)
    rr = _reintegrate_suffix(src, tmp_path/"mms_refined", before=.1, until=.2,
                            forced_nodes=[.123], hmax=.002, width=.004,
                            system_factory=mms_factory, wall_seconds=30.)
    assert rr["status"] == "COMPLETED_INTERVAL" and rr["new_accepted_steps"] > 20
    refined = Trajectory(Path(rr["run_dir"])/"trajectory")
    assert any(float(t) == .123 for t, _ in refined.iter_states())
    assert np.all(np.isfinite(refined.at(.2)))
    diagnostics = recompute_balances(rr["run_dir"],system_factory=mms_factory,wall_seconds=30.)
    assert diagnostics["checks_passed"] and diagnostics["covered_until"] == .2
    assert diagnostics["layer_bound_violations"] is None


def test_polynomial_stationary_points_include_interior_and_edges():
    # f=1-(x-.37)^2-2(z-.61)^2 has unique interior maximum 1.
    c = np.zeros((3,3)); c[0,0] = 1-.37**2-2*.61**2
    c[1,0], c[2,0], c[0,1], c[0,2] = .74, -1., 2.44, -2.
    maximum, point = polynomial_rectangle_max(c)
    assert maximum == pytest.approx(1., abs=1e-12)
    assert point == pytest.approx((.37,.61), abs=1e-10)
    # An x-flat polynomial reaches its stationary maximum on both edges.
    c[:] = 0.; c[0,0],c[0,1],c[0,2] = .91,.6,-1.
    assert polynomial_rectangle_max(c)[0] == pytest.approx(1.)


def test_spatial_comparison_does_not_hide_true_surface_initial_layer(config):
    a = DryingSystem(Grid(3), TestInputs(), question=23)
    b = DryingSystem(Grid(6), TestInputs(), question=23)
    one = reconstruct(a,0.,a.initial(),side="right")
    two = reconstruct(b,0.,b.initial(),side="right")
    diff = spatial_difference(one,two)
    assert diff["C"] > .01
    # The maximum can occur at a fine-grid breakpoint *inside* the coarse
    # surface half-cell. Both that point and the true surface are included.
    assert diff["positions"]["C"][0] >= a.grid.xi[-1]
    assert diff["C"] >= abs(one.surface()[1]-two.surface()[1])-1e-14
    assert diff["G"] == pytest.approx(0.)


def test_actual_adjacent_run_comparison_measures_time_and_event_differences(tmp_path, config):
    a,b = tmp_path/"coarse", tmp_path/"fine"
    write_run(a,config)
    write_run(b,replace(config,rtol=config.rtol/10,atol_t=config.atol_t/10,atol_c=config.atol_c/10))
    comparison = compare_runs(a,b,coverage_end=.7,system_factory=DecayCells,
                              wall_seconds=30.,max_time_points=5000)
    assert comparison["resolved"]
    assert comparison["differences"]["C"] > 0
    assert comparison["event_difference"] is not None and comparison["event_difference"] > 0
    assert comparison["initial_layer_included"]
    assert len(comparison["time_refinement_maxima"]) >= 2


def test_three_level_plan_has_independent_prescribed_changes(config):
    plan = plan_refinement_configs(config)
    assert set(plan) == {"radial","time","newton","dense","event"}
    assert [x["nr"] for x in plan["radial"]] == [3,6,12]
    assert [x["width"] for x in plan["event"]] == [.01,.005,.0025]
    assert plan["time"][2]["rtol"] == config.rtol/100
    assert all(x["nr"] == 12 for category in ("time","newton","dense") for x in plan[category])
    c = plan_refinement_configs(replace(config,route="C",nz=3,end_condition="C1"))
    assert [x["nz"] for x in c["axial"]] == [3,6,12]
    assert [(x["nr"],x["nz"]) for x in c["joint"]] == [(3,3),(6,6),(12,12)]
    assert all((x["nr"],x["nz"]) == (12,12) for category in ("time","newton","dense") for x in c[category])


def test_measured_three_level_time_category_aggregates_without_certifying_missing_categories(tmp_path, config):
    paths = []
    for i in range(3):
        cfg = replace(config, rtol=config.rtol/10**i, atol_t=config.atol_t/10**i, atol_c=config.atol_c/10**i)
        path = tmp_path/f"time_{i}"
        write_run(path,cfg,until=.4)
        paths.append(path)
    evidence = build_error_evidence(paths[-1], {"time": paths}, coverage_end=.4,
        system_factory=DecayCells, comparison_options={"wall_seconds":30.,"max_time_points":10000})
    assert "time" in evidence["categories"]
    measured = evidence["categories"]["time"]
    assert measured["levels"] == 3 and len(measured["comparisons"]) == 2
    assert measured["estimates"]["eC"] == 2*max(x["differences"]["C"] for x in measured["comparisons"])
    assert measured["estimates"]["et_ref"] is not None
    assert evidence["status"] == "ERROR_BUDGET_UNRESOLVED" and not evidence["checks_passed"]


def test_missing_categories_and_forged_certificate_fail_closed(tmp_path, config):
    src = tmp_path/"source"; write_run(src,config)
    e = build_error_evidence(src,{},system_factory=DecayCells)
    assert e["status"] == "ERROR_BUDGET_UNRESOLVED"
    assert not e["checks_passed"] and not e["refinement_verified"]
    assert e["eC"] is None and len(e["issues"]) == 5
    candidate = prepare_strict_report(src,e,tmp_path/"preparation",system_factory=DecayCells)
    assert candidate["status"] == "ERROR_BUDGET_UNRESOLVED"
    certificate = certify_strict_report(src,e,{"status":"PROVISIONAL_EVENT"},system_factory=DecayCells)
    assert certificate["status"] != "DRYING_COMPLETE"
    assert any("TEST_ONLY" in s for s in certificate["issues"])


def test_changed_numerical_source_provenance_blocks_reintegration(tmp_path, config):
    src = tmp_path/"source"; write_run(src,config)
    manifest = json.loads((src/"manifest.json").read_text())
    manifest["source"]["files"]["src/drying/integrator.py"] = "0"*64
    atomic_json(src/"manifest.json",manifest)
    with pytest.raises(RefinementError,match="numerical source"):
        refine_event(src,tmp_path/"invalid",system_factory=DecayCells)


def test_comparison_capacity_is_unresolved_not_zero_error(tmp_path, config):
    a,b = tmp_path/"a",tmp_path/"b"; write_run(a,config); write_run(b,config)
    comparison = compare_runs(a,b,system_factory=DecayCells,max_time_points=1)
    assert not comparison["resolved"]
    assert comparison["status"] == "COMPARISON_POINT_BUDGET_REACHED"


def test_suffix_gpu_failure_keeps_last_checkpoint_and_hard_exit_code(tmp_path, config, monkeypatch):
    from drying.cuda_backend import CudaBackendError
    source = tmp_path / "source"
    write_run(source, config)
    def fail_run(self, *args, **kwargs):
        raise CudaBackendError("CUDA_SOLVE_FAILED", "TEST_ONLY injected device failure")
    monkeypatch.setattr(Integrator, "run", fail_run)
    output = tmp_path / "gpu_failed_suffix"
    result = _reintegrate_suffix(source, output, before=.3, until=.7,
                                system_factory=DecayCells, wall_seconds=30.)
    manifest = json.loads((output / "manifest.json").read_text())
    checkpoint = json.loads((output / "checkpoint.json").read_text())
    assert result["status"] == "GPU_BACKEND_FAILURE" and result["exit_code"] == 1
    assert manifest["execution"]["exit_code"] == 1
    assert checkpoint["integrator"]["t"] == result["checkpoint_time"]
    assert result["new_accepted_steps"] == 0
