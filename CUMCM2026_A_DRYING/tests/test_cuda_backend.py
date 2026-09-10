"""SERVER ONLY: actual NVIDIA CUDA sparse-solve tests, never a mocked PASS.

DRYING_REQUIRE_CUDA=1 forces hardware/dependency failure to fail the tests.
Only an explicit DRYING_CUDA_TEST_MODE=optional-local permits a missing-device
skip, and REQUIRE_CUDA overrides that opt-out. Do not run these tests locally
under the current user's prohibition on all local numerical execution.
"""
import json
import os
import numpy as np
import pytest
from scipy import sparse
from scipy.sparse.linalg import spsolve as cpu_reference_spsolve

from drying.cuda_backend import CudaBackendError, CudaLinearSolver, probe_cuda


pytestmark = pytest.mark.cuda


@pytest.fixture(scope="module", autouse=True)
def actual_cuda(cuda_options):
    device_id, memory_mb = cuda_options
    try:
        metadata = probe_cuda(device_id=device_id, memory_mb=memory_mb)
    except CudaBackendError as exc:
        optional = (os.environ.get("DRYING_REQUIRE_CUDA") != "1" and
                    os.environ.get("DRYING_CUDA_TEST_MODE") == "optional-local")
        if optional and exc.code in {"CUDA_DEPENDENCY_UNAVAILABLE", "CUDA_DEVICE_UNAVAILABLE"}:
            pytest.skip("Explicit optional local mode; no GPU solve evidence: " + str(exc))
        pytest.fail("REQUIRED CUDA server preflight failed: " + str(exc), pytrace=False)
    assert metadata["status"] == "PASS" and metadata["backend"] == "CUDA"
    assert metadata["float64_supported"] and metadata["dtype"] == "float64"
    assert 12000 <= metadata["cuda_runtime_version"] < 13000
    assert metadata["solver_probe_performed"] is False
    assert metadata["device_id"] == device_id
    assert metadata["gpu_memory_budget_bytes"] == memory_mb * 1024**2
    json.dumps(metadata, allow_nan=False)
    return device_id, memory_mb


def test_real_nonsymmetric_float64_CSR_and_CSC_gpu_solves(actual_cuda):
    n = 37
    matrix = sparse.diags((np.full(n-2, .13), np.full(n-1, -.8),
                            np.linspace(3., 4., n), np.full(n-1, -.31)),
                           (-2, -1, 0, 1), shape=(n, n), format="csr", dtype=np.float64)
    expected = np.sin(np.linspace(.1, 1.2, n))
    residual = np.asarray(-(matrix @ expected), dtype=np.float64)
    backend = CudaLinearSolver(*actual_cuda)
    for A in (matrix, matrix.tocsc()):
        cpu = cpu_reference_spsolve(A, -residual)
        answer, backward = backend.solve(A, residual)
        assert answer.dtype == np.float64 and answer.shape == residual.shape
        np.testing.assert_allclose(answer, expected, rtol=2e-12, atol=2e-13)
        np.testing.assert_allclose(answer, cpu, rtol=2e-12, atol=2e-13)
        host_backward = np.max(np.abs(A @ answer+residual)) / (
            np.max(np.asarray(abs(A).sum(axis=1)).ravel()) * np.max(abs(answer)) + np.max(abs(residual)))
        assert backward <= 1e-12 and host_backward <= 1e-12
        assert abs(backward-host_backward) <= 128*np.finfo(float).eps
    metadata = backend.metadata
    assert metadata["gpu_solve_calls"] == metadata["gpu_solve_completed_calls"] == 2
    assert metadata["successful_solves"] == 2 and metadata["cpu_fallback_calls"] == 0
    assert metadata["host_to_device_bytes"] > 0 and metadata["device_to_host_bytes"] >= 2*n*8
    assert metadata["solve_synchronized_wall_seconds"] >= 0
    assert metadata["residual_synchronized_wall_seconds"] >= 0
    assert metadata["last_solve"]["backward_error_computed_on"] == "CUDA"
    assert metadata["peak_managed_pool_bytes"] <= metadata["gpu_memory_budget_bytes"]
    json.dumps(metadata, allow_nan=False)
    metadata["successful_solves"] = 999
    assert backend.metadata["successful_solves"] == 2


