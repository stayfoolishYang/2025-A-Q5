"""Finite CLI; commands persist artifacts and return nonzero on unresolved work."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import os
from .config import RunConfig
from .execution import ROOT,run_config,inspect_run
from .trajectory import atomic_json


def _cuda_test_requests(records):
    """Bind server acceptance tests to each configured device/budget pair."""
    requests=set()
    for record in records:
        if record.get('linear_backend')!='CUDA':
            continue
        device,memory=record['cuda_device'],record['gpu_memory_mb']
        if (isinstance(device,bool) or not isinstance(device,int) or device<0 or
                isinstance(memory,bool) or not isinstance(memory,int) or memory<1):
            raise ValueError('CUDA_TEST_CONFIG_INVALID: expected nonnegative device and positive integer MiB')
        requests.add((device,memory))
    if not requests:
        raise ValueError('CUDA_TEST_CONFIG_REQUIRED: no configured CUDA device/budget pair')
    return [{'cuda_device':device,'gpu_memory_mb':memory} for device,memory in sorted(requests)]


def _tests(cuda_requests):
    # The shared pytest fixture prefers this complete set over ambient legacy
    # single-device variables. Each GPU test runs for every requested pair.
    env=dict(os.environ,DRYING_REQUIRE_CUDA='1',
             DRYING_CUDA_TEST_REQUESTS=json.dumps(cuda_requests,allow_nan=False))
    (ROOT/'results').mkdir(exist_ok=True)
    return subprocess.run([sys.executable,'-m','pytest','-q',
                           '--junitxml=results/server_tests.xml'],cwd=ROOT,env=env).returncode


def main(argv=None):
    p=argparse.ArgumentParser(description='A26-04-v2 Stage06 server runner')
    commands=p.add_subparsers(dest='command',required=True)
    s=commands.add_parser('preflight'); s.add_argument('--tests',action='store_true'); s.add_argument('--output',default='results/preflight.json')
    s=commands.add_parser('run'); s.add_argument('--config',required=True); s.add_argument('--out',required=True); s.add_argument('--resume',action='store_true')
    s=commands.add_parser('pipeline'); s.add_argument('--plan',default='configs/server_first_round.json')
    s=commands.add_parser('full-run',help='bounded full server campaign with restartable evidence collection')
    s.add_argument('--plan',default='configs/server_full.json'); s.add_argument('--out',required=True)
    s.add_argument('--resume',action='store_true'); s.add_argument('--plan-only',action='store_true')
    s=commands.add_parser('_campaign-worker',help=argparse.SUPPRESS); s.add_argument('--request',required=True)
    s=commands.add_parser('summarize'); s.add_argument('run_dir')
    s=commands.add_parser('compare-q1'); s.add_argument('run_a'); s.add_argument('run_b'); s.add_argument('--out',required=True)
    s=commands.add_parser('refine-event'); s.add_argument('run_dir'); s.add_argument('--out',required=True); s.add_argument('--threshold',type=float,default=.15); s.add_argument('--width',type=float,default=.01); s.add_argument('--wall-seconds',type=float,default=3600)
    s=commands.add_parser('error-evidence'); s.add_argument('reference_run'); s.add_argument('--categories',required=True); s.add_argument('--out',required=True)
    s=commands.add_parser('plan-refinement'); s.add_argument('--config',required=True); s.add_argument('--out',required=True)
    s=commands.add_parser('prepare-report'); s.add_argument('run_dir'); s.add_argument('--evidence',required=True); s.add_argument('--out',required=True); s.add_argument('--wall-seconds',type=float,default=300)
    s=commands.add_parser('recompute-balances'); s.add_argument('run_dir'); s.add_argument('--out'); s.add_argument('--wall-seconds',type=float,default=300)
    s=commands.add_parser('certify'); s.add_argument('run_dir'); s.add_argument('--evidence',required=True); s.add_argument('--candidate',required=True); s.add_argument('--out',required=True)
    s=commands.add_parser('export'); s.add_argument('run_dir'); s.add_argument('--out',required=True); s.add_argument('--event'); s.add_argument('--q1-reviewed',action='store_true')
    s=commands.add_parser('verify-output'); s.add_argument('run_dir'); s.add_argument('workbook'); s.add_argument('--end',required=True,type=float); s.add_argument('--question',type=int,choices=[1,2,3,4],required=True)
    s=commands.add_parser('pack-return'); s.add_argument('--runs',default='results/runs'); s.add_argument('--out',required=True); s.add_argument('--full',action='store_true')
    args=p.parse_args(argv)
    try:
        result={}; code=0
        if args.command=='_campaign-worker':
            from .campaign import _worker
            return _worker(args.request)
        elif args.command=='full-run':
            from .campaign import run_campaign
            result=run_campaign(args.plan,args.out,resume=args.resume,plan_only=args.plan_only)
            code=result['exit_code']
        elif args.command=='preflight':
            from .preflight import run_preflight
            result=run_preflight(output=args.output)
            if result.get('status')!='PASS': code=1
            if args.tests and code==0:
                requests=_cuda_test_requests(result['configs']['files'])
                result['gpu_test_requests']=requests
                result['preflight_checks_status']=result['status']
                test_code=_tests(requests); result['pytest_exit_code']=test_code
                code=(test_code if test_code>0 else 1) if test_code else 0
                if test_code:
                    result['status']='FAIL'
                    result.setdefault('failures',[]).append('Required server tests failed; pytest exit code '+str(test_code))
                atomic_json(args.output,result)
        elif args.command=='run':
            result=run_config(RunConfig.from_json(args.config),args.out,resume=args.resume)
            if result['status'] in ['EXECUTION_EXCEPTION','NUMERICAL_FAILURE','MEMORY_BUDGET_REACHED','GPU_BACKEND_FAILURE']: code=1
            elif result['status'] in ['WALL_BUDGET_REACHED','STEP_BUDGET_REACHED']: code=2
        elif args.command=='pipeline':
            from .preflight import run_preflight,_pipeline_config
            from .reporting import summarize_run
            if run_preflight(output='results/preflight.json').get('status')!='PASS':
                raise RuntimeError('PREFLIGHT_FAILED; no production job started')
            plan=json.loads(Path(args.plan).read_text(encoding='utf-8'))
            checked_plan=_pipeline_config(ROOT,Path(args.plan).resolve(),plan)
            requests=_cuda_test_requests(checked_plan['runs'])
            if _tests(requests): raise RuntimeError('PREFLIGHT_TESTS_FAILED; no production job started')
            runs=[]
            for job,checked in zip(plan['runs'],checked_plan['runs']):
                config=RunConfig.from_json(ROOT/job['config'])
                if config.fingerprint!=checked['config_fingerprint']:
                    raise ValueError('CONFIG_CHANGED_AFTER_PREFLIGHT: '+job['config'])
                result=run_config(config,ROOT/job['out'])
                runs.append(result)
                if result['status'] in ['EXECUTION_EXCEPTION','NUMERICAL_FAILURE','MEMORY_BUDGET_REACHED','GPU_BACKEND_FAILURE']:
                    code=1; break
                if result['status'] in ['WALL_BUDGET_REACHED','STEP_BUDGET_REACHED']: code=2
                summarize_run(ROOT/job['out'])
            result={'runs':runs,'status':'COMPLETE_INTERVALS' if code==0 else 'PARTIAL_OR_FAILED',
                    'gpu_test_requests':requests,'stage07':'NOT_RUN'}
            atomic_json('results/pipeline_summary.json',result)
        elif args.command=='summarize':
            from .reporting import summarize_run
            result=summarize_run(args.run_dir)
        elif args.command=='compare-q1':
            from .reporting import compare_q1_development
            result=compare_q1_development(args.run_a,args.run_b,args.out)
        elif args.command=='refine-event':
            from .refinement import refine_event
            result=refine_event(args.run_dir,args.out,threshold=args.threshold,width=args.width,wall_seconds=args.wall_seconds)
            if result.get('status') in ['GPU_BACKEND_FAILURE','NUMERICAL_FAILURE','EXECUTION_EXCEPTION','MEMORY_BUDGET_REACHED']: code=1
            elif result.get('status')!='EVENT_BRACKET_REFINED': code=2
        elif args.command=='error-evidence':
            from .refinement import build_error_evidence
            result=build_error_evidence(args.reference_run,json.loads(Path(args.categories).read_text(encoding='utf-8')),out_path=args.out)
            if not result.get('checks_passed'): code=2
        elif args.command=='plan-refinement':
            from .refinement import plan_refinement_configs
            if Path(args.out).exists(): raise FileExistsError(args.out)
            result=plan_refinement_configs(RunConfig.from_json(args.config)); atomic_json(args.out,result)
        elif args.command=='prepare-report':
            from .refinement import prepare_strict_report
            result=prepare_strict_report(args.run_dir,json.loads(Path(args.evidence).read_text(encoding='utf-8')),args.out,wall_seconds=args.wall_seconds)
            if result.get('status') in ['GPU_BACKEND_FAILURE','NUMERICAL_FAILURE','EXECUTION_EXCEPTION','MEMORY_BUDGET_REACHED']: code=1
            elif result.get('status')!='PROVISIONAL_EVENT': code=2
        elif args.command=='recompute-balances':
            from .refinement import recompute_balances
            result=recompute_balances(args.run_dir,out_path=args.out,wall_seconds=args.wall_seconds)
            if not result.get('checks_passed'): code=2
        elif args.command=='certify':
            from .refinement import certify_strict_report
            result=certify_strict_report(args.run_dir,json.loads(Path(args.evidence).read_text(encoding='utf-8')),
                    json.loads(Path(args.candidate).read_text(encoding='utf-8')),out_path=args.out)
            if result.get('status')!='DRYING_COMPLETE': code=2
        elif args.command=='export':
            from .export import export_workbooks
            system,trajectory,config=inspect_run(args.run_dir)
            event=json.loads(Path(args.event).read_text(encoding='utf-8')) if args.event else None
            result=export_workbooks(system,trajectory,args.out,config.question,event_record=event,developer_approved=args.q1_reviewed)
        elif args.command=='verify-output':
            from .export import verify_workbook
            system,trajectory,config=inspect_run(args.run_dir)
            if args.question not in ([2,3] if config.question==23 else [config.question]):
                raise ValueError('workbook question incompatible with run')
            result=verify_workbook(args.workbook,system,trajectory,args.question,args.end)
        elif args.command=='pack-return':
            from .reporting import pack_return
            result=pack_return(args.runs,args.out,args.full)
        print(json.dumps(result,ensure_ascii=False,indent=2,default=str,allow_nan=False))
        return code
    except Exception as exc:
        print(json.dumps({'status':'COMMAND_FAILED','error':str(exc),'command':args.command},ensure_ascii=False),file=sys.stderr)
        return 1
