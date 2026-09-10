"""Standard-library source/package checks; never import or run drying code."""
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[2]
AUTHORITY = "29ea5f37f9e50dae9f5d7f7515276394d2215fdc8f0d0b79c6d0c91eccd437d4"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    checks = []
    def record(name, ok, detail):
        checks.append({"check": name, "status": "PASS" if ok else "FAIL", "detail": detail})
        if not ok:
            raise ValueError(name + ": " + str(detail))

    python_files = sorted((ROOT / "src").rglob("*.py")) + sorted((ROOT / "tests").glob("*.py"))
    trees = {p: ast.parse(p.read_text(encoding="utf-8-sig"), filename=str(p)) for p in python_files}
    record("PYTHON_AST", True, {"files": len(trees), "project_imported": False})
    for path in sorted((ROOT / "configs").glob("*.json")):
        json.loads(path.read_text(encoding="utf-8-sig"))
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8-sig"))
    record("JSON_TOML_SYNTAX", metadata["project"]["version"] == "0.6.2", "0.6.2")
    record("AUTHORITY_UNCHANGED", sha(ROOT / "workspace/04_model_specification.md") == AUTHORITY, AUTHORITY)
    raw = ROOT / "data/raw"
    manifest = json.loads((raw / "source_manifest.json").read_text(encoding="utf-8-sig"))
    for item in manifest["files"]:
        path = (raw / item["relative_path"]).resolve()
        record("RAW_" + item["relative_path"], raw.resolve() in path.parents and sha(path) == item["sha256"], item["sha256"])
    state = json.loads((ROOT / "workspace/modeling_state.json").read_text(encoding="utf-8-sig"))
    record("GATES_REMAIN_UNVERIFIED", state["gates"]["gate_07_validation"] == "NOT_RUN" and
        state["gates"]["gate_08_model_improvement"] == "NOT_RUN" and
        state["model_status"]["current_best_verified"] is None and not state["model_status"]["model_frozen"] and
        state["workflow"]["operating_mode"] == "PERFORMANCE", "Stage07/08 NOT_RUN; PERFORMANCE; unfrozen")
    for name in ("06_implementation", "06_validation_return_requirements"):
        path = ROOT / "workspace/stale" / (name + "_rev002.md")
        record("ARCHIVE_" + name, path.is_file() and path.stat().st_size > 0, sha(path))
    functions = {}
    for path, tree in trees.items():
        functions[path.stem] = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    required = {"campaign": ("run_campaign", "_worker"), "campaign_plan": ("expand_campaign", "validate_campaign_spec"),
                "campaign_analysis": ("analyze_case",), "campaign_comparison": ("compare_campaign_runs",)}
    for module, names in required.items():
        record("API_" + module, all(n in functions[module] for n in names), list(names))
    args = functions["preflight"]["run_preflight"].args
    record("PREFLIGHT_OVERRIDE_SIGNATURE", "cuda_requests_override" in [a.arg for a in args.args + args.kwonlyargs], "AST signature")
    cli = (ROOT / "src/drying/cli.py").read_text(encoding="utf-8")
    record("CLI_BOUND", all(text in cli for text in ("'full-run'", "'_campaign-worker'", "run_campaign(args.plan", "return _worker(args.request)")), "AST parsed and dispatch source inspected")
    source_hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in python_files}
    output = {"scope": "STATIC_ONLY_NO_PROJECT_IMPORT_OR_NUMERICAL_EXECUTION", "timestamp": datetime.now(timezone.utc).isoformat(),
        "implementation_revision": "A26-06-FULL-v1", "checks": checks, "source_hashes": source_hashes,
        "gpu_probe": "NOT_RUN", "pytest": "NOT_RUN", "solver": "NOT_RUN", "campaign_execution": "NOT_RUN",
        "expected_default_run_count": 67, "count_evidence": "STATIC_DESIGN_SERVER_ASSERTIONS_NOT_EXECUTED",
        "stage07": "NOT_RUN", "model_frozen": False}
    (ROOT / "workspace/evidence/stage06_full_static_checks.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "STATIC_CHECKS_PASS", "checks": len(checks), "python_files": len(python_files),
                      "numeric_execution": "NOT_RUN"}))


if __name__ == "__main__":
    main()
