"""Server-executed preflight tests; CPU fixtures and mocked CUDA failures.

Writing or collecting this file does not probe a GPU. The actual GPU-required
server preflight is separate from these explicitly CPU_REFERENCE_TEST fixtures.
"""
import hashlib
import json
from pathlib import Path
import shutil
import pytest

from drying.config import RunConfig
import drying.preflight as module

REAL_ROOT=Path(__file__).resolve().parents[1]


def portable_copy(tmp_path):
    root=tmp_path/"portable"
    for rel in ["workspace/04_model_specification.md","workspace/evidence/stage05_test_only_checks.py",
                "workspace/evidence/stage05_presolve_checks.json"]:
        dst=root/rel;dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(REAL_ROOT/rel,dst)
    shutil.copytree(REAL_ROOT/"data/raw",root/"data/raw")
    (root/"configs").mkdir()
    RunConfig().to_json(root/"configs/b_q23.json")
    return root


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def test_preflight_reexecutes_original_48_checks_without_historical_mutation(tmp_path,monkeypatch):
    root=portable_copy(tmp_path);monkeypatch.setattr(module,"ROOT",root)
    historical=root/"workspace/evidence/stage05_presolve_checks.json"
    script=root/"workspace/evidence/stage05_test_only_checks.py"
    before=(digest(historical),digest(script))
    report=module.run_preflight(output=tmp_path/"preflight_result.json",require_cuda=False)
    assert report["status"]=="PASS",report["failures"]
    assert report["stage05"]["assertions_passed"]==48
    assert report["stage05"]["historical_files_unchanged"]
    assert before==(digest(historical),digest(script))
    assert len(report["stage05"]["source_mapping"])==7
    assert any(c["id"]=="ENVIRONMENT_BELOW_THRESHOLD" for c in report["stage05"]["checks"])
    assert json.loads((tmp_path/"preflight_result.json").read_text(encoding="utf-8"))["status"]=="PASS"
    assert report["mode"]=="CPU_REFERENCE_TEST" and report["gpu"]["status"]=="GPU_NOT_CHECKED"


def test_preflight_blocks_tampered_authority_before_stage05(tmp_path,monkeypatch):
    root=portable_copy(tmp_path);monkeypatch.setattr(module,"ROOT",root)
    with (root/"workspace/04_model_specification.md").open("ab") as f:f.write(b"changed")
    report=module.run_preflight(require_cuda=False)
    assert report["status"]=="FAIL" and report["authority"]["status"]=="FAIL"
    assert report["stage05"]["status"]=="NOT_RUN"


def test_preflight_rejects_source_and_config_tampering(tmp_path,monkeypatch):
    root=portable_copy(tmp_path);monkeypatch.setattr(module,"ROOT",root)
    with (root/"data/raw/environment.xlsx").open("ab") as f:f.write(b"tamper")
    (root/"configs/b_q23.json").write_text('{"nr":1}',encoding="utf-8")
    report=module.run_preflight(include_stage05=False,require_cuda=False)
    assert report["status"]=="FAIL"
    assert report["raw"]["status"]=="FAIL" and report["configs"]["status"]=="FAIL"


def test_pipeline_manifest_validates_references_and_unique_outputs(tmp_path,monkeypatch):
    root=portable_copy(tmp_path);monkeypatch.setattr(module,"ROOT",root)
    plan=root/"configs/server_first_round.json"
    item={"config":"configs/b_q23.json","out":"results/runs/EXP_TEST"}
    plan.write_text(json.dumps({"runs":[item],"note":"TEST_ONLY preflight schema test"}),encoding="utf-8")
    report=module.run_preflight(include_stage05=False,require_cuda=False)
    assert report["status"]=="PASS",report["failures"]
    assert any(c.get("kind")=="PIPELINE_PLAN" for c in report["configs"]["files"])
    plan.write_text(json.dumps({"runs":[item,item]}),encoding="utf-8")
    duplicate=module.run_preflight(include_stage05=False,require_cuda=False)
    assert duplicate["status"]=="FAIL"
    plan.write_text(json.dumps({"runs":[{**item,"config":"configs/missing.json"}]}),encoding="utf-8")
    missing=module.run_preflight(include_stage05=False,require_cuda=False)
    assert missing["status"]=="FAIL"


@pytest.mark.parametrize("error",[RuntimeError("CuPy is unavailable"),RuntimeError("CUDA driver unavailable"),
                                 RuntimeError("CUDA device 0 unavailable"),RuntimeError("CUDA float64 check failed")])
