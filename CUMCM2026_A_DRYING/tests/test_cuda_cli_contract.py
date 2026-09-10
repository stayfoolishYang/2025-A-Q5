"""Server-run routing tests with mocked execution; not run on the local host.

These tests exercise transport, selection and failure propagation, never CUDA
availability or numerical correctness. Actual solves live in the CUDA suites.
"""
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from conftest import _cuda_request_pairs
import drying.cli as cli
from drying.config import RunConfig


def _record(device,memory,backend='CUDA'):
    return {'linear_backend':backend,'cuda_device':device,'gpu_memory_mb':memory}


def test_gpu_test_requests_deduplicate_full_pairs_and_exclude_cpu_reference():
    records=[_record(2,1024),_record(1,512),_record(2,1024),_record(2,2048),
             _record(0,2048,'CPU_REFERENCE')]
    assert cli._cuda_test_requests(records)==[
        {'cuda_device':1,'gpu_memory_mb':512},
        {'cuda_device':2,'gpu_memory_mb':1024},
        {'cuda_device':2,'gpu_memory_mb':2048}]
    with pytest.raises(ValueError,match='CUDA_TEST_CONFIG_REQUIRED'):
        cli._cuda_test_requests([_record(0,2048,'CPU_REFERENCE')])


def test_required_pytest_receives_complete_set_over_ambient_single_device(tmp_path,monkeypatch):
    monkeypatch.setattr(cli,'ROOT',tmp_path)
    monkeypatch.setenv('DRYING_CUDA_DEVICE','99')
    monkeypatch.setenv('DRYING_GPU_MEMORY_MB','1')
    monkeypatch.setenv('DRYING_CUDA_TEST_MODE','optional-local')
    requests=cli._cuda_test_requests([_record(3,1024),_record(1,512)])
    captured={}
    def fake_subprocess(command,**kwargs):
        captured.update(command=command,**kwargs)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(cli.subprocess,'run',fake_subprocess)
    assert cli._tests(requests)==0
    assert captured['env']['DRYING_REQUIRE_CUDA']=='1'
    assert json.loads(captured['env']['DRYING_CUDA_TEST_REQUESTS'])==requests
    assert _cuda_request_pairs(captured['env'])==[(1,512),(3,1024)]
    assert captured['cwd']==tmp_path


@pytest.mark.parametrize('raw',[
    '[]','{}','null','not-json',
    '[{"cuda_device":true,"gpu_memory_mb":256}]',
    '[{"cuda_device":-1,"gpu_memory_mb":256}]',
    '[{"cuda_device":0,"gpu_memory_mb":0}]',
    '[{"cuda_device":0,"gpu_memory_mb":1.5}]',
    '[{"cuda_device":0,"gpu_memory_mb":256,"extra":1}]'])
def test_invalid_gpu_test_request_transport_fails_closed(raw):
    with pytest.raises(pytest.UsageError,match='CUDA_TEST_CONFIG_INVALID'):
        _cuda_request_pairs({'DRYING_CUDA_TEST_REQUESTS':raw})


def test_manual_gpu_suite_uses_explicit_single_pair_when_no_plan_payload():
    assert _cuda_request_pairs({'DRYING_CUDA_DEVICE':'2','DRYING_GPU_MEMORY_MB':'768'})==[(2,768)]


@pytest.mark.parametrize('test_exit_code',[0,1,-15])
def test_standalone_preflight_tests_all_validated_config_pairs(tmp_path,monkeypatch,test_exit_code):
    import drying.preflight as preflight
    records=[_record(4,512),_record(4,1024),_record(4,512),_record(0,2048,'CPU_REFERENCE')]
    report={'status':'PASS','configs':{'files':records},'failures':[]}
    monkeypatch.setattr(preflight,'run_preflight',lambda **kwargs:report)
    seen=[]
    def fake_tests(requests):
        seen.append(requests)
        return test_exit_code
    monkeypatch.setattr(cli,'_tests',fake_tests)
    output=tmp_path/'preflight.json'
    expected_code=1 if test_exit_code<0 else test_exit_code
    assert cli.main(['preflight','--tests','--output',str(output)])==expected_code
    expected=[{'cuda_device':4,'gpu_memory_mb':512},{'cuda_device':4,'gpu_memory_mb':1024}]
    assert seen==[expected]
    saved=json.loads(output.read_text(encoding='utf-8'))
    assert saved['gpu_test_requests']==expected and saved['preflight_checks_status']=='PASS'
    assert saved['status']==('PASS' if test_exit_code==0 else 'FAIL')
    assert saved['pytest_exit_code']==test_exit_code


@pytest.mark.parametrize('mutate_after_tests',[False,True])
def test_pipeline_tests_selected_pairs_and_blocks_postcheck_config_changes(tmp_path,monkeypatch,mutate_after_tests):
    import drying.preflight as preflight
    import drying.reporting as reporting
    monkeypatch.setattr(cli,'ROOT',tmp_path)
    monkeypatch.chdir(tmp_path)
    configs=tmp_path/'configs';configs.mkdir()
    selected=RunConfig(cuda_device=2,gpu_memory_mb=768)
    selected.to_json(configs/'selected.json')
    unselected=RunConfig(cuda_device=0,gpu_memory_mb=2048)
    unselected.to_json(configs/'unselected.json')
    plan=configs/'plan.json'
    plan.write_text(json.dumps({'runs':[{'config':'configs/selected.json','out':'results/run'}]}),encoding='utf-8')
    monkeypatch.setattr(preflight,'run_preflight',lambda **kwargs:{'status':'PASS','configs':{'files':[
        _record(2,768),_record(0,2048)]}})
    seen=[];runs=[]
    def fake_tests(requests):
        seen.append(requests)
        if mutate_after_tests:
            replace(selected,cuda_device=3).to_json(configs/'selected.json')
        return 0
    monkeypatch.setattr(cli,'_tests',fake_tests)
    def fake_run(config,out):
        runs.append(config)
        return {'status':'TIME_LIMIT_REACHED'}
    monkeypatch.setattr(cli,'run_config',fake_run)
    monkeypatch.setattr(reporting,'summarize_run',lambda *args:None)
    assert cli.main(['pipeline','--plan',str(plan)])==(1 if mutate_after_tests else 0)
    assert seen==[[{'cuda_device':2,'gpu_memory_mb':768}]]
    assert runs==([] if mutate_after_tests else [selected])


@pytest.mark.parametrize('status,expected_code',[
    ('GPU_BACKEND_FAILURE',1),('NUMERICAL_FAILURE',1),('EXECUTION_EXCEPTION',1),
    ('MEMORY_BUDGET_REACHED',1),('WALL_BUDGET_REACHED',2),('EVENT_UNRESOLVED',2)])
@pytest.mark.parametrize('command',['refine-event','prepare-report'])
def test_refinement_cli_preserves_hard_failure_class(tmp_path,monkeypatch,status,expected_code,command):
    import drying.refinement as refinement
    function='refine_event' if command=='refine-event' else 'prepare_strict_report'
    monkeypatch.setattr(refinement,function,lambda *args,**kwargs:{'status':status})
    argv=[command,'unused-run','--out',str(tmp_path/'result')]
    if command=='prepare-report':
        evidence=tmp_path/'evidence.json';evidence.write_text('{}',encoding='utf-8')
        argv+=['--evidence',str(evidence)]
    assert cli.main(argv)==expected_code
