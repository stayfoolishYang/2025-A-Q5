"""Portable, read-only source/config checks and an isolated Stage05 rerun.

The original Stage05 checker is copied byte-for-byte into a temporary folder.
Its evidence JSON is copied, and only the copy's source paths are redirected
to verified portable-input aliases. Historical project evidence is never used
as a destination for a new test result.
"""
from datetime import datetime,timezone
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path,PureWindowsPath
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

from .config import RunConfig

ROOT=Path(__file__).resolve().parents[2]
AUTHORITY_SHA256="29ea5f37f9e50dae9f5d7f7515276394d2215fdc8f0d0b79c6d0c91eccd437d4"
EXPECTED_STAGE05_ASSERTIONS=48


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _pipeline_config(root,path,value):
    if (not isinstance(value,dict) or set(value)-{"runs","note"}
            or not isinstance(value.get("runs"),list) or not value["runs"]
            or ("note" in value and not isinstance(value["note"],str))):
        raise ValueError("Invalid server_first_round pipeline manifest shape")
    outputs=set();rows=[]
    for item in value["runs"]:
        if (not isinstance(item,dict) or set(item)!={"config","out"}
                or any(not isinstance(item[k],str) or not item[k] for k in ("config","out"))):
            raise ValueError("Pipeline runs must contain config/out path strings only")
        # Both spellings of absolute paths and parent traversal are rejected,
        # so a Windows-authored plan remains constrained on a Linux server.
        for key in ("config","out"):
            pp=Path(item[key]);wp=PureWindowsPath(item[key])
            if pp.is_absolute() or wp.is_absolute() or ".." in pp.parts or ".." in wp.parts:
                raise ValueError("Pipeline paths must be project-relative without parent traversal")
        config=(root/item["config"]).resolve();output=(root/item["out"]).resolve()
        if (root/"configs").resolve() not in config.parents or not config.is_file():
            raise ValueError(f"Missing/out-of-project pipeline config: {item['config']}")
        if root not in output.parents or output in outputs:
            raise ValueError("Pipeline output paths must be unique and stay within project")
        outputs.add(output)
        cfg=RunConfig.from_json(config)
        rows.append({"config":config.relative_to(root).as_posix(),"out":output.relative_to(root).as_posix(),
                     "config_fingerprint":cfg.fingerprint})
    return {"path":path.relative_to(root).as_posix(),"kind":"PIPELINE_PLAN","status":"PASS",
            "file_sha256":_sha(path),"runs":rows}


