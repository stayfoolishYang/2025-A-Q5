"""CUDA-required server preflight and an isolated Stage05 rerun.

The original Stage05 checker is copied byte-for-byte into a temporary folder.
Its evidence JSON is copied, and only the copy's source paths are redirected
to verified portable-input aliases. Historical project evidence is never used
as a destination for a new test result.

Importing this module never probes a GPU. CUDA probing happens only when the
server invokes run_preflight(require_cuda=True), its default. An explicitly
requested CPU_REFERENCE_TEST preflight never impersonates CUDA verification.
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


def _probe_cuda(device_id,memory_mb):
    # Deliberately lazy: package imports and static inspection must not touch
    # CuPy, the CUDA runtime, a driver, or a device.
    from .cuda_backend import probe_cuda
    return probe_cuda(device_id=device_id,memory_mb=memory_mb)


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
                     "config_fingerprint":cfg.fingerprint,"linear_backend":cfg.linear_backend,
                     "cuda_device":cfg.cuda_device,"gpu_memory_mb":cfg.gpu_memory_mb})
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


def run_preflight(output=None,include_stage05=True,require_cuda=True,cuda_requests_override=None):
    """Return JSON-serializable PASS/FAIL report; caller must honor FAIL.

    ``output`` optionally receives a new atomic JSON report. Missing packages,
    altered authority/inputs/configurations, and failed isolated checks are
    explicit failures. CUDA is required by default; unavailable CuPy, a driver,
    a device, or float64 capability causes FAIL, never CPU fallback.
    ``require_cuda=False`` is explicitly labeled CPU_REFERENCE_TEST and
    GPU_NOT_CHECKED. Skipping Stage05 does not impersonate an executed check.
    """
    root=ROOT.resolve()
    authority=root/"workspace/04_model_specification.md"
    report={"status":"PASS","scope":"STAGE06_PORTABLE_PREFLIGHT",
            "mode":"CUDA_REQUIRED_SERVER" if require_cuda else "CPU_REFERENCE_TEST",
            "timestamp":datetime.now(timezone.utc).isoformat(),"root":str(root),
            "python":sys.version,"executable":sys.executable,"dependencies":{},
            "authority":{},"raw":{},"configs":{},"stage05":{"status":"NOT_RUN"},
            "gpu":{"status":"NOT_RUN" if require_cuda else "GPU_NOT_CHECKED",
                   "required":bool(require_cuda),"automatic_cpu_fallback":False,"devices":[],
                   "scope":"CUDA_RUNTIME_DEVICE_CAPABILITY_NOT_SOLVER_VALIDATION"},
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
    cuda_requests=set()
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
                if isinstance(value,dict) and value.get("kind")=="CAMPAIGN_PLAN":
                    from .campaign_plan import expand_campaign
                    expanded=expand_campaign(value,root=root)
                    config_records.append({"path":path.relative_to(root).as_posix(),
                        "kind":"CAMPAIGN_PLAN","status":"PASS","file_sha256":_sha(path),
                        "plan_fingerprint":expanded["plan_fingerprint"],"run_count":expanded["run_count"]})
                    continue
                if not isinstance(value,dict) or not {"route","question"}.issubset(value):
                    raise ValueError("Unexpected config JSON shape; expected explicit route/question RunConfig")
                cfg=RunConfig.from_json(path)
                if cfg.linear_backend=="CUDA":
                    cuda_requests.add((cfg.cuda_device,cfg.gpu_memory_mb))
                config_records.append({"path":path.relative_to(root).as_posix(),"status":"PASS",
                                       "kind":"RUN_CONFIG",
                                       "file_sha256":_sha(path),"config_fingerprint":cfg.fingerprint,
                                       "route":cfg.route,"question":cfg.question,"geometry":cfg.geometry,
                                       "linear_backend":cfg.linear_backend,"cuda_device":cfg.cuda_device,
                                       "gpu_memory_mb":cfg.gpu_memory_mb,
                                       "execution_backend":cfg.execution_backend,"execution_purpose":cfg.execution_purpose,
                                       "production_eligible":cfg.production_eligible})
            except Exception as exc:
                config_records.append({"path":path.relative_to(root).as_posix(),"status":"FAIL","error":str(exc)})
                report["failures"].append(f"Configuration {path.name}: {exc}")
        report["configs"]={"status":"PASS" if all(x["status"]=="PASS" for x in config_records) else "FAIL","files":config_records}
    if cuda_requests_override is not None:
        try:
            if not isinstance(cuda_requests_override,list) or not cuda_requests_override:
                raise ValueError("CUDA override must be a nonempty list")
            selected=set()
            for item in cuda_requests_override:
                if not isinstance(item,dict) or set(item)!={"cuda_device","gpu_memory_mb"}:
                    raise ValueError("CUDA override requires cuda_device/gpu_memory_mb only")
                device,memory=item["cuda_device"],item["gpu_memory_mb"]
                if (isinstance(device,bool) or not isinstance(device,int) or device<0 or
                        isinstance(memory,bool) or not isinstance(memory,int) or memory<1):
                    raise ValueError("CUDA override requires a nonnegative device and positive MiB")
                selected.add((device,memory))
            cuda_requests=selected
            report["gpu"]["request_source"]="EXPLICIT_CAMPAIGN_HARDWARE"
        except ValueError as exc:
            report["failures"].append(str(exc))
    report["gpu"]["requested_devices"]=[{"cuda_device":d,"gpu_memory_mb":m} for d,m in sorted(cuda_requests)]
    if require_cuda and not report["failures"]:
        if not cuda_requests:
            report["gpu"].update(status="FAIL",reason="No CUDA RunConfig found for CUDA-required server preflight")
            report["failures"].append("CUDA_REQUIRED: no configured CUDA execution; CPU fallback is forbidden")
        else:
            for device_id,memory_mb in sorted(cuda_requests):
                try:
                    metadata=_probe_cuda(device_id,memory_mb)
                    if not isinstance(metadata,dict) or metadata.get("status")!="PASS":
                        raise ValueError("CUDA probe did not return explicit PASS metadata")
                    if (metadata.get("backend")!="CUDA" or metadata.get("dtype")!="float64"
                            or metadata.get("float64_supported") is not True
                            or metadata.get("device_id")!=device_id):
                        raise ValueError("CUDA probe metadata does not establish the requested float64 device")
                    for field in ("cupy_version","device_name","compute_capability","solver"):
                        if not isinstance(metadata.get(field),str) or not metadata[field]:
                            raise ValueError(f"CUDA probe metadata missing {field}")
                    for field in ("cuda_runtime_version","cuda_driver_version","device_total_bytes",
                                  "device_free_bytes","gpu_memory_budget_bytes"):
                        if (not isinstance(metadata.get(field),int) or isinstance(metadata[field],bool)
                                or metadata[field]<0):
                            raise ValueError(f"CUDA probe metadata missing/invalid {field}")
                    if not isinstance(metadata.get("solver_probe_performed"),bool):
                        raise ValueError("CUDA probe must distinguish device checks from an executed solve")
                    # Keep the actual backend metadata, including CuPy/driver/
                    # runtime/device/float64 evidence; do not replace it with
                    # inferred availability or a synthesized device identity.
                    json.dumps(metadata,allow_nan=False)
                    report["gpu"]["devices"].append({"device_id":device_id,"memory_mb":memory_mb,
                                                      "status":"PASS","metadata":metadata})
                except Exception as exc:
                    report["gpu"]["devices"].append({"device_id":device_id,"memory_mb":memory_mb,
                                                      "status":"FAIL","error":str(exc),"error_type":type(exc).__name__,
                                                      "code":getattr(exc,"code","CUDA_PREFLIGHT_FAILED")})
                    report["failures"].append(f"CUDA_REQUIRED device {device_id}: {exc}")
            report["gpu"]["status"]="PASS" if all(x["status"]=="PASS" for x in report["gpu"]["devices"]) else "FAIL"
    elif require_cuda:
        report["gpu"]["reason"]="Earlier preflight prerequisite failed; CUDA not probed"
    else:
        report["gpu"]["reason"]="Explicit require_cuda=False: CPU_REFERENCE_TEST only; CUDA availability is unverified"
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
