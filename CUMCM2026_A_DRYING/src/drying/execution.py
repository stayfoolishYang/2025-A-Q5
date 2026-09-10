"""Run identities, finite execution, checkpoints and honest development artifacts."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import importlib.metadata as metadata
import io
import contextlib
import json
import platform
import sys
import time
import traceback
import shutil
import ast
import numpy as np

from .config import RunConfig
from .inputs import Inputs
from .spatial import Grid, DryingSystem
from .manufactured import ManufacturedCase
from .integrator import Integrator, Settings
from .diagnostics import Diagnostics
from .trajectory import Trajectory, TrajectoryWriter, atomic_json, fingerprint, save_checkpoint, load_checkpoint, recover_trajectory
from .resources import process_memory_mb, MemoryBudgetReached


ROOT=Path(__file__).resolve().parents[2]


def _factory_hash(source):
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='make_system')
    return hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest()


def system_identity(system,config):
    return {'route':system.grid.route,'nr':system.grid.nr,'nz':system.grid.nz,
            'question':system.question,'geometry':system.geometry,'end_condition':system.end_condition,
            'h':system.h,'hm':system.hm,'model_version':config.model_version,
            'test_case':config.test_case,'dtype':'float64'}


def verify_system_identity(manifest,system,config,run_dir=None):
    actual=system_identity(system,config)
    live_factory=_factory_hash(Path(__file__).read_text(encoding='utf-8'))
    if 'system_contract' in manifest:
        if manifest['system_contract']!=actual or manifest['identity'].get('system')!=fingerprint(actual):
            raise ValueError('system construction identity mismatch')
        if manifest.get('factory_sha256')!=live_factory:
            raise ValueError('system factory changed; use the recorded source_snapshot')
    else:
        # These two constructor ASTs were inspected during Stage06. The only
        # difference is attachment of output tolerances/capacity, not the PDE.
        approved={'c46c8b0b635c94d9a09c030a0caa2d7988495df912c7cc77ba9b2f853ef89f68',
                  '474b2742afee695d08bd5f96aefdb67ef191ba73f23c13918494a4644be19d30'}
        if run_dir is None: raise ValueError('legacy source_snapshot required')
        source=Path(run_dir)/'source_snapshot/src/drying/execution.py'
        if not source.exists() or hashlib.sha256(source.read_bytes()).hexdigest()!=manifest['source']['files'].get('src/drying/execution.py'):
            raise ValueError('legacy constructor source_snapshot missing or changed')
        if _factory_hash(source.read_text(encoding='utf-8')) not in approved or live_factory not in approved:
            raise ValueError('unreviewed legacy system constructor')
    return actual


def code_identity():
    files={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
           for p in sorted((ROOT/'src').rglob('*.py'))}
    return {'sha256':fingerprint(files),'files':files,'uncommitted_source_snapshot':True}


def environment():
    buff=io.StringIO()
    with contextlib.redirect_stdout(buff): np.show_config()
    return {'python':sys.version,'executable':sys.executable,'platform':platform.platform(),
            'machine':platform.machine(),'processor':platform.processor(),'dtype':'float64',
            'dependencies':{p:metadata.version(p) for p in ['numpy','scipy','openpyxl']},
            'linear_algebra':buff.getvalue()}


def make_system(config,data_dir=None):
    inputs=Inputs(data_dir or ROOT/'data/raw',scenario=config.scenario,
                  radius_method=config.radius_method,radius_tail=config.radius_tail,
                  window_start_h=config.window_start_h)
    grid=Grid(config.nr,config.nz,config.route)
    test=None
    if config.test_case is not None:
        if config.test_case not in ['MMS_FIXED','MMS_MOVING']:
            raise ValueError('unsupported isolated TEST_CASE')
        test=ManufacturedCase(moving=config.test_case=='MMS_MOVING',route=config.route)
    system=DryingSystem(grid,inputs,question=config.question,geometry=config.geometry,
                        end_condition=config.end_condition,test_case=test)
    system.reconstruction_rtol=config.rtol
    system.reconstruction_atol_t=config.atol_t
    system.reconstruction_atol_c=config.atol_c
    system.max_output_rows=config.max_output_rows
    return system


def run_config(config,run_dir,*,data_dir=None,resume=False,diagnostic=True):
    # Conservative admission estimate for state/Jacobian/chunk storage, before allocation.
    estimated_mb=process_memory_mb()+config.nr*config.nz*2*(256*8+1024)/2**20
    if estimated_mb>config.memory_mb:
        raise MemoryBudgetReached(f'MEMORY_ADMISSION_FAILED: estimated {estimated_mb:.1f} MiB > {config.memory_mb}')
    run_dir=Path(run_dir); system=make_system(config,data_dir)
    if run_dir.exists() and not resume: raise FileExistsError(f'run already exists: {run_dir}')
    run_dir.mkdir(parents=True,exist_ok=True)
    cfgdict=config.as_dict(); code=code_identity()
    if not resume:
        for relative in code['files']:
            target=run_dir/'source_snapshot'/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/relative,target)
    identity={'config':config.fingerprint,'input':system.inputs.fingerprint,'code':code['sha256'],
              'model_version':config.model_version,'dtype':'float64','system':fingerprint(system_identity(system,config))}
    solver=Integrator(system,Settings.from_config(config))
    checkpoint=run_dir/'checkpoint.json'
    extra={}
    if resume:
        extra=load_checkpoint(checkpoint,solver,identity)
        recovered=recover_trajectory(run_dir/'trajectory',solver.t)
        if recovered and (run_dir/'steps.jsonl').exists():
            revision=1
            archive=run_dir/f'interrupted_steps_rev{revision:03d}.jsonl'
            while archive.exists():
                revision+=1; archive=run_dir/f'interrupted_steps_rev{revision:03d}.jsonl'
            shutil.copy2(run_dir/'steps.jsonl',archive)
            with archive.open(encoding='utf-8') as old,(run_dir/'steps.jsonl.tmp').open('w',encoding='utf-8') as new:
                for line in old:
                    try: item=json.loads(line)
                    except json.JSONDecodeError: break
                    if item['t']<=solver.t: new.write(line)
            (run_dir/'steps.jsonl.tmp').replace(run_dir/'steps.jsonl')
    writer=TrajectoryWriter(run_dir/'trajectory',identity,resume=resume)
    if not resume: writer.append(solver.t,solver.y)
    elif writer.last_time!=solver.t:
        raise ValueError('checkpoint and committed trajectory coverage differ')
    diagnostics=Diagnostics(system,config.tmax,solver.cfg,extra.get('diagnostics'))
    started=datetime.now(timezone.utc).isoformat(); begin=time.perf_counter()
    manifest_path=run_dir/'manifest.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8')) if resume else {
        'schema_version':'1.0','experiment':{'experiment_id':run_dir.name.split('__')[0],
        'name':run_dir.name,'status':'RUNNING','created_at':started,'completed_at':None},
        'model':{'role':'BASELINE_AND_PRIMARY' if config.route=='B' else 'CHALLENGER',
        'model_id':'B_EMPIRICAL_RADIAL' if config.route=='B' else 'C_AXISYMMETRIC_REFERENCE',
        'model_version':config.model_version},
        'purpose':{'question':config.question,'hypothesis':'Implement the approved forward model',
        'success_criteria':['finite accepted trajectory','specified source and algorithm','honest event/coverage state'],
        'failure_criteria':['invalid numerical state','unresolved Newton/step budget','incomplete required input']},
        'data':{'input_files':system.inputs.manifest,'dataset_version':config.input_version,'split_strategy':'OFFLINE_OBSERVATION_RECONSTRUCTION'},
        'configuration':{'config_file':'config.json','random_seed':config.seed,'fingerprint':config.fingerprint},
        'execution':{'execution_backend':config.execution_backend,'execution_purpose':config.execution_purpose,
        'production_eligible':config.production_eligible,'command':' '.join(sys.argv),'environment':'environment.json','device':'CPU'},
        'solver':{'name':solver.algorithm,'status':'RUNNING'},'source':dict(code,snapshot_directory='source_snapshot'),'identity':identity,
        'system_contract':system_identity(system,config),
        'factory_sha256':_factory_hash(Path(__file__).read_text(encoding='utf-8')),
        'outputs':{'metrics_file':'metrics.json','diagnostics_file':'diagnostics.json',
        'trajectory':'trajectory/index.json','checkpoint':'checkpoint.json','result_files':[],
        'log_file':'run.log'},'summary':{'notes':'Stage06 evidence; Stage07 NOT_RUN; not approved for submission'}}
    manifest['execution'].setdefault('attempts',[]).append({'started_at':started,'resume':resume})
    current_environment=environment()
    env_name=f'environment_attempt_{len(manifest["execution"]["attempts"]):03d}.json'
    atomic_json(run_dir/env_name,current_environment)
    manifest['execution']['attempts'][-1]['environment']=env_name
    atomic_json(run_dir/'config.json',cfgdict)
    if not resume: atomic_json(run_dir/'environment.json',current_environment)
    atomic_json(manifest_path,manifest)
    extrema=extra.get('extrema',{'T_min':float(np.min(solver.y[0::2])),
        'T_max':float(np.max(solver.y[0::2])),'C_min':float(np.min(solver.y[1::2])),
        'C_max':float(np.max(solver.y[1::2]))})
    checkpoint_list=extra.get('checkpoint_files',[])
    last_print=time.perf_counter()
    log=(run_dir/'run.log').open('a',encoding='utf-8')
    step_log=(run_dir/'steps.jsonl').open('a',encoding='utf-8')
    def persist():
        writer.flush()
        cpname=f'checkpoints/accepted_{solver.stats["accepted"]:09d}.json'
        is_new=cpname not in checkpoint_list
        if is_new: checkpoint_list.append(cpname)
        payload={'diagnostics':diagnostics.data,'extrema':extrema,'checkpoint_files':checkpoint_list,
                 'event_checked_until':None,'output_cursor':None,'trajectory_end':solver.t,
                 'input_segment':int(np.searchsorted(system.inputs.nodes(question=config.question,
                     geometry=config.geometry,tmax=config.tmax),solver.t,side='right'))}
        save_checkpoint(checkpoint,solver,identity,payload)
        if is_new: save_checkpoint(run_dir/cpname,solver,identity,payload)
        atomic_json(run_dir/'diagnostics.json',diagnostics.summary())
    def accept(t0,y0,t1,y1,info,residual):
        nonlocal last_print
        writer.append(t1,y1)
        if diagnostic: diagnostics.add_segment(t0,y0,t1,y1,info,residual)
        extrema['T_min']=min(extrema['T_min'],float(np.min(y1[0::2])))
        extrema['T_max']=max(extrema['T_max'],float(np.max(y1[0::2])))
        extrema['C_min']=min(extrema['C_min'],float(np.min(y1[1::2])))
        extrema['C_max']=max(extrema['C_max'],float(np.max(y1[1::2])))
        step_log.write(json.dumps({k:v for k,v in info.items() if k!='absolute_history'},allow_nan=False)+'\n')
        if solver.stats['accepted']%100==0 and process_memory_mb()>config.memory_mb:
            raise MemoryBudgetReached('MEMORY_BUDGET_REACHED after accepted segment')
        if solver.stats['accepted']%config.checkpoint_steps==0: persist()
        if time.perf_counter()-last_print>=15:
            msg=f't={t1:.6f}s accepted={solver.stats["accepted"]} C_min={extrema["C_min"]:.7g}'
            print(msg,flush=True); log.write(msg+'\n'); log.flush(); step_log.flush(); last_print=time.perf_counter()
    result=None
    if not resume: persist()
    try:
        endpoint=config.case_end_time or config.tmax
        result=solver.run(endpoint,callback=accept)
    except MemoryBudgetReached as exc:
        result={'status':'MEMORY_BUDGET_REACHED','t':solver.t,'failure':str(exc),'stats':solver.stats}
    except Exception as exc:
        result={'status':'EXECUTION_EXCEPTION','t':solver.t,'failure':repr(exc),'stats':solver.stats}
        log.write(traceback.format_exc())
    finally:
        persist(); log.close(); step_log.close()
    finished=datetime.now(timezone.utc).isoformat(); wall=time.perf_counter()-begin
    status=result['status']
    if status=='COMPLETED_INTERVAL' and config.test_case is None:
        if config.question==1 and solver.t==1800: status='Q1_WINDOW_COMPLETE'
        elif config.geometry=='moving' and config.radius_tail=='NONE' and solver.t==259200:
            status='INPUT_HORIZON_REACHED'
        elif solver.t==config.tmax: status='TIME_LIMIT_REACHED'
    result.update({'status':status,'wall_seconds':wall,'covered_seconds':solver.t,
                  'run_id':run_dir.name,'extrema':extrema,
                  'be_fraction':solver.stats['be_steps']/max(1,solver.stats['accepted']),
                  'be_time_fraction':solver.stats['be_time']/solver.t if solver.t else 0.,
                  'strict_report_status':'NOT_ASSESSED_NO_ERROR_EVIDENCE',
                  'stage07':'NOT_RUN','dtype':'float64'})
    result['process_memory_mb']=process_memory_mb()
    result['memory_budget_kind']='COOPERATIVE_EVERY_100_ACCEPTED_STEPS_NOT_OS_HARD_LIMIT'
    atomic_json(run_dir/'metrics.json',result)
    manifest['experiment']['status']=status; manifest['experiment']['completed_at']=finished
    manifest['execution']['attempts'][-1].update({'finished_at':finished,'runtime_seconds':wall,'status':status})
    manifest['execution']['runtime_seconds']=sum(a.get('runtime_seconds',0) for a in manifest['execution']['attempts'])
    manifest['execution']['exit_code']=(1 if status in ['EXECUTION_EXCEPTION','NUMERICAL_FAILURE','MEMORY_BUDGET_REACHED'] else
                                        2 if status in ['WALL_BUDGET_REACHED','STEP_BUDGET_REACHED'] else 0)
    manifest['solver']['status']=status; manifest['summary']['key_metrics']={k:result[k] for k in ['covered_seconds','be_fraction','be_time_fraction','strict_report_status']}
    atomic_json(manifest_path,manifest)
    return result


def inspect_run(run_dir,data_dir=None):
    path=Path(run_dir); config=RunConfig.from_json(path/'config.json')
    system=make_system(config,data_dir); trajectory=Trajectory(path/'trajectory',verify=True)
    manifest=json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    identity=trajectory.index['identity']
    if identity.get('dtype')!='float64': raise ValueError('trajectory dtype identity mismatch')
    if identity.get('config')!=config.fingerprint or identity.get('input')!=system.inputs.fingerprint:
        raise ValueError('run config/input identity mismatch')
    if manifest.get('identity')!=identity or identity.get('model_version')!=config.model_version:
        raise ValueError('run manifest/model identity mismatch')
    # Postprocessing code can evolve; the model/state interpretation must not.
    for name in ['physics','spatial','integrator','inputs','config','reconstruction','manufactured']:
        relative=f'src/drying/{name}.py'
        actual=hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()
        if manifest['source']['files'].get(relative)!=actual:
            raise ValueError(f'numerical source mismatch: {relative}; use the recorded source_snapshot')
    verify_system_identity(manifest,system,config,path)
    return system,trajectory,config
