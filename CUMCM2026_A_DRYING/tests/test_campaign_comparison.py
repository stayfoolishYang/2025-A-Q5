"""TEST_ONLY synthetic postprocessing tests; no PDE, GPU, or solver invocation.

These tests are authored for the server suite and are not run on the local PC.
"""
from dataclasses import replace
from types import SimpleNamespace
import json

import numpy as np
import pytest

from drying.config import RunConfig
from drying import campaign_comparison as campaign
from drying.reconstruction import Reconstruction


def node_reconstruction(route="B", radius=.02, xi=(0., .4, 1.), z=(0., .05, .125), values=None):
    rec = object.__new__(Reconstruction)
    rec.system = SimpleNamespace(grid=SimpleNamespace(route=route))
    rec.R = radius
    rec.xi = np.asarray(xi, float)
    rec.z = np.array([0.]) if route == "B" else np.asarray(z, float)
    rec.nodes = np.empty((len(rec.xi), len(rec.z), 2))
    rec.nodes[...] = (310., .2) if values is None else values
    pos = np.unravel_index(np.argmax(rec.nodes[..., 1]), rec.nodes.shape[:2])
    rec.max_C = float(rec.nodes[pos][1])
    rec.max_position = (float(rec.xi[pos[0]]), float(rec.z[pos[1]]))
    return rec


def test_physical_radius_comparison_does_not_compare_unlike_xi_or_extrapolate():
    one = node_reconstruction(radius=.02, xi=(0., .2, .5, 1.))
    two = node_reconstruction(radius=.01)
    # Physical breakpoints coincide on [0,.01], while normalized xi differs.
    # Thus both prescribed reconstructions agree on the whole common domain.
    one.nodes[:, 0, 0] = 310. + (one.R * one.xi) ** 2 * 1000.
    two.nodes[:, 0, 0] = 310. + (two.R * two.xi) ** 2 * 1000.
    result = campaign.midplane_difference(one, two)
    assert result["common_radius_m"] == .01
    assert result["positions"]["T"]["r_m"] <= .01
    assert result["T"] == pytest.approx(0., abs=1e-11)
    with pytest.raises(campaign.CampaignComparisonError, match="OUTSIDE_DOMAIN"):
        campaign._physical_query(two, .01001)


def test_radial_reconstruction_difference_peaks_between_union_breakpoints():
    left = node_reconstruction(xi=(0., .8, 1.))
    right = node_reconstruction(xi=(0., .2, 1.))
    left.nodes[:, 0, 0] = (310., 310.64, 310.84)
    right.nodes[:, 0, 0] = (310., 310.04, 310.84)
    # On .2 < xi < .8 the difference is (xi-.2)*(xi-.8),
    # zero at both breakpoints but -.09 at the interior stationary point.
    result = campaign.midplane_difference(left, right)
    assert result["T"] == pytest.approx(.09, abs=1e-11)
    assert result["positions"]["T"]["r_m"] == pytest.approx(.01, abs=1e-11)


def test_B_C_fields_are_midplane_but_G_and_axial_use_whole_C_domain():
    b, c = node_reconstruction(), node_reconstruction("C")
    c.nodes[:, -1, 0] += 2.
    c.nodes[:, -1, 1] += .03
    c.max_C, c.max_position = .23, (0., .125)
    delta = campaign.midplane_difference(b, c)
    assert delta["T"] == 0.
    assert delta["C"] == 0.
    assert delta["G"] == pytest.approx(.03)
    axial = campaign.axial_departure(c)
    assert axial["T"]["value"] == 2.
    assert axial["C"]["value"] == pytest.approx(.03)
    assert campaign.axial_departure(b) is None


class FakeTrajectory:
    def __init__(self, end=10.):
        self.start_time, self.end_time = 0., end
        self.times = [0., end / 2., end]
        self.index = {"identity": {"synthetic": True}, "times": self.times}

    def iter_states(self):
        yield from ((t, np.array([t])) for t in self.times)

    def at(self, t):
        assert self.start_time <= t <= self.end_time
        return np.array([t])


