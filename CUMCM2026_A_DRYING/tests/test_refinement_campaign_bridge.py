"""SERVER ONLY: checkpoint bridge regression tests; not executed locally.

Mock phase tests establish scheduling/budget contracts only. The final test
uses an explicitly injected stationary TEST_ONLY system and real accepted
steps; it cannot establish physical-model or CUDA validation.
"""
from copy import deepcopy
from dataclasses import asdict, replace
import json
import math

import pytest

from drying.config import RunConfig
from drying.cuda_backend import CudaBackendError
from drying.integrator import Settings
from drying.refinement import (_advance_checkpoint_bridge, _reintegrate_suffix,
                               _validate_category, RefinementError)


class Clock:
    def __init__(self):
        self.now = 0.

    def __call__(self):
        return self.now


class ScheduledSolver:
    """No equation solver: records the caller's time/step policy."""
    algorithm = "MOCK_SCHEDULING_ONLY"

    def __init__(self, settings, clock, costs=(1., 1.), fail_on=None):
        self.cfg = settings
        self.t = 0.
        self.h_next = settings.h0
        self.stats = {"accepted": 40}
        self.clock = clock
        self.costs = costs
        self.fail_on = fail_on
        self.calls = []

    def run(self, until, *, callback, forced_nodes, wall_seconds):
        self.calls.append({"from": self.t, "until": until, "settings": asdict(self.cfg),
                           "forced_nodes": list(forced_nodes), "wall_seconds": wall_seconds})
        if self.fail_on == len(self.calls):
            raise CudaBackendError("CUDA_OUT_OF_MEMORY", "mock failure, no GPU operation")
        start = self.t
        needed = int(math.ceil((until-start)/self.cfg.hmax))
        taken = min(needed, self.cfg.max_steps)
        for step in range(taken):
            previous = self.t
            self.t = until if step+1 == needed else start + (until-start)*(step+1)/needed
            self.stats["accepted"] += 1
            callback(previous, [], self.t, [], {"E": 0., "residual": 0., "linear": 0.}, [])
        self.clock.now += self.costs[min(len(self.calls)-1, len(self.costs)-1)]
        return {"status": "COMPLETED_INTERVAL" if taken == needed else "STEP_BUDGET_REACHED",
                "t": self.t, "stats": self.stats, "failure": None}


def _invoke(solver, source, local, clock, *, before, until, wall=30., persisted=None):
    persisted = [] if persisted is None else persisted
    def checkpoint():
        persisted.append((solver.t, len(solver.calls), solver.cfg.hmax))
        return {"kind": "MOCK_CHECKPOINT_NOT_NUMERICAL_EVIDENCE", "time": solver.t}
    return _advance_checkpoint_bridge(solver, source, local, before=before, until=until,
        forced_nodes=[before, until], wall_seconds=wall, started=0.,
        callback=lambda *args, **kwargs: None, persist_bridge=checkpoint, clock=clock)


def test_distant_checkpoint_uses_source_steps_before_local_tiny_steps():
    source = Settings(h0=.1, hmax=60., max_steps=1000, wall_seconds=30.)
    local = replace(source, hmax=.00125, h0=.00125)
    clock = Clock(); solver = ScheduledSolver(source, clock); persisted = []
    result = _invoke(solver, source, local, clock, before=1000., until=1000.01, persisted=persisted)
    assert result["status"] == "COMPLETED_INTERVAL"
    assert len(solver.calls) == 2
    assert solver.calls[0]["settings"]["hmax"] == 60.
    assert solver.calls[0]["until"] == solver.calls[1]["from"] == 1000.
    assert solver.calls[1]["settings"]["hmax"] == .00125
    assert persisted == [(1000., 1, 60.)]
    assert result["accepted_this_call"] < 1000
    assert solver.cfg == local
    for key in ("rtol", "atol_t", "atol_c", "newton_tol", "linear_tol", "linear_backend", "cuda_device"):
        assert solver.calls[0]["settings"][key] == solver.calls[1]["settings"][key]


def test_two_phases_share_one_accepted_step_budget():
    source = Settings(h0=.1, hmax=1., max_steps=6, wall_seconds=30.)
    local = replace(source, hmax=.5)
    clock = Clock(); solver = ScheduledSolver(source, clock)
    result = _invoke(solver, source, local, clock, before=4., until=6.)
    assert result["status"] == "STEP_BUDGET_REACHED"
    assert solver.calls[0]["settings"]["max_steps"] == 6
    assert solver.calls[1]["settings"]["max_steps"] == 2
    assert result["accepted_this_call"] == 6
    assert [p["accepted_steps_committed"] for p in result["phase_diagnostics"]] == [4, 2]


def test_local_phase_cannot_reset_consumed_wall_budget():
    source = Settings(hmax=1., max_steps=100, wall_seconds=10.)
    local = replace(source, hmax=.1)
    clock = Clock(); solver = ScheduledSolver(source, clock, costs=(10.,))
    result = _invoke(solver, source, local, clock, before=1., until=2., wall=10.)
    assert result["status"] == "WALL_BUDGET_REACHED"
    assert len(solver.calls) == 1
    assert result["phase_diagnostics"][1]["accepted_steps_committed"] == 0


def test_bridge_gpu_failure_prevents_local_phase_and_preserves_hard_status():
    source = Settings(hmax=1., max_steps=100)
    clock = Clock(); solver = ScheduledSolver(source, clock, fail_on=1); persisted = []
    result = _invoke(solver, source, replace(source,hmax=.1), clock,
                     before=1., until=2., persisted=persisted)
    assert result["status"] == "GPU_BACKEND_FAILURE"
    assert len(solver.calls) == 1 and persisted == []
    assert result["phase_diagnostics"][1]["status"] == "NOT_RUN"