def test_zero_residual_zero_denominator_rule_is_executed_on_GPU(actual_cuda):
    backend = CudaLinearSolver(*actual_cuda)
    A = sparse.eye(9, format="csc", dtype=np.float64)
    answer, backward = backend.solve(A, np.zeros(9, dtype=np.float64))
    np.testing.assert_array_equal(answer, np.zeros(9))
    assert backward == 0.
    assert backend.metadata["last_solve"]["backward_numerator"] == 0.
    assert backend.metadata["last_solve"]["backward_denominator"] == 0.


def test_canonicalization_preserves_input_and_gpu_equation(actual_cuda):
    # Duplicate, unsorted CSR entries are legal host inputs. The GPU transport
    # canonicalizes a copy and must not mutate the normalized Newton matrix.
    A = sparse.csr_matrix((np.array([.2, 2., .3, 3., -.1], dtype=np.float64),
                           np.array([1, 0, 1, 1, 0], dtype=np.int32),
                           np.array([0, 3, 5], dtype=np.int32)), shape=(2, 2))
    data_before, indices_before, ptr_before = A.data.copy(), A.indices.copy(), A.indptr.copy()
    residual = np.array([-.75, .4], dtype=np.float64)
    answer, backward = CudaLinearSolver(*actual_cuda).solve(A, residual)
    np.testing.assert_allclose(A @ answer, -residual, rtol=1e-12, atol=1e-13)
    np.testing.assert_array_equal(A.data, data_before)
    np.testing.assert_array_equal(A.indices, indices_before)
    np.testing.assert_array_equal(A.indptr, ptr_before)
    assert backward <= 1e-12


@pytest.mark.parametrize("bad_kind", ["float32_matrix", "float32_residual", "nonsquare", "vector_shape", "nonfinite"])
def test_invalid_inputs_fail_before_GPU_solve_without_fallback(actual_cuda, bad_kind):
    backend = CudaLinearSolver(*actual_cuda)
    A = sparse.eye(4, format="csr", dtype=np.float64)
    residual = np.ones(4, dtype=np.float64)
    if bad_kind == "float32_matrix": A = A.astype(np.float32)
    elif bad_kind == "float32_residual": residual = residual.astype(np.float32)
    elif bad_kind == "nonsquare": A = sparse.csr_matrix(np.ones((4, 3), dtype=np.float64))
    elif bad_kind == "vector_shape": residual = residual[:, None]
    else: A.data[0] = np.nan
    with pytest.raises(CudaBackendError):
        backend.solve(A, residual)
    assert backend.metadata["gpu_solve_calls"] == 0
    assert backend.metadata["host_to_device_bytes"] == 0
    assert backend.metadata["cpu_fallback_calls"] == 0
    assert backend.metadata["failed_solves"] == 1


def test_insufficient_memory_budget_fails_before_transfer(actual_cuda):
    # The admission estimate includes workspace, so a cap below its documented
    # minimum cannot quietly allocate beyond the configured budget.
    backend = CudaLinearSolver(actual_cuda[0], 1)
    with pytest.raises(CudaBackendError, match="CUDA_MEMORY_ADMISSION_FAILED"):
        backend.solve(sparse.eye(8, format="csr", dtype=np.float64), np.ones(8, dtype=np.float64))
    metadata = backend.metadata
    assert metadata["gpu_solve_calls"] == 0 and metadata["host_to_device_bytes"] == 0
    assert metadata["cpu_fallback_calls"] == 0


def test_invalid_device_and_memory_options_fail_explicitly(actual_cuda):
    device_id, memory_mb = actual_cuda
    metadata = probe_cuda(device_id, memory_mb)
    with pytest.raises(CudaBackendError, match="CUDA_DEVICE_UNAVAILABLE"):
        probe_cuda(metadata["visible_device_count"], memory_mb)
    with pytest.raises(CudaBackendError, match="CUDA_DEVICE_INVALID"):
        probe_cuda(-1, memory_mb)
    with pytest.raises(CudaBackendError, match="CUDA_MEMORY_BUDGET_INVALID"):
        probe_cuda(device_id, 0)
    with pytest.raises(CudaBackendError, match="CUDA_MEMORY_BUDGET_EXCEEDS_DEVICE"):
        probe_cuda(device_id, metadata["device_total_bytes"]/1024**2+1)