def event(at=None, status=None):
    return {"status": status or ("NO_EVENT" if at is None else "PROVISIONAL_EVENT"),
            "t_hat": at, "earliest_verified": True, "retention_verified": at is not None}


def install_runs(monkeypatch, tmp_path, left_cfg=None, right_cfg=None,
                 left_event=None, right_event=None, input_ids=("same", "same"), end=10., reconstruct_fn=None):
    left_cfg = left_cfg or RunConfig(linear_backend="CPU_REFERENCE")
    right_cfg = right_cfg or replace(left_cfg, route="C", nz=3, end_condition="C1")
    runs, configs = {}, (left_cfg, right_cfg)
    calls = []
    for i, label in enumerate(("left", "right")):
        path = tmp_path / label
        path.mkdir()
        (path / "manifest.json").write_text("{}", encoding="utf-8")
        cfg = configs[i]
        system = SimpleNamespace(label=label, question=cfg.question, geometry=cfg.geometry,
                                 grid=SimpleNamespace(route=cfg.route),
                                 inputs=SimpleNamespace(nodes=lambda **kwargs: np.array([2.])))
        trajectory = FakeTrajectory(end)
        manifest = {"identity": {"input": input_ids[i], "code": "recorded-source"}, "source": {}}
        runs[label] = (path, cfg, manifest, system, trajectory)
    monkeypatch.setattr(campaign, "_load_run", lambda p: runs[str(p)])
    monkeypatch.setattr(campaign, "_core_hashes", lambda m: {"reconstruction.py": "same-core"})
    mapping = {"left": event() if left_event is None else left_event,
               "right": event() if right_event is None else right_event}
    monkeypatch.setattr(campaign, "scan_events", lambda s, t: mapping[s.label])

    def rebuild(s, t, y, side="point"):
        calls.append((s.label, t, side))
        if reconstruct_fn is not None:
            return reconstruct_fn(s, t, side)
        return node_reconstruction(s.grid.route)

    monkeypatch.setattr(campaign, "reconstruct", rebuild)
    return runs, calls


def test_B_C_earlier_event_caps_main_window_and_C_is_denominator(monkeypatch, tmp_path):
    _, calls = install_runs(monkeypatch, tmp_path, left_event=event(8.), right_event=event(6.))
    output = tmp_path / "raw-comparison.json"
    result = campaign.compare_campaign_runs("left", "right", out_path=output)
    assert result["status"] == "COMPARISON_MEASURED"
    assert result["main_window"]["end_seconds"] == 6.
    assert max(t for _, t, _ in calls) <= 6.
    assert result["event_difference"]["absolute_seconds"] == 2.
    assert result["event_difference"]["relative_to_C"] == pytest.approx(2. / 6.)
    assert result["event_difference"]["C_reference_side"] == "right"
    assert json.loads(output.read_text())["run_identities"][0]["input_fingerprint"] == "same"
    assert len(result["time_refinement_maxima"]) >= 2
    assert any(t == 1. for _, t, _ in calls)
    assert {side for _, t, side in calls if t == 2.} == {"left", "right"}


def test_one_event_and_no_event_keep_difference_undefined(monkeypatch, tmp_path):
    install_runs(monkeypatch, tmp_path, left_event=event(7.))
    result = campaign.compare_campaign_runs("left", "right")
    assert result["main_window"]["end_seconds"] == 7.
    assert result["event_difference"]["absolute_seconds"] is None
    assert result["event_difference"]["relative_to_C"] is None


def test_no_event_uses_common_coverage_not_zero_difference_for_missing_event(monkeypatch, tmp_path):
    install_runs(monkeypatch, tmp_path)
    result = campaign.compare_campaign_runs("left", "right")
    assert result["main_window"]["end_seconds"] == 10.
    assert result["event_difference"]["status"] == "EVENT_DIFFERENCE_UNDEFINED"
    assert result["resolved"]


