"""Server-executed policy tests; synthetic telemetry is not GPU-run evidence."""
from dataclasses import replace
import pytest
from drying.config import RunConfig
from drying.refinement import _require_cuda_evidence, RefinementError


def telemetry(**changes):
    record = dict(backend="CUDA", dtype="float64", device_id=0,
                  successful_solves=3, cpu_fallback_calls=0)
    record.update(changes)
    return record


def test_cpu_reference_cannot_receive_formal_gpu_certificate():
    cfg = RunConfig(linear_backend="CPU_REFERENCE", execution_purpose="TEST_ONLY")
    with pytest.raises(RefinementError, match="CPU_REFERENCE"):
        _require_cuda_evidence(cfg, {"execution": {"linear_backend": telemetry()}})


@pytest.mark.parametrize("record", [None, telemetry(successful_solves=0),
    telemetry(backend="CPU_REFERENCE"), telemetry(dtype="float32"),
    telemetry(device_id=1), telemetry(cpu_fallback_calls=1)])
def test_missing_probe_only_or_incompatible_backend_evidence_is_rejected(record):
    execution = {} if record is None else {"linear_backend": record}
    with pytest.raises(RefinementError, match="CUDA_EVIDENCE_REQUIRED"):
        _require_cuda_evidence(RunConfig(), {"execution": execution})


def test_resumed_run_can_use_actual_earlier_attempt_but_all_attempts_must_agree():
    cfg = replace(RunConfig(), cuda_device=1)
    execution = {"attempts": [{"linear_backend": telemetry(device_id=1)},
                              {"linear_backend": telemetry(device_id=1, successful_solves=0)}]}
    _require_cuda_evidence(cfg, {"execution": execution})
    execution["attempts"][0]["linear_backend"]["cpu_fallback_calls"] = 1
    with pytest.raises(RefinementError, match="incompatible"):
        _require_cuda_evidence(cfg, {"execution": execution})
