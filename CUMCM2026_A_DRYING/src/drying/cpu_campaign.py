"""Explicit local CPU execution of the complete finite server experiment plan.

No PDE, grid, tolerance or horizon is changed. GPU-only tests/certificates and
competition workbook exports are inapplicable, not passed. Stage07 stays closed.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import traceback

from .campaign import (Campaign, CampaignDeadline, ROOT, _exclusive_lock,
                       _fingerprint, _invoke, _now, _read, _write, _retryable)
from .campaign_plan import expand_campaign
from .config import RunConfig


CPU_FIELDS = {"linear_backend": "CPU_REFERENCE", "execution_backend": "LOCAL_DEV",
              "execution_purpose": "FRAMEWORK_INTEGRATION", "production_eligible": False}


def expand_cpu_campaign(plan):
    original = expand_campaign(plan, root=ROOT)
    result = deepcopy(original)
    mapping, configs = {}, {}
    for record in result["runs"]:
        old_key = record["run_key"]
        cpu = replace(RunConfig.from_dict(record["config"]), **CPU_FIELDS)
        key = f"CPU_{cpu.route}_Q{cpu.question}_{cpu.fingerprint[:16]}"
        if key in configs:
            raise ValueError("CPU_PLAN_KEY_COLLISION")
        mapping[old_key] = key
        configs[key] = cpu
        record.update(run_key=key, config=cpu.as_dict(), config_fingerprint=cpu.fingerprint)

    def remap(value):
        if isinstance(value, str):
            return mapping.get(value, value)
        if isinstance(value, list):
            return [remap(item) for item in value]
        if isinstance(value, dict):
            return {key: remap(item) for key, item in value.items()}
        return value

    for field in ("base_runs", "cases", "comparisons", "sensitivities", "source_configs"):
        result[field] = remap(result[field])
    for source in result["source_configs"]:
        source["config_fingerprint"] = configs[source["run_key"]].fingerprint
    result["hardware"]["linear_backend"] = "CPU_REFERENCE"
    result.update(name="CPU_" + original["name"], version="A26-CPU-FULL-TEST-v1",
                  source_plan_fingerprint=original["plan_fingerprint"],
                  source_spec_fingerprint=original["spec_fingerprint"],
                  execution=CPU_FIELDS, cpu_key_mapping=mapping,
                  excluded_operations={"cuda_device_tests": "NOT_APPLICABLE_CPU",
                      "formal_cuda_certification": "NOT_APPLICABLE_CPU",
                      "competition_workbook_exports": "NOT_REQUESTED_CPU_DEVELOPMENT"})
    result["spec_fingerprint"] = _fingerprint({"source_spec": original["spec_fingerprint"],
        "version": result["version"], "execution": CPU_FIELDS})
    result.pop("plan_fingerprint")
    # Verify every physical/numerical/resource field and all plan references.
    if not (len(result["runs"]) == len(configs) == len(mapping) == 67
            and len(result["comparisons"]) == 14 and len(result["source_configs"]) == 11):
        raise ValueError("CPU_PLAN_TOPOLOGY_CHANGED")
    for before, after in zip(original["runs"], result["runs"]):
        if (not all(after["config"][k] == v for k, v in before["config"].items() if k not in CPU_FIELDS)
                or not all(after["config"][k] == v for k, v in CPU_FIELDS.items())
                or after["config_fingerprint"] != RunConfig.from_dict(after["config"]).fingerprint):
            raise ValueError("CPU_PLAN_CONFIG_CONTRACT_CHANGED")
    result["plan_fingerprint"] = _fingerprint(result)
    return result


class CPUCampaign(Campaign):
    def progress(self, phase, active=None):
        result = {"status": "RUNNING", "phase": phase, "active_run": active,
            "updated_at": _now(), "pid": os.getpid(), "run_count": self.expanded["run_count"],
            "completed_run_count": sum(bool(r.get("complete")) for r in self.state["runs"].values()),
            "execution": CPU_FIELDS, "stage07": "NOT_RUN", "stage08": "NOT_RUN"}
        _write(self.root / "live_progress.json", result)

    def preflight(self):
        self.progress("PREFLIGHT_AND_CPU_TESTS")
        request = self.logs / "cpu_preflight_request.json"
        output = self.logs / "cpu_preflight.json"
        _write(request, {"output": str(output)})
        process = _invoke([sys.executable, "-m", "drying.cpu_campaign", "--preflight-worker", str(request)],
                          self.logs / "cpu_preflight.log", min(self.budget["tests_timeout_seconds"], self.remaining()))
        self.state["invocations"][-1]["cpu_preflight"] = process; self.save()
        if process["returncode"] != 0 or process["timed_out"] or not output.exists() or _read(output).get("status") != "PASS":
            raise RuntimeError("CPU_PREFLIGHT_FAILED; see " + str(self.logs / "cpu_preflight.log"))
        env = dict(os.environ, DRYING_REQUIRE_CUDA="0")
        for name in ("DRYING_CUDA_TEST_REQUESTS", "DRYING_CUDA_DEVICE", "DRYING_GPU_MEMORY_MB"):
            env.pop(name, None)
        xml = self.logs / "cpu_tests.xml"
        process = _invoke([sys.executable, "-m", "pytest", "-q", "-m", "not cuda", "--junitxml=" + str(xml)],
                          self.logs / "cpu_tests.log", min(self.budget["tests_timeout_seconds"], self.remaining()), env)
        self.state["invocations"][-1]["tests"] = dict(process, xml=str(xml), selection="not cuda")
        self.save()
        if process["returncode"] != 0 or process["timed_out"]:
            raise RuntimeError("CPU_TESTS_FAILED_OR_TIMED_OUT; see " + str(self.logs / "cpu_tests.log"))

    def run_one(self, specification):
        self.progress("MAIN_SOLVES", specification["run_key"])
        super().run_one(specification)
        self.progress("MAIN_SOLVES")
        record = self.state["runs"][specification["run_key"]]
        metrics_path = Path(record["directory"]) / "metrics.json"
        metrics = _read(metrics_path) if metrics_path.exists() else {}
        print(f"[cpu-full] completed={sum(bool(r.get('complete')) for r in self.state['runs'].values())}/67 "
              f"run={specification['run_key']} status={record.get('status')} "
              f"solver_wall_s={metrics.get('wall_seconds')}", flush=True)

    def action(self, key, payload, timeout, cache=True, finalization=False):
        if payload.get("operation") == "analysis":
            payload = deepcopy(payload)
            payload["context"].update(development_cpu=True, export_requested=False)
            payload["identity"]["cpu_analysis_context"] = _fingerprint(payload["context"])
        return super().action(key, payload, timeout, cache, finalization)

    def analyze(self):
        self.progress("REFINEMENT_BALANCES_AND_COMPARISONS")
        return super().analyze()

    def finish(self, failure=None):
        cases = self.state.get("case_results", {})
        comparisons = self.state.get("comparisons", {})
        observations = self.state.get("observations", {})
        count = sum(bool(r.get("complete")) for r in self.state["runs"].values())
        expected = {r["run_key"] for r in self.expanded["runs"]}
        ready = (set(self.state["runs"]) == expected and count == len(expected)
                 and set(observations) == expected and all(not _retryable(o) for o in observations.values()))
        ready &= (set(cases) == set(self.expanded["cases"]) and cases.get("Q1", {}).get("status") == "CPU_Q1_NUMERICS_READY"
                  and all(cases.get(k, {}).get("status") == "CPU_REPORT_CANDIDATE_READY" for k in self.expanded["cases"] if k != "Q1"))
        ready &= len(comparisons) == 14 and all(c.get("resolved") for c in comparisons.values())
        hard = (failure is not None and not isinstance(failure, CampaignDeadline)) or any(c.get("exit_code") == 1 for c in cases.values())
        code = 1 if hard else 0 if ready and failure is None else 2
        result = {"status": "CPU_FULL_TEST_COMPLETE" if code == 0 else "CPU_FULL_TEST_FAILED" if code == 1 else "CPU_FULL_TEST_PARTIAL_OR_UNRESOLVED",
            "exit_code": code, "campaign_dir": str(self.root), "identity": self.identity,
            "run_count": self.expanded["run_count"], "completed_run_count": count,
            "case_results": cases, "comparisons": comparisons, "observations": observations,
            "failure": str(failure) if failure else None, "execution": CPU_FIELDS,
            "stage07": "NOT_RUN", "stage08": "NOT_RUN", "model_frozen": False,
            "formal_certificate_issued": False,
            "scope": "LOCAL_CPU_FULL_DEVELOPMENT_TEST_NOT_PRODUCTION_VALIDATION",
            "excluded_operations": self.expanded["excluded_operations"]}
        self.state["invocations"][-1].update(finished_at=_now(), status=result["status"], exit_code=code)
        self.state["status"] = result["status"]; self.save()
        _write(self.root / "campaign_summary.json", result)
        try:
            result["return_package"] = self.action("pack_cpu_" + str(self.invocation),
                {"operation": "pack", "root": str(self.root),
                 "zip_path": str(self.root.with_name(self.root.name + f"_return_{self.invocation:03d}.zip"))},
                300., cache=False, finalization=True)
        except Exception as exc:
            result["return_package"] = {"status": "NOT_PACKED", "error": str(exc)}
        if not result["return_package"].get("path") and code == 0:
            result.update(status="CPU_FULL_TEST_PARTIAL_OR_UNRESOLVED", exit_code=2)
        self.state["status"] = result["status"]
        self.state["invocations"][-1].update(status=result["status"], exit_code=result["exit_code"])
        self.save()
        _write(self.root / "campaign_summary.json", result)
        _write(self.root / f"campaign_summary_invocation_{self.invocation:03d}.json", result)
        _write(self.root / "live_progress.json", dict(result, updated_at=_now(), pid=os.getpid()))
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", default=str(ROOT / "configs/server_full.json"))
    parser.add_argument("--out")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--preflight-worker", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.preflight_worker:
        from .preflight import run_preflight
        request = _read(args.preflight_worker)
        result = run_preflight(output=request["output"], require_cuda=False)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0 if result["status"] == "PASS" else 1
    expanded = expand_cpu_campaign(args.plan)
    if args.plan_only:
        print(json.dumps(expanded, indent=2, ensure_ascii=False)); return 0
    if not args.out:
        parser.error("--out is required for execution")
    out = Path(args.out).resolve()
    results_root = (ROOT / "results").resolve()
    if results_root not in out.parents:
        raise ValueError("CPU campaign output must be a new subdirectory of project results")
    if out.exists() and not args.resume:
        raise FileExistsError("Use a new CPU run directory or --resume")
    out.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock(out):
        campaign = CPUCampaign(expanded, out, args.resume)
        failure = None
        try:
            campaign.preflight()
            for specification in expanded["runs"]:
                campaign.run_one(specification)
            campaign.progress("OBSERVATIONS")
            campaign.summarize()
            campaign.analyze()
        except (Exception, KeyboardInterrupt) as exc:
            failure = CampaignDeadline("USER_INTERRUPTED") if isinstance(exc, KeyboardInterrupt) else exc
            traceback.print_exc()
        result = campaign.finish(failure)
        print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
        return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
