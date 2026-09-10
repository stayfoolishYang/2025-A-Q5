from pathlib import Path
import json
import os
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))


def _cuda_request_pairs(environ):
    """Parse test routing only; never import/probe a CUDA runtime at collection."""
    try:
        raw=environ.get('DRYING_CUDA_TEST_REQUESTS')
        if raw is None:
            records=[{'cuda_device':int(environ.get('DRYING_CUDA_DEVICE','0')),
                      'gpu_memory_mb':int(environ.get('DRYING_GPU_MEMORY_MB','2048'))}]
        else:
            records=json.loads(raw)
        if not isinstance(records,list) or not records:
            raise ValueError('request list must be nonempty')
        pairs=set()
        for record in records:
            if not isinstance(record,dict) or set(record)!={'cuda_device','gpu_memory_mb'}:
                raise ValueError('each request must contain cuda_device and gpu_memory_mb only')
            device,memory=record['cuda_device'],record['gpu_memory_mb']
            if (isinstance(device,bool) or not isinstance(device,int) or device<0 or
                    isinstance(memory,bool) or not isinstance(memory,int) or memory<1):
                raise ValueError('device must be nonnegative and memory must be positive integer MiB')
            pairs.add((device,memory))
        return sorted(pairs)
    except (ValueError,TypeError) as exc:
        raise pytest.UsageError('CUDA_TEST_CONFIG_INVALID: '+str(exc)) from exc


def pytest_generate_tests(metafunc):
    if 'cuda_options' in metafunc.fixturenames:
        pairs=_cuda_request_pairs(os.environ)
        metafunc.parametrize('cuda_options',pairs,indirect=True,scope='module',
                             ids=[f'cuda{device}-{memory}MiB' for device,memory in pairs])


@pytest.fixture(scope='module')
def cuda_options(request):
    """Exact (device_id, memory_mb) used by both GPU test modules."""
    return request.param
