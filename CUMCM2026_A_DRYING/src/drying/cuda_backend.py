"""Required NVIDIA CUDA 12 float64 sparse linear algebra for server execution.

Importing this module does not import CuPy, initialize a device, or solve an
equation. ``probe_cuda`` and ``CudaLinearSolver`` construction are explicit
runtime GPU operations intended for the server. No CPU fallback exists here.

Only the linear Newton system moves to the GPU. The caller retains the exact
BDF/Newton equations, scaling, acceptance tolerance, and failure/retry policy.
"""
from __future__ import annotations

from copy import deepcopy
import importlib
import math
import threading
import time


class CudaBackendError(RuntimeError):
    """Fatal device/dependency/input failure, distinct from Newton rejection."""

    def __init__(self, code, message):
        self.code = str(code)
        super().__init__(f"{self.code}: {message}")


def _validate_options(device_id, memory_mb):
    if isinstance(device_id, bool) or not isinstance(device_id, int) or device_id < 0:
        raise CudaBackendError("CUDA_DEVICE_INVALID", "device_id must be a nonnegative integer")
    if isinstance(memory_mb, bool) or not isinstance(memory_mb, (int, float)):
        raise CudaBackendError("CUDA_MEMORY_BUDGET_INVALID", "memory_mb must be positive and finite")
    try:
        finite_value = float(memory_mb)
    except (OverflowError, ValueError) as exc:
        raise CudaBackendError("CUDA_MEMORY_BUDGET_INVALID", "memory_mb cannot be represented finitely") from exc
    if not math.isfinite(finite_value) or finite_value <= 0 or finite_value >= 2**43:
        raise CudaBackendError("CUDA_MEMORY_BUDGET_INVALID", "memory_mb must be positive, finite and representable in signed-int64 bytes")
    budget = int(memory_mb * 1024**2)
    if budget < 1:
        raise CudaBackendError("CUDA_MEMORY_BUDGET_INVALID", "memory budget is smaller than one byte")
    return budget


def _load_cuda():
    try:
        cp = importlib.import_module("cupy")
        sparse = importlib.import_module("cupyx.scipy.sparse")
        linalg = importlib.import_module("cupyx.scipy.sparse.linalg")
    except Exception as exc:
        raise CudaBackendError("CUDA_DEPENDENCY_UNAVAILABLE",
            "CuPy CUDA 12 and cupyx sparse linear algebra are required; " + str(exc)) from exc
    if bool(getattr(cp.cuda.runtime, "is_hip", False)):
        raise CudaBackendError("CUDA_PLATFORM_UNSUPPORTED", "ROCm/HIP does not satisfy the NVIDIA CUDA requirement")
    if not callable(getattr(linalg, "spsolve", None)):
        raise CudaBackendError("CUDA_SOLVER_UNAVAILABLE", "cupyx.scipy.sparse.linalg.spsolve is unavailable")
    return cp, sparse, linalg


