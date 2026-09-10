"""SERVER ONLY: compare the unchanged PDE/integrator using actual CUDA solves.

Written but not executed locally. Production preflight requires every configured
device/budget pair. Only explicit optional-local mode permits missing-GPU skips.
"""
import os
from dataclasses import replace
import numpy as np
import pytest

from drying.config import RunConfig
from drying.cuda_backend import probe_cuda,CudaBackendError
from drying.execution import run_config,inspect_run


@pytest.fixture(scope='module')
def actual_cuda(cuda_options):
    device,memory=cuda_options
    try:
        metadata=probe_cuda(device_id=device,memory_mb=memory)
    except CudaBackendError as exc:
        optional=(os.environ.get('DRYING_REQUIRE_CUDA')!='1' and
                  os.environ.get('DRYING_CUDA_TEST_MODE')=='optional-local')
        if optional and exc.code in {'CUDA_DEPENDENCY_UNAVAILABLE','CUDA_DEVICE_UNAVAILABLE'}:
            pytest.skip(f'Explicit optional local mode; no GPU solve evidence: {exc}')
        pytest.fail(f'CUDA_REQUIRED: {exc}',pytrace=False)
    assert metadata['status']=='PASS' and metadata['backend']=='CUDA'
    assert metadata['dtype']=='float64' and metadata['float64_supported'] is True
    assert metadata['device_id']==device
    assert metadata['gpu_memory_budget_bytes']==memory*1024**2
    return cuda_options


@pytest.mark.cuda
@pytest.mark.parametrize('route,question,geometry,end_condition',[
    ('B',1,'fixed','C0'),('B',4,'moving','C0'),('C',23,'fixed','C1')])
def test_gpu_pde_matches_cpu_reference_without_cpu_linear_fallback(
        tmp_path,monkeypatch,actual_cuda,route,question,geometry,end_condition):
    device,memory=actual_cuda
    config=RunConfig(route=route,question=question,geometry=geometry,end_condition=end_condition,
        nr=4,nz=3 if route=='C' else 1,tmax=.5,wall_seconds=120,h0=.01,
        linear_backend='CPU_REFERENCE',execution_purpose='TEST_ONLY',
        cuda_device=device,gpu_memory_mb=memory)
    cpu=tmp_path/'cpu_reference'; gpu=tmp_path/'cuda'
    cpu_result=run_config(config,cpu)
    assert cpu_result['covered_seconds']==.5 and cpu_result['failure'] is None
    import drying.integrator as integration
    def forbidden(*args,**kwargs):
        raise AssertionError('GPU path attempted a CPU linear solve')
    monkeypatch.setattr(integration,'solve_banded',forbidden)
    monkeypatch.setattr(integration,'splu',forbidden)
    gpu_result=run_config(replace(config,linear_backend='CUDA'),gpu)
    assert gpu_result['covered_seconds']==.5 and gpu_result['failure'] is None
    metadata=gpu_result['linear_backend']
    assert metadata['backend']=='CUDA' and metadata['dtype']=='float64'
    assert metadata['device_id']==device and metadata['gpu_memory_budget_bytes']==memory*1024**2
    assert metadata['successful_solves']>0
    _,a,_=inspect_run(cpu); _,b,_=inspect_run(gpu)
    for t in [0.,.1,.25,.5]:
        ya,yb=a.at(t),b.at(t)
        np.testing.assert_allclose(ya[0::2],yb[0::2],rtol=0,atol=1e-6)
        np.testing.assert_allclose(ya[1::2],yb[1::2],rtol=0,atol=1e-8)
