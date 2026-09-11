"""CPU campaign routing checks; these are not physical model validation."""
from copy import deepcopy
from dataclasses import replace
import pytest

from drying import campaign_analysis as analysis
from drying.cpu_campaign import CPU_FIELDS, ROOT, expand_cpu_campaign
from drying.campaign_plan import expand_campaign
from drying.config import RunConfig


def test_full_cpu_plan_preserves_all_numerics_and_rekeys_every_reference():
    plan = ROOT / "configs/server_full.json"
    original = expand_campaign(plan)
    cpu = expand_cpu_campaign(plan)
    assert len(cpu["runs"]) == 67 and len(cpu["comparisons"]) == 14
    keys = {r["run_key"] for r in cpu["runs"]}
    mapping = cpu["cpu_key_mapping"]
    for old, new in zip(original["runs"], cpu["runs"]):
        assert new["run_key"] == mapping[old["run_key"]]
        assert new["config_fingerprint"] == RunConfig.from_dict(new["config"]).fingerprint
        assert old["config_fingerprint"] != new["config_fingerprint"]
        assert {k: v for k, v in old["config"].items() if k not in CPU_FIELDS} == {k: v for k, v in new["config"].items() if k not in CPU_FIELDS}
    for case in cpu["cases"].values():
        assert case["base_run"] in keys and case["reference_run"] in keys
        assert all(key in keys for levels in case["categories"].values() for key in levels)
    for item in cpu["comparisons"]:
        assert item["left"] in keys and item["right"] in keys
    for old, new in zip(original["source_configs"], cpu["source_configs"]):
        assert new["source_config_fingerprint"] == old["source_config_fingerprint"]
        assert new["file_sha256"] == old["file_sha256"]
        assert new["run_key"] in keys
    assert cpu["plan_fingerprint"] != original["plan_fingerprint"]
    assert expand_campaign(plan) == original


def cpu_manifest():
    return {"execution": {**{k: v for k, v in CPU_FIELDS.items() if k != "linear_backend"},
        "device": "CPU_REFERENCE", "attempts": [{"linear_backend": {"backend": "CPU_REFERENCE", "gpu_used": False,
            "dtype": "float64", "purpose": "EXPLICIT_NONPRODUCTION_REFERENCE_NOT_FALLBACK"}}]}}


def test_cpu_analysis_requires_actual_cpu_metadata():
    config = RunConfig(**CPU_FIELDS)
    analysis._require_analysis_backend(config, cpu_manifest(), True)
    for bad in ({}, {"execution": {}}):
        with pytest.raises(ValueError):
            analysis._require_analysis_backend(config, bad, True)
    bad = deepcopy(cpu_manifest())
    bad["execution"]["attempts"][0]["linear_backend"]["gpu_used"] = True
    with pytest.raises(ValueError, match="TELEMETRY"):
        analysis._require_analysis_backend(config, bad, True)
    with pytest.raises(ValueError, match="IDENTITY"):
        analysis._require_analysis_backend(replace(config, linear_backend="CUDA"), cpu_manifest(), True)


def test_default_analysis_still_enforces_cuda(monkeypatch):
    called = []
    monkeypatch.setattr(analysis, "_require_cuda_evidence", lambda *args: called.append(args))
    cfg = RunConfig()
    analysis._require_analysis_backend(cfg, {})
    assert called == [(cfg, {})]