def _stage05_isolated(root,manifest):
    source_script=root/"workspace/evidence/stage05_test_only_checks.py"
    source_evidence=root/"workspace/evidence/stage05_presolve_checks.json"
    before={"script":_sha(source_script),"evidence":_sha(source_evidence)}
    original=json.loads(source_evidence.read_text(encoding="utf-8"))
    recorded=original.get("test_only_execution",{}).get("script_sha256")
    if recorded!=before["script"]:
        raise ValueError("Stage05 script differs from its recorded reviewed hash")
    raw=root/"data/raw"
    remapping=[]
    with TemporaryDirectory(prefix="drying_stage05_preflight_") as temporary:
        work=Path(temporary)
        copied_script=work/source_script.name
        copied_evidence=work/source_evidence.name
        shutil.copyfile(source_script,copied_script)
        shutil.copyfile(source_evidence,copied_evidence)
        record=json.loads(copied_evidence.read_text(encoding="utf-8"))
        aliases=work/"source_aliases";aliases.mkdir()
        for source in record["source_hashes"]:
            basename=PureWindowsPath(source["path"]).name
            matching=[item for item in manifest["files"] if item["sha256"]==source["sha256"]]
            named=[item for item in matching if PureWindowsPath(item["original_relative_path"]).name==basename]
            if len(named)!=1:
                raise ValueError(f"Unambiguous portable source mapping unavailable: {basename}")
            entry=named[0];portable=(raw/entry["relative_path"]).resolve()
            if raw.resolve() not in portable.parents or _sha(portable)!=source["sha256"]:
                raise ValueError(f"Portable source hash/path mismatch: {basename}")
            # Preserve original names: the unchanged historical checker has
            # one basename-specific environment assertion. This is a verified
            # alias copy, not a reconstructed or modified input workbook.
            alias=aliases/basename
            if alias.exists():raise ValueError(f"Duplicate source alias: {basename}")
            shutil.copyfile(portable,alias)
            if _sha(alias)!=source["sha256"]:
                raise ValueError("Copied portable input failed identity check")
            source["path"]=str(alias)
            remapping.append({"original_filename":basename,"portable_path":entry["relative_path"],
                              "sha256":source["sha256"],"alias_bytes_unchanged":True})
        copied_evidence.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        env=os.environ.copy();env["PYTHONDONTWRITEBYTECODE"]="1";env["PYTHONUTF8"]="1"
        start=time.perf_counter()
        proc=subprocess.run([sys.executable,str(copied_script)],cwd=work,env=env,
                            capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=60)
        elapsed=time.perf_counter()-start
        if proc.returncode!=0:
            raise RuntimeError(f"Isolated Stage05 checker failed ({proc.returncode}): {proc.stderr[-6000:]}")
        updated=json.loads(copied_evidence.read_text(encoding="utf-8"))
        execution=updated["test_only_execution"]
        checks=execution["checks"]
        if (execution["assertions_passed"]!=EXPECTED_STAGE05_ASSERTIONS or len(checks)!=EXPECTED_STAGE05_ASSERTIONS
                or any(check["status"]!="PASS" for check in checks)
                or not any(check["id"]=="ENVIRONMENT_BELOW_THRESHOLD" for check in checks)):
            raise RuntimeError("Stage05 rerun did not execute all 48 original assertions")
        if execution["script_sha256"]!=before["script"]:
            raise RuntimeError("Stage05 subprocess used altered checker bytes")
        after={"script":_sha(source_script),"evidence":_sha(source_evidence)}
        if before!=after:
            raise RuntimeError("Historical Stage05 files changed during preflight")
        return {"status":"PASS","scope":"STAGE05_ISOLATED_TEST_ONLY_RERUN",
                "assertions_passed":execution["assertions_passed"],"checks":checks,
                "packages":execution["packages"],"python":execution["python"],
                "runtime":execution["runtime"],"timestamp":execution["timestamp"],
                "elapsed_seconds":elapsed,"returncode":proc.returncode,
                "stdout":proc.stdout.strip(),"stderr":proc.stderr.strip(),
                "source_mapping":remapping,"historical_hashes_before":before,
                "historical_hashes_after":after,"historical_files_unchanged":True,
                "checker_bytes_unchanged":True,"temporary_copies_removed_on_return":True,
                "formal_PDE":"NOT_RUN_BY_PREFLIGHT","stage07":"NOT_RUN"}