def test_required_cuda_failure_is_fail_closed_without_cpu_fallback(tmp_path,monkeypatch,error):
    root=portable_copy(tmp_path);monkeypatch.setattr(module,"ROOT",root)
    calls=[]
    def unavailable(device_id,memory_mb):
        calls.append((device_id,memory_mb))
        raise error
    def must_not_run(*args,**kwargs):
        raise AssertionError("Stage05 must not start after a required CUDA failure")
    monkeypatch.setattr(module,"_probe_cuda",unavailable)
    monkeypatch.setattr(module,"_stage05_isolated",must_not_run)
    # This invokes only the mock, never the real CUDA probe.
    report=module.run_preflight()
    assert report["status"]=="FAIL"
    assert report["mode"]=="CUDA_REQUIRED_SERVER"
    assert report["gpu"]["status"]=="FAIL" and calls==[(0,2048)]
    assert report["gpu"]["automatic_cpu_fallback"] is False
    assert report["gpu"]["devices"][0]["error"]==str(error)
    assert report["stage05"]["status"]=="NOT_RUN"


def test_cpu_reference_preflight_does_not_call_cuda_probe(tmp_path,monkeypatch):
    root=portable_copy(tmp_path);monkeypatch.setattr(module,"ROOT",root)
    def must_not_probe(*args,**kwargs):
        raise AssertionError("Explicit CPU_REFERENCE_TEST must not probe CUDA")
    monkeypatch.setattr(module,"_probe_cuda",must_not_probe)
    report=module.run_preflight(include_stage05=False,require_cuda=False)
    assert report["status"]=="PASS"
    assert report["mode"]=="CPU_REFERENCE_TEST"
    assert report["gpu"]["status"]=="GPU_NOT_CHECKED" and report["gpu"]["devices"]==[]


@pytest.mark.parametrize("metadata",[{"status":"FAIL","reason":"TEST_ONLY driver error"},
                                     {"status":"PASS"}])
def test_cuda_probe_incomplete_or_nonpass_metadata_cannot_be_promoted(tmp_path,monkeypatch,metadata):
    root=portable_copy(tmp_path);monkeypatch.setattr(module,"ROOT",root)
    monkeypatch.setattr(module,"_probe_cuda",lambda *args,**kwargs:metadata)
    report=module.run_preflight(include_stage05=False)
    assert report["status"]=="FAIL" and report["gpu"]["status"]=="FAIL"


def test_campaign_manifest_is_not_parsed_as_runconfig(tmp_path,monkeypatch):
    root=portable_copy(tmp_path);monkeypatch.setattr(module,"ROOT",root)
    for path in (REAL_ROOT/"configs").glob("*.json"):
        shutil.copy2(path,root/"configs"/path.name)
    report=module.run_preflight(include_stage05=False,require_cuda=False)
    assert report["status"]=="PASS",report["failures"]
    plan=next(r for r in report["configs"]["files"] if r.get("kind")=="CAMPAIGN_PLAN")
    assert plan["run_count"]==67
    assert plan["path"]=="configs/server_full.json"


def test_campaign_gpu_override_probes_selected_device_not_unused_source_device(tmp_path,monkeypatch):
    root=portable_copy(tmp_path);monkeypatch.setattr(module,"ROOT",root)
    calls=[]
    def fail_probe(device_id,memory_mb):
        calls.append((device_id,memory_mb))
        raise RuntimeError("TEST_ONLY selected-device failure")
    monkeypatch.setattr(module,"_probe_cuda",fail_probe)
    report=module.run_preflight(include_stage05=False,
        cuda_requests_override=[{"cuda_device":1,"gpu_memory_mb":4096}])
    assert calls==[(1,4096)]
    assert report["status"]=="FAIL"
    assert report["gpu"]["request_source"]=="EXPLICIT_CAMPAIGN_HARDWARE"


@pytest.mark.parametrize("override",[[],{},[{"cuda_device":True,"gpu_memory_mb":2048}],
    [{"cuda_device":0,"gpu_memory_mb":0}],[{"cuda_device":0,"gpu_memory_mb":2048,"extra":1}]])
def test_campaign_gpu_override_invalid_shape_blocks_probe(tmp_path,monkeypatch,override):
    root=portable_copy(tmp_path);monkeypatch.setattr(module,"ROOT",root)
    def forbidden(*args,**kwargs):
        raise AssertionError("Invalid override must not reach device probe")
    monkeypatch.setattr(module,"_probe_cuda",forbidden)
    report=module.run_preflight(include_stage05=False,cuda_requests_override=override)
    assert report["status"]=="FAIL"
    assert report["gpu"]["status"]=="NOT_RUN"
