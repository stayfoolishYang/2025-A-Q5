"""True-attachment input contract and independent interpolation anchors."""
from dataclasses import replace
from pathlib import Path
import math
import shutil

import numpy as np
import pytest

from drying.config import RunConfig
from drying.inputs import Inputs, InputError, InputHorizonError

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"


@pytest.fixture(scope="module")
def inputs():
    return Inputs(RAW)


def test_units_exact_anchors_and_source_identity(inputs):
    x = inputs.at(0)
    assert x.T_inf == 301.15
    assert x.C_eq == 0.01963
    assert x.R == 0.02
    assert inputs.at(1800).T_inf == 41.513 + 273.15
    assert inputs.at(259200, question=4, geometry="moving").R == pytest.approx(0.01198, abs=1e-17)
    assert len(inputs.hashes) == 6
    assert len(inputs.fingerprint) == 64


def test_linear_environment_and_exact_jump_sides(inputs):
    a, b = inputs.at(0), inputs.at(60)
    m = inputs.at(30)
    assert m.T_inf == pytest.approx((a.T_inf + b.T_inf)/2, abs=1e-13)
    assert m.C_eq == pytest.approx((a.C_eq + b.C_eq)/2, abs=1e-16)
    assert inputs.at(14400).T_inf == 50.165 + 273.15
    assert inputs.at(14400, side="left").C_eq == 0.04986
    right = inputs.at(14400, side="right")
    assert right.T_inf == pytest.approx(49.998934426229508 + 273.15, abs=1e-12)
    assert right.C_eq == pytest.approx(0.049987540983606557, abs=1e-16)
    assert inputs.at(14401) == right
    assert inputs.window_count == 61
    assert inputs.node_kind(14400) == "JUMP"


def test_s1_and_approved_sample_windows():
    s1 = Inputs(RAW, scenario="S1")
    assert s1.at(14400) == s1.at(20000)
    assert s1.node_kind(14400) == "KINK"
    wide = Inputs(RAW, window_start_h=2.5)
    narrow = Inputs(RAW, window_start_h=3.5)
    assert (wide.window_count, narrow.window_count) == (91, 31)
    assert wide.at(15000).T_inf == pytest.approx(50.0049450549451 + 273.15, abs=1e-12)
    assert narrow.at(15000).C_eq == pytest.approx(0.0499887096774194, abs=1e-16)
    assert len({s1.fingerprint, wide.fingerprint, narrow.fingerprint}) == 3


def test_radius_linear_sides_and_horizon(inputs):
    kw = {"question": 4, "geometry": "moving"}
    for i in [1, 5, 90, 143]:
        t = inputs.radius_times[i]
        l, r = inputs.at(t, side="left", **kw), inputs.at(t, side="right", **kw)
        assert l.R == pytest.approx(r.R, abs=1e-17)
        assert l.Rdot == (inputs.radius_m[i]-inputs.radius_m[i-1])/1800
        assert r.Rdot == (inputs.radius_m[i+1]-inputs.radius_m[i])/1800
        mid = inputs.at(t+900, **kw)
        assert mid.R == pytest.approx((inputs.radius_m[i]+inputs.radius_m[i+1])/2, abs=1e-17)
    with pytest.raises(InputHorizonError):
        inputs.at(259201, **kw)
    hold = Inputs(RAW, radius_tail="HOLD")
    assert hold.at(259201, **kw).R == 0.01198
    assert hold.at(259201, **kw).Rdot == 0
    assert inputs.at(500000).R == 0.02


def test_pchip_is_distinct_monotone_and_has_consistent_derivative(inputs):
    p = Inputs(RAW, radius_method="pchip")
    kw = {"question": 4, "geometry": "moving"}
    times = np.linspace(0, 259200, 3001)
    values = np.array([p.at(t, **kw).R for t in times])
    assert values.min() > 0
    assert np.max(np.diff(values)) <= 2e-16
    differences = [abs(p.at(float(t), **kw).R - inputs.at(float(t), **kw).R) for t in times]
    assert max(differences) > 1e-8
    for t in [700., 2350., 64300.]:
        delta = 0.01
        fd = (p.at(t+delta, **kw).R-p.at(t-delta, **kw).R)/(2*delta)
        assert p.at(t, **kw).Rdot == pytest.approx(fd, rel=1e-6, abs=1e-14)
    assert p.fingerprint != inputs.fingerprint


def test_nodes_and_invalid_times(inputs):
    n = inputs.nodes(question=4, geometry="moving")
    assert n[0] == 60 and n[-1] == 259200
    assert np.all(np.diff(n) > 0)
    assert len(n) == 376
    assert inputs.node_kind(1) == "NONE"
    for t in [-1, math.inf, math.nan]:
        with pytest.raises(InputError):
            inputs.at(t)
    with pytest.raises(InputError):
        inputs.at(1, side="guess")


def test_corrupted_portable_copy_rejected(tmp_path):
    for name in ["environment.xlsx", "source_manifest.json"]:
        shutil.copyfile(RAW/name, tmp_path/name)
    with (tmp_path/"environment.xlsx").open("ab") as f:
        f.write(b"changed")
    with pytest.raises(InputError, match="hash mismatch"):
        Inputs(tmp_path)


def test_config_roundtrip_and_finite_contract(tmp_path):
    c = RunConfig()
    c.to_json(tmp_path/"config.json")
    assert RunConfig.from_json(tmp_path/"config.json") == c
    assert RunConfig.from_dict(c.as_dict()).fingerprint == c.fingerprint
    for change in [{"tmax": math.inf}, {"wall_seconds": 0}, {"nr": 1}, {"nz": 2}, {"hmax": 61},
                   {"geometry": "moving"}, {"question": 4, "geometry": "moving", "tmax": 300000},
                   {"production_eligible": True}, {"test_case": "MMS"}, {"scenario": "S1", "window_start_h": 3.5}]:
        with pytest.raises(ValueError):
            replace(c, **change)
    with pytest.raises(ValueError, match="unknown fields"):
        RunConfig.from_dict({"typo": 1})
    explicit = RunConfig.from_dict({"question": 4, "geometry": "moving", "tmax": 300000, "radius_tail": "R_EXT_HOLD"})
    assert explicit.radius_tail == "HOLD"
    assert replace(c, route="C", nz=3, end_condition="C1").route == "C"
    assert c.linear_backend=='CUDA'
    for change in [{'linear_backend':'auto'}, {'cuda_device':-1}, {'cuda_device':True},
                   {'gpu_memory_mb':0}, {'linear_backend':'CPU_REFERENCE','execution_purpose':'PRODUCTION'}]:
        with pytest.raises(ValueError): replace(c,**change)