def test_existing_endpoint_needs_no_bridge_solve_but_still_persists_checkpoint():
    source = Settings(hmax=1., max_steps=100)
    clock = Clock(); solver = ScheduledSolver(source, clock); persisted = []
    result = _invoke(solver, source, replace(source,hmax=.1), clock,
                     before=0., until=.2, persisted=persisted)
    assert result["status"] == "COMPLETED_INTERVAL"
    assert persisted == [(0., 0, 1.)]
    assert len(solver.calls) == 1
    assert result["phase_diagnostics"][0]["accepted_steps_committed"] == 0


def test_unpersisted_bridge_cannot_start_local_reintegration():
    source = Settings(hmax=1., max_steps=100)
    clock = Clock(); solver = ScheduledSolver(source, clock)
    def failed_checkpoint():
        raise OSError("mock write failure")
    result = _advance_checkpoint_bridge(solver,source,replace(source,hmax=.1),
        before=1.,until=2.,wall_seconds=30.,started=0.,callback=lambda *args,**kwargs:None,
        persist_bridge=failed_checkpoint,clock=clock)
    assert result["status"] == "EXECUTION_EXCEPTION"
    assert "BRIDGE_CHECKPOINT_FAILED" in result["failure"]
    assert len(solver.calls) == 1


def _event_records():
    configs, manifests = [], []
    for width in (.01,.005,.0025):
        cfg=RunConfig(nr=2,tmax=1.,h0=.001,hmax=width/2,linear_backend="CPU_REFERENCE",execution_purpose="TEST_ONLY")
        configs.append(cfg)
        manifests.append({"refinement": {"method":"ACCEPTED_CHECKPOINT_REINTEGRATION",
            "new_accepted_steps":12,"bridge_accepted_steps":10,"local_accepted_steps":2,
            "target_width":width,"local_hmax":width/2,
            "phase_diagnostics":[{"phase":"CHECKPOINT_BRIDGE","status":"COMPLETED_INTERVAL"},
                {"phase":"LOCAL_REINTEGRATION","status":"COMPLETED_INTERVAL",
                 "accepted_steps_committed":2,"hmax":width/2,"max_h":width/2,"end":.5}]}})
    return configs,manifests


def test_bridge_steps_cannot_masquerade_as_event_refinement():
    configs, manifests = _event_records()
    _validate_category("event",configs,manifests)
    failed=deepcopy(manifests)
    failed[1]["refinement"]["local_accepted_steps"]=0
    failed[1]["refinement"]["phase_diagnostics"][1].update(status="NOT_RUN",accepted_steps_committed=0)
    with pytest.raises(RefinementError,match="bridge alone"):
        _validate_category("event",configs,failed)
    too_large=deepcopy(manifests)
    too_large[1]["refinement"]["phase_diagnostics"][1]["max_h"]=.1
    with pytest.raises(RefinementError,match="exceeds.*hmax"):
        _validate_category("event",configs,too_large)


def test_real_stationary_bridge_persists_accepted_history_before_local_steps(tmp_path):
    # SERVER ONLY: a small real regression with a 1000-second checkpoint gap.
    # No evaporation/physics conclusion can be inferred from this injected ODE.
    import numpy as np
    from scipy.sparse import diags
    from types import SimpleNamespace
    from test_refinement import DecayCells, write_run
    from drying.trajectory import Trajectory, fingerprint

    class StationaryCells(DecayCells):
        def evaluate(self,t,y,side="point",jacobian=True):
            return SimpleNamespace(f=np.zeros_like(y),
                jac=diags(np.zeros_like(y),format="csc") if jacobian else None)

    cfg=RunConfig(nr=2,tmax=1200.,h0=.1,hmax=60.,max_steps=1000,wall_seconds=30.,
                  linear_backend="CPU_REFERENCE",execution_purpose="TEST_ONLY")
    source=tmp_path/"source"
    write_run(source,cfg,factory=StationaryCells,until=1200.,checkpoint_interval=1000000)
    original=fingerprint(Trajectory(source/"trajectory",verify=True).index)
    checkpoint_before=(source/"checkpoint.json").read_bytes()
    output=tmp_path/"bridged"
    result=_reintegrate_suffix(source,output,before=1000.,until=1000.01,hmax=.00125,
        width=.0025,system_factory=StationaryCells,wall_seconds=30.)
    assert result["status"]=="COMPLETED_INTERVAL"
    manifest=json.loads((output/"manifest.json").read_text())
    phases=manifest["refinement"]["phase_diagnostics"]
    assert phases[0]["hmax"]==60. and phases[0]["max_h"]>.00125
    assert phases[1]["hmax"]==.00125 and phases[1]["start"]==1000.
    assert manifest["refinement"]["bridge_accepted_steps"]>0
    assert manifest["refinement"]["local_accepted_steps"]>0
    assert result["new_accepted_steps"]<1000
    bridge=json.loads((output/"checkpoints/bridge_endpoint.json").read_text())
    assert bridge["integrator"]["t"]==1000.
    assert bridge["integrator"]["settings"]["hmax"]==60.
    trajectory=Trajectory(output/"trajectory",verify=True)
    accepted={t: y for t,y in trajectory.iter_states()}
    np.testing.assert_array_equal(accepted[1000.],bridge["integrator"]["y"])
    np.testing.assert_array_equal(accepted[bridge["integrator"]["t_prev"]],bridge["integrator"]["y_prev"])
    assert manifest["refinement"]["injected_test_system"] is True
    assert fingerprint(Trajectory(source/"trajectory",verify=True).index)==original
    assert (source/"checkpoint.json").read_bytes()==checkpoint_before
    assert json.loads((output/"diagnostics.json").read_text())["checks_passed"] is False
