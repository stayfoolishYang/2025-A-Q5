"""Portable preflight failures and real isolated Stage05 rerun."""
import hashlib
import json
from pathlib import Path
import shutil

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
    report=module.run_preflight(output=tmp_path/"preflight_result.json")
    assert report["status"]=="PASS",report["failures"]
    assert report["stage05"]["assertions_passed"]==48
    assert report["stage05"]["historical_files_unchanged"]
    assert before==(digest(historical),digest(script))
    assert len(report["stage05"]["source_mapping"])==7
    assert any(c["id"]=="ENVIRONMENT_BELOW_THRESHOLD" for c in report["stage05"]["checks"])
    assert json.loads((tmp_path/"preflight_result.json").read_text(encoding="utf-8"))["status"]=="PASS"


def test_preflight_blocks_tampered_authority_before_stage05(tmp_path,monkeypatch):
    root=portable_copy(tmp_path);monkeypatch.setattr(module,"ROOT",root)
    with (root/"workspace/04_model_specification.md").open("ab") as f:f.write(b"changed")
    report=module.run_preflight()
    assert report["status"]=="FAIL" and report["authority"]["status"]=="FAIL"
    assert report["stage05"]["status"]=="NOT_RUN"


def test_preflight_rejects_source_and_config_tampering(tmp_path,monkeypatch):
    root=portable_copy(tmp_path);monkeypatch.setattr(module,"ROOT",root)
    with (root/"data/raw/environment.xlsx").open("ab") as f:f.write(b"tamper")
    (root/"configs/b_q23.json").write_text('{"nr":1}',encoding="utf-8")
    report=module.run_preflight(include_stage05=False)
    assert report["status"]=="FAIL"
    assert report["raw"]["status"]=="FAIL" and report["configs"]["status"]=="FAIL"


def test_pipeline_manifest_validates_references_and_unique_outputs(tmp_path,monkeypatch):
    root=portable_copy(tmp_path);monkeypatch.setattr(module,"ROOT",root)
    plan=root/"configs/server_first_round.json"
    item={"config":"configs/b_q23.json","out":"results/runs/EXP_TEST"}
    plan.write_text(json.dumps({"runs":[item],"note":"TEST_ONLY preflight schema test"}),encoding="utf-8")
    report=module.run_preflight(include_stage05=False)
    assert report["status"]=="PASS",report["failures"]
    assert any(c.get("kind")=="PIPELINE_PLAN" for c in report["configs"]["files"])
    plan.write_text(json.dumps({"runs":[item,item]}),encoding="utf-8")
    duplicate=module.run_preflight(include_stage05=False)
    assert duplicate["status"]=="FAIL"
    plan.write_text(json.dumps({"runs":[{**item,"config":"configs/missing.json"}]}),encoding="utf-8")
    missing=module.run_preflight(include_stage05=False)
    assert missing["status"]=="FAIL"