def probe_cuda(device_id=0, memory_mb=2048):
    """Validate the real server device and return JSON-safe runtime metadata.

    This is a device capability probe, not evidence that a linear equation or
    a drying model has run. CUDA 12 runtime and a CUDA-12-capable NVIDIA driver
    are required; a newer compatible driver is permitted.
    """
    budget = _validate_options(device_id, memory_mb)
    cp, _, _ = _load_cuda()
    try:
        runtime_version = int(cp.cuda.runtime.runtimeGetVersion())
        driver_version = int(cp.cuda.runtime.driverGetVersion())
        if not 12000 <= runtime_version < 13000:
            raise CudaBackendError("CUDA_RUNTIME_UNSUPPORTED",
                                   f"CUDA 12.x runtime required, found encoded version {runtime_version}")
        if driver_version < 12000:
            raise CudaBackendError("CUDA_DRIVER_UNSUPPORTED",
                                   f"CUDA 12 capable driver required, found encoded version {driver_version}")
        count = int(cp.cuda.runtime.getDeviceCount())
        if device_id >= count:
            raise CudaBackendError("CUDA_DEVICE_UNAVAILABLE", f"device {device_id} requested; {count} device(s) visible")
        with cp.cuda.Device(device_id):
            props = cp.cuda.runtime.getDeviceProperties(device_id)
            major, minor = int(props["major"]), int(props["minor"])
            if major < 5:
                raise CudaBackendError("CUDA_DEVICE_UNSUPPORTED", "CUDA 12 backend requires compute capability >= 5.0")
            free, total = map(int, cp.cuda.runtime.memGetInfo())
            cp.cuda.runtime.deviceSynchronize()
        if total <= 0 or free <= 0 or free > total:
            raise CudaBackendError("CUDA_MEMORY_UNAVAILABLE", "invalid or exhausted device memory")
        if budget > total:
            raise CudaBackendError("CUDA_MEMORY_BUDGET_EXCEEDS_DEVICE",
                                   f"configured cap {budget} bytes exceeds device capacity {total} bytes")
        name = props.get("name", b"unknown")
        if isinstance(name, bytes):
            name = name.decode("utf-8", errors="replace")
        return {"status": "PASS", "backend": "CUDA", "dtype": "float64",
                "float64_supported": True, "float64_support_evidence": "NVIDIA_COMPUTE_CAPABILITY",
                "cupy_version": str(cp.__version__), "cuda_runtime_version": runtime_version,
                "cuda_driver_version": driver_version, "device_id": device_id,
                "device_name": str(name), "compute_capability": f"{major}.{minor}",
                "visible_device_count": count, "device_total_bytes": total, "device_free_bytes": free,
                "gpu_memory_budget_bytes": budget, "solver": "cupyx.scipy.sparse.linalg.spsolve",
                "solver_probe_performed": False, "cpu_fallback_enabled": False}
    except CudaBackendError:
        raise
    except Exception as exc:
        raise CudaBackendError("CUDA_PROBE_FAILED", str(exc)) from exc