def run_preflight(output=None,include_stage05=True):
    """Return JSON-serializable PASS/FAIL report; caller must honor FAIL.

    ``output`` optionally receives a new atomic JSON report. Missing packages,
    altered authority/inputs/configurations, and failed isolated checks are
    explicit failures. Skipping Stage05 does not impersonate an executed check.
    """
    root=ROOT.resolve()
    authority=root/"workspace/04_model_specification.md"
    report={"status":"PASS","scope":"STAGE06_PORTABLE_PREFLIGHT",
            "timestamp":datetime.now(timezone.utc).isoformat(),"root":str(root),
            "python":sys.version,"executable":sys.executable,"dependencies":{},
            "authority":{},"raw":{},"configs":{},"stage05":{"status":"NOT_RUN"},
            "failures":[],"formal_PDE":"NOT_RUN_BY_PREFLIGHT","stage07":"NOT_RUN"}
    start=time.perf_counter()
    for name in ("numpy","scipy","sympy","openpyxl","pytest"):
        try:
            importlib.import_module(name)
            report["dependencies"][name]={"status":"PASS","version":importlib.metadata.version(name)}
        except Exception as exc:
            report["dependencies"][name]={"status":"FAIL","error":str(exc)}
            report["failures"].append(f"Dependency {name}: {exc}")
    try:
        actual=_sha(authority)
        report["authority"]={"path":"workspace/04_model_specification.md","expected_sha256":AUTHORITY_SHA256,
                             "actual_sha256":actual,"model_version":"A26-04-v2","status":"PASS" if actual==AUTHORITY_SHA256 else "FAIL"}
        if actual!=AUTHORITY_SHA256:raise ValueError("A26-04-v2 authority SHA-256 mismatch")
    except Exception as exc:
        report["authority"]["status"]="FAIL";report["failures"].append(str(exc))
    try:
        from .inputs import Inputs
        inputs=Inputs(root/"data/raw")
        # Inputs independently pins all numerical/template sources. Verify
        # every manifest entry as well, including the optional problem PDF.
        for entry in inputs.manifest["files"]:
            path=(root/"data/raw"/entry["relative_path"]).resolve()
            if (root/"data/raw").resolve() not in path.parents or _sha(path)!=entry["sha256"]:
                raise ValueError(f"Portable manifest mismatch: {entry['relative_path']}")
        report["raw"]={"status":"PASS","input_fingerprint":inputs.fingerprint,"files":inputs.manifest["files"],
                       "environment_rows":len(inputs.env_times),"radius_rows":len(inputs.radius_times),
                       "environment_window_count":inputs.window_count,"schema_and_units_checked":True}
    except Exception as exc:
        report["raw"]={"status":"FAIL","error":str(exc)};report["failures"].append(str(exc))
    config_files=sorted((root/"configs").rglob("*.json"))
    if not config_files:
        report["configs"]={"status":"FAIL","files":[],"error":"No RunConfig JSON files under configs"}
        report["failures"].append("No portable RunConfig JSON files discovered")
    else:
        config_records=[]
        for path in config_files:
            try:
                value=json.loads(path.read_text(encoding="utf-8-sig"))
                if path.name=="server_first_round.json":
                    config_records.append(_pipeline_config(root,path,value))
                    continue
                if not isinstance(value,dict) or not {"route","question"}.issubset(value):
                    raise ValueError("Unexpected config JSON shape; expected explicit route/question RunConfig")
                cfg=RunConfig.from_json(path)
                config_records.append({"path":path.relative_to(root).as_posix(),"status":"PASS",
                                       "kind":"RUN_CONFIG",
                                       "file_sha256":_sha(path),"config_fingerprint":cfg.fingerprint,
                                       "route":cfg.route,"question":cfg.question,"geometry":cfg.geometry,
                                       "execution_backend":cfg.execution_backend,"execution_purpose":cfg.execution_purpose,
                                       "production_eligible":cfg.production_eligible})
            except Exception as exc:
                config_records.append({"path":path.relative_to(root).as_posix(),"status":"FAIL","error":str(exc)})
                report["failures"].append(f"Configuration {path.name}: {exc}")
        report["configs"]={"status":"PASS" if all(x["status"]=="PASS" for x in config_records) else "FAIL","files":config_records}
    if include_stage05 and not report["failures"]:
        try:
            report["stage05"]=_stage05_isolated(root,inputs.manifest)
        except Exception as exc:
            report["stage05"]={"status":"FAIL","error":str(exc)};report["failures"].append(str(exc))
    elif include_stage05:
        report["stage05"]={"status":"NOT_RUN","reason":"Earlier preflight prerequisite failed"}
    else:
        report["stage05"]={"status":"NOT_RUN","reason":"Explicit include_stage05=False"}
    report["status"]="FAIL" if report["failures"] else "PASS"
    report["elapsed_seconds"]=time.perf_counter()-start
    if output is not None:
        destination=Path(output).resolve()
        protected={authority.resolve(),(root/"workspace/evidence/stage05_test_only_checks.py").resolve(),
                   (root/"workspace/evidence/stage05_presolve_checks.json").resolve()}
        raw=(root/"data/raw").resolve()
        if destination in protected or destination==raw or raw in destination.parents:
            raise ValueError("Preflight output cannot overwrite authority, historical evidence or raw sources")
        from .trajectory import atomic_json
        atomic_json(destination,report)
    return report