def test_different_inputs_rejected_for_cross_route_but_allowed_same_route(monkeypatch, tmp_path):
    cfg = RunConfig(linear_backend="CPU_REFERENCE")
    runs, _ = install_runs(monkeypatch, tmp_path, input_ids=("S0", "S1"))
    result = campaign.compare_campaign_runs("left", "right")
    assert result["status"] == "COMPARISON_UNRESOLVED"
    assert result["differences"] is None
    old = runs["right"]
    new_cfg = replace(cfg, scenario="S1")
    old[3].grid.route = "B"
    runs["right"] = (old[0], new_cfg, old[2], old[3], old[4])
    result = campaign.compare_campaign_runs("left", "right")
    assert result["resolved"]
    assert result["comparison_kind"] == "SAME_ROUTE_INPUT_SENSITIVITY"
    assert result["config_differences"]["scenario"] == ["S0", "S1"]


def test_same_route_q4_fixed_moving_actual_radius_sensitivity(monkeypatch, tmp_path):
    fixed = RunConfig(question=4, linear_backend="CPU_REFERENCE")
    moving = replace(fixed, geometry="moving")

    def rebuild(system, t, side):
        return node_reconstruction(radius=.02 if system.label == "left" else .02 - .001 * t)

    install_runs(monkeypatch, tmp_path, fixed, moving, reconstruct_fn=rebuild)
    result = campaign.compare_campaign_runs("left", "right")
    assert result["resolved"]
    assert result["main_window"]["common_radius_min_m"] == pytest.approx(.01)
    assert result["differences"] == {"T": 0., "C": 0., "G": 0.}


def test_unknown_event_classification_is_not_treated_as_no_event(monkeypatch, tmp_path):
    install_runs(monkeypatch, tmp_path, right_event=event(status="EVENT_UNRESOLVED"))
    result = campaign.compare_campaign_runs("left", "right")
    assert result["status"] == "EVENT_WINDOW_UNRESOLVED"
    assert not result["resolved"]
    assert result["differences"] is not None


def test_point_budget_does_not_create_zero_evidence(monkeypatch, tmp_path):
    install_runs(monkeypatch, tmp_path)
    result = campaign.compare_campaign_runs("left", "right", max_time_points=1)
    assert result["status"] == "COMPARISON_POINT_BUDGET_REACHED"
    assert result["differences"] is None
    assert result["samples"] == 0


def test_no_midpoint_refinement_is_explicitly_unresolved(monkeypatch, tmp_path):
    install_runs(monkeypatch, tmp_path)
    result = campaign.compare_campaign_runs("left", "right", max_time_refinements=0)
    assert result["status"] == "TIME_COMPARISON_UNRESOLVED"
    assert result["time_coverage_complete"]
    assert not result["time_stable"]


def test_provenance_failure_returns_unresolved_json(monkeypatch):
    def fail(_):
        raise ValueError("PROVENANCE_UNRESOLVED: changed source")
    monkeypatch.setattr(campaign, "_load_run", fail)
    result = campaign.compare_campaign_runs("left", "right")
    assert not result["resolved"]
    assert result["differences"] is None
    assert "PROVENANCE_UNRESOLVED" in result["issues"][0]


def test_wall_budget_exhaustion_is_explicit_before_loading(monkeypatch):
    ticks = [-1.]
    def clock():
        ticks[0] += 1.
        return ticks[0]
    monkeypatch.setattr(campaign.time, "perf_counter", clock)
    result = campaign.compare_campaign_runs("left", "right", wall_seconds=.1)
    assert result["status"] == "COMPARISON_WALL_BUDGET_REACHED"
    assert result["differences"] is None


def test_C_reference_is_identified_when_C_is_left(monkeypatch, tmp_path):
    c = RunConfig(route="C", nz=3, end_condition="C1", linear_backend="CPU_REFERENCE")
    b = replace(c, route="B", nz=1, end_condition="C0")
    install_runs(monkeypatch, tmp_path, c, b, left_event=event(4.), right_event=event(6.))
    result = campaign.compare_campaign_runs("left", "right")
    assert result["event_difference"]["relative_to_C"] == pytest.approx(.5)
    assert result["event_difference"]["C_reference_side"] == "left"


@pytest.mark.parametrize("budgets", [{"wall_seconds": 0}, {"max_time_points": True},
                                    {"max_time_refinements": -1}])
def test_invalid_resource_budgets_rejected(budgets):
    with pytest.raises(ValueError):
        campaign.compare_campaign_runs("left", "right", **budgets)