class CudaLinearSolver:
    """Synchronous, serialized GPU solution of ``matrix @ answer = -residual``.

    Input matrices are CPU SciPy CSR/CSC and input residuals are CPU numpy
    float64 vectors. CSR conversion/canonicalization on the CPU is transport
    preparation; the sparse solve and backward-error norms execute on CUDA.

    ``memory_mb`` limits this solver's private CuPy memory pool. Admission
    additionally checks a conservative workspace estimate against device free
    memory. cuSOLVER may allocate internal workspace outside the CuPy pool:
    that transient peak is not hard-bounded or claimed measured by this API.
    Any allocation/runtime failure raises CudaBackendError without fallback.
    """

    reference_linear_tolerance = 1e-8

    def __init__(self, device_id=0, memory_mb=2048):
        self.device_id = device_id
        self.memory_budget_bytes = _validate_options(device_id, memory_mb)
        probe = probe_cuda(device_id, memory_mb)
        self._cp, self._sparse, self._linalg = _load_cuda()
        self._lock = threading.RLock()
        try:
            with self._cp.cuda.Device(device_id):
                self._pool = self._cp.cuda.MemoryPool()
                self._pool.set_limit(size=self.memory_budget_bytes)
        except Exception as exc:
            raise CudaBackendError("CUDA_ALLOCATOR_INITIALIZATION_FAILED", str(exc)) from exc
        self._metadata = dict(probe, status="PROBED_NOT_SOLVED", execution_status="PROBED_NOT_SOLVED", probe_calls=1,
            solve_calls=0, gpu_solve_calls=0, gpu_solve_completed_calls=0, successful_solves=0,
            failed_solves=0, validation_failures=0, reference_residual_exceedances=0,
            host_to_device_bytes=0, device_to_host_bytes=0, cpu_fallback_calls=0,
            total_wall_seconds=0., upload_synchronized_wall_seconds=0.,
            solve_synchronized_wall_seconds=0., residual_synchronized_wall_seconds=0.,
            download_synchronized_wall_seconds=0., peak_managed_pool_bytes=0,
            reference_linear_tolerance=self.reference_linear_tolerance,
            memory_limit_scope="PRIVATE_CUPY_POOL_AND_ADMISSION_NOT_CUSOLVER_INTERNAL_PEAK",
            workspace_estimate_kind="CONSERVATIVE_ADMISSION_ESTIMATE_NOT_A_PEAK_BOUND",
            timing_scope="HOST_WALL_WITH_DEVICE_SYNCHRONIZATION_NOT_PURE_KERNEL_TIME",
            phase_timing_scope="COMPLETED_PHASES_ONLY_TOTAL_WALL_INCLUDES_FAILED_ATTEMPTS",
            transfer_accounting="SUCCESSFULLY_ISSUED_ARRAY_COPIES_SYNCHRONIZED_BEFORE_SUCCESSFUL_RETURN",
            backward_error_computed_on="CUDA", solve_equation="A*x=-residual",
            last_solve=None, last_error=None)

    @property
    def metadata(self):
        """Independent JSON-safe snapshot; callers cannot mutate backend counters."""
        with self._lock:
            return deepcopy(self._metadata)

    def _prepare_cpu(self, matrix, residual):
        import numpy as np
        from scipy import sparse
        if not sparse.issparse(matrix) or matrix.format not in {"csr", "csc"}:
            raise CudaBackendError("CUDA_INPUT_MATRIX_INVALID", "CPU SciPy CSR/CSC matrix required")
        if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1] or matrix.shape[0] == 0:
            raise CudaBackendError("CUDA_INPUT_SHAPE_INVALID", "nonempty square matrix required")
        if matrix.dtype != np.dtype("float64"):
            raise CudaBackendError("CUDA_INPUT_DTYPE_INVALID", "matrix must already use float64")
        if not isinstance(residual, np.ndarray) or residual.dtype != np.dtype("float64"):
            raise CudaBackendError("CUDA_INPUT_DTYPE_INVALID", "CPU numpy float64 residual required")
        if residual.shape != (matrix.shape[0],):
            raise CudaBackendError("CUDA_INPUT_SHAPE_INVALID", "residual must be a vector matching the matrix")
        if np.any(~np.isfinite(matrix.data)) or np.any(~np.isfinite(residual)):
            raise CudaBackendError("CUDA_INPUT_NONFINITE", "matrix and residual entries must be finite")
        n = matrix.shape[0]
        index_limit = np.iinfo(np.int32).max
        if n > index_limit or matrix.nnz > index_limit:
            raise CudaBackendError("CUDA_INDEX_LIMIT", "cuSOLVER spsolve transport requires signed int32 CSR indices")
        try:
            # Copy prevents canonicalization or index conversion from changing
            # the parent's current normalized Newton Jacobian.
            csr = matrix.tocsr(copy=True)
            csr.check_format(full_check=True)
            csr.sum_duplicates()
            csr.sort_indices()
            if np.any(~np.isfinite(csr.data)):
                raise CudaBackendError("CUDA_INPUT_NONFINITE", "duplicate summation produced a nonfinite coefficient")
            data = np.ascontiguousarray(csr.data, dtype=np.float64)
            indices = np.ascontiguousarray(csr.indices, dtype=np.int32)
            indptr = np.ascontiguousarray(csr.indptr, dtype=np.int32)
            rhs = np.ascontiguousarray(residual)
        except CudaBackendError:
            raise
        except Exception as exc:
            raise CudaBackendError("CUDA_INPUT_MATRIX_INVALID", str(exc)) from exc
        payload = int(data.nbytes + indices.nbytes + indptr.nbytes + rhs.nbytes)
        workspace = int(max(2 * 1024**2, 24*(data.nbytes + indices.nbytes) + 32*rhs.nbytes))
        estimated = payload + workspace
        if estimated > self.memory_budget_bytes:
            raise CudaBackendError("CUDA_MEMORY_ADMISSION_FAILED",
                f"estimated managed data/workspace {estimated} bytes exceeds configured cap {self.memory_budget_bytes}")
        return data, indices, indptr, rhs, payload, estimated

    def _device_solve(self, prepared):
        import numpy as np
        cp = self._cp
        data, indices, indptr, residual, payload, estimated = prepared
        n = residual.size
        with cp.cuda.Device(self.device_id), cp.cuda.using_allocator(self._pool.malloc):
            free_before, total = map(int, cp.cuda.runtime.memGetInfo())
            available = free_before + int(self._pool.free_bytes())
            if estimated > available:
                raise CudaBackendError("CUDA_MEMORY_ADMISSION_FAILED",
                    f"estimated data/workspace {estimated} bytes exceeds currently available {available} bytes")
            cp.cuda.runtime.deviceSynchronize()
            start = time.perf_counter()
            def upload(array):
                gpu = cp.asarray(array)
                self._metadata["host_to_device_bytes"] += int(array.nbytes)
                return gpu
            gpu_data, gpu_indices, gpu_indptr, gpu_residual = (upload(x) for x in (data, indices, indptr, residual))
            gpu_matrix = self._sparse.csr_matrix((gpu_data, gpu_indices, gpu_indptr), shape=(n, n))
            if gpu_matrix.dtype != cp.dtype("float64") or gpu_residual.dtype != cp.dtype("float64"):
                raise CudaBackendError("CUDA_DEVICE_DTYPE_INVALID", "transport changed float64 dtype")
            if gpu_matrix.data.device.id != self.device_id or gpu_residual.device.id != self.device_id:
                raise CudaBackendError("CUDA_DEVICE_MISMATCH", "matrix or residual is on a different CUDA device")
            cp.cuda.runtime.deviceSynchronize()
            upload_seconds = time.perf_counter() - start
            self._metadata["upload_synchronized_wall_seconds"] += upload_seconds

            start = time.perf_counter()
            self._metadata["gpu_solve_calls"] += 1
            # Required actual CUDA sparse solve. There is deliberately no
            # scipy.sparse.linalg/NumPy solve or exception-to-CPU path.
            answer_gpu = self._linalg.spsolve(gpu_matrix, -gpu_residual)
            cp.cuda.runtime.deviceSynchronize()
            solve_seconds = time.perf_counter() - start
            self._metadata["solve_synchronized_wall_seconds"] += solve_seconds
            self._metadata["gpu_solve_completed_calls"] += 1
            if not isinstance(answer_gpu, cp.ndarray) or answer_gpu.dtype != cp.dtype("float64"):
                raise CudaBackendError("CUDA_SOLVER_DTYPE_INVALID", "CUDA spsolve did not return a float64 device array")
            if answer_gpu.shape != (n,) or answer_gpu.device.id != self.device_id:
                raise CudaBackendError("CUDA_SOLVER_OUTPUT_INVALID", "CUDA solution shape/device mismatch")

            start = time.perf_counter()
            # All norm reductions and A*x+r are on the device. The mathematical
            # backward-error definition is identical to Stage04 section 6.8.
            norm_a = cp.max(cp.asarray(abs(gpu_matrix).sum(axis=1)).ravel())
            norm_x = cp.max(cp.abs(answer_gpu))
            norm_r = cp.max(cp.abs(gpu_residual))
            numerator = cp.max(cp.abs(gpu_matrix @ answer_gpu + gpu_residual))
            denominator = norm_a*norm_x + norm_r
            safe_denominator = cp.where(denominator == 0, cp.float64(1.), denominator)
            backward_gpu = cp.where(denominator == 0,
                cp.where(numerator == 0, cp.float64(0.), cp.float64(cp.inf)), numerator/safe_denominator)
            nonfinite_answer = cp.count_nonzero(~cp.isfinite(answer_gpu)).astype(cp.float64)
            checks_gpu = cp.stack((backward_gpu, numerator, denominator, norm_a, norm_x, norm_r, nonfinite_answer))
            cp.cuda.runtime.deviceSynchronize()
            residual_seconds = time.perf_counter() - start
            self._metadata["residual_synchronized_wall_seconds"] += residual_seconds

            start = time.perf_counter()
            checks = cp.asnumpy(checks_gpu)
            self._metadata["device_to_host_bytes"] += int(checks.nbytes)
            if not np.all(np.isfinite(checks)) or checks[6] != 0:
                raise CudaBackendError("CUDA_SOLVER_NONFINITE", "nonfinite solution, norm or backward residual")
            answer = cp.asnumpy(answer_gpu)
            self._metadata["device_to_host_bytes"] += int(answer.nbytes)
            cp.cuda.runtime.deviceSynchronize()
            download_seconds = time.perf_counter() - start
            self._metadata["download_synchronized_wall_seconds"] += download_seconds
            free_after, _ = map(int, cp.cuda.runtime.memGetInfo())
            self._metadata["peak_managed_pool_bytes"] = max(self._metadata["peak_managed_pool_bytes"], int(self._pool.total_bytes()))
            backward = float(checks[0])
            last = {"n": int(n), "nnz": int(data.size), "dtype": "float64", "device_id": self.device_id,
                    "host_to_device_bytes": payload, "device_to_host_bytes": int(checks.nbytes + answer.nbytes),
                    "estimated_device_bytes": estimated, "device_free_before_bytes": free_before,
                    "device_free_after_bytes": free_after, "backward_error": backward,
                    "backward_numerator": float(checks[1]), "backward_denominator": float(checks[2]),
                    "matrix_inf_norm": float(checks[3]), "solution_inf_norm": float(checks[4]),
                    "residual_inf_norm": float(checks[5]), "backward_error_computed_on": "CUDA",
                    "within_reference_tolerance": backward <= self.reference_linear_tolerance,
                    "upload_synchronized_wall_seconds": upload_seconds,
                    "solve_synchronized_wall_seconds": solve_seconds,
                    "residual_synchronized_wall_seconds": residual_seconds,
                    "download_synchronized_wall_seconds": download_seconds}
            return answer, backward, last

    def solve(self, matrix, residual):
        """Return CPU answer and GPU-computed finite backward error.

        A finite error above the acceptance threshold is returned unchanged:
        the caller must apply its current ``linear_tol`` and preserve the
        specified numerical rejection/step-reduction policy. Device failures
        are fatal CudaBackendError instances and never request CPU fallback.
        """
        with self._lock:
            start = time.perf_counter()
            self._metadata["solve_calls"] += 1
            prepared = None
            try:
                prepared = self._prepare_cpu(matrix, residual)
                answer, backward, last = self._device_solve(prepared)
                self._metadata["successful_solves"] += 1
                self._metadata["reference_residual_exceedances"] += int(backward > self.reference_linear_tolerance)
                self._metadata["last_solve"] = last
                self._metadata["last_error"] = None
                self._metadata["execution_status"] = "CUDA_SOLVE_RETURNED_FINITE_CANDIDATE"
                self._metadata["status"] = "CUDA_FINITE_CANDIDATE"
                return answer, backward
            except CudaBackendError as exc:
                self._metadata["failed_solves"] += 1
                self._metadata["validation_failures"] += int(prepared is None)
                self._metadata["last_error"] = {"code": exc.code, "message": str(exc)}
                self._metadata["execution_status"] = "CUDA_FAILED_NO_FALLBACK"
                self._metadata["status"] = "GPU_BACKEND_FAILURE"
                raise
            except Exception as exc:
                self._metadata["failed_solves"] += 1
                code = "CUDA_OUT_OF_MEMORY" if isinstance(exc, self._cp.cuda.memory.OutOfMemoryError) else "CUDA_SOLVE_FAILED"
                error = CudaBackendError(code, str(exc))
                self._metadata["last_error"] = {"code": code, "message": str(error)}
                self._metadata["execution_status"] = "CUDA_FAILED_NO_FALLBACK"
                self._metadata["status"] = "GPU_BACKEND_FAILURE"
                raise error from exc
            finally:
                # _device_solve has returned/unwound, so its arrays are no longer
                # retained by this backend. Release cached blocks from this
                # private pool only; do not alter another component's allocator.
                cleanup_error = None
                try:
                    with self._cp.cuda.Device(self.device_id):
                        self._cp.cuda.runtime.deviceSynchronize()
                        self._pool.free_all_blocks()
                except Exception as exc:
                    self._metadata["cleanup_error"] = str(exc)
                    cleanup_error = exc
                self._metadata["total_wall_seconds"] += time.perf_counter() - start
                if cleanup_error is not None and self._metadata["last_error"] is None:
                    self._metadata["successful_solves"] -= 1
                    self._metadata["failed_solves"] += 1
                    self._metadata["execution_status"] = "CUDA_FAILED_NO_FALLBACK"
                    self._metadata["status"] = "GPU_BACKEND_FAILURE"
                    self._metadata["last_error"] = {"code": "CUDA_CLEANUP_FAILED", "message": str(cleanup_error)}
                    raise CudaBackendError("CUDA_CLEANUP_FAILED", str(cleanup_error)) from cleanup_error
