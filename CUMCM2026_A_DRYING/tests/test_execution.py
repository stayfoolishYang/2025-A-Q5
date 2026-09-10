"""Integrated execution contracts distinct from PDE accuracy tests."""
import json
from pathlib import Path
import pytest
from drying.config import RunConfig
from drying.execution import run_config,inspect_run
from drying.resources import MemoryBudgetReached,process_memory_mb
from drying.reporting import summarize_run,pack_return
from drying.cli import main


def test_real_run_restart_package(tmp_path):
    config=RunConfig(question=1,nr=4,tmax=1,wall_seconds=30,checkpoint_steps=10)
    path=tmp_path/'EXP900_contract__test001'
    first=run_config(config,path)
    assert first['t']==1 and first['failure'] is None
    system,trajectory,_=inspect_run(path)
    before=trajectory.at(1)
    checkpoint=json.loads((path/'checkpoint.json').read_text())
    assert checkpoint['extra']['checkpoint_files']
    second=run_config(config,path,resume=True)
    assert second['t']==1
    _,again,_=inspect_run(path)
    assert (before==again.at(1)).all()
    summary=summarize_run(path)
    assert summary['coverage_end']==1 and summary['event']['status']=='NO_EVENT'
    bundle=pack_return(tmp_path,tmp_path/'return.zip')
    assert bundle['files']>0
    with pytest.raises(FileExistsError): run_config(config,path)


def test_memory_budget_and_cli_failure(tmp_path):
    assert process_memory_mb()>0
    with pytest.raises(MemoryBudgetReached):
        run_config(RunConfig(memory_mb=1),tmp_path/'too_small')
    assert not (tmp_path/'too_small').exists()
    assert main(['run','--config',str(tmp_path/'missing.json'),'--out',str(tmp_path/'bad')])==1


def test_pipeline_preflight_failure_blocks_runs(tmp_path,monkeypatch):
    import drying.preflight
    monkeypatch.setattr(drying.preflight,'run_preflight',lambda **kw:{'status':'FAIL'})
    assert main(['pipeline','--plan',str(tmp_path/'absent_plan.json')])==1


def test_actual_crash_ahead_recovery_and_tampered_config(tmp_path):
    import shutil
    from drying.trajectory import Trajectory
    config=RunConfig(question=1,nr=4,tmax=1,wall_seconds=30,checkpoint_steps=10)
    path=tmp_path/'EXP901_crash__test001'
    run_config(config,path)
    original=Trajectory(path/'trajectory',verify=True).at(1)
    chunks={p.name:p.read_bytes() for p in (path/'trajectory').glob('*.npz')}
    shutil.copy2(path/'checkpoints/accepted_000000000.json',path/'checkpoint.json')
    result=run_config(config,path,resume=True)
    assert result['t']==1
    assert (Trajectory(path/'trajectory',verify=True).at(1)==original).all()
    assert list((path/'trajectory').glob('recovery_index_rev*.json'))
    assert all((path/'trajectory'/name).read_bytes()==content for name,content in chunks.items())
    cfg=json.loads((path/'config.json').read_text()); cfg['scenario']='S1'
    (path/'config.json').write_text(json.dumps(cfg))
    with pytest.raises(ValueError,match='identity'): inspect_run(path)


def test_partial_chunk_recovery_preserves_orphans(tmp_path):
    import numpy as np
    from drying.trajectory import TrajectoryWriter,Trajectory,recover_trajectory
    writer=TrajectoryWriter(tmp_path,{'config':'test'},chunk_size=4)
    for t in range(5): writer.append(t,np.array([t],dtype=float))
    writer.flush()
    orphan=(tmp_path/'chunk_000001.npz').read_bytes()
    assert recover_trajectory(tmp_path,2)
    writer=TrajectoryWriter(tmp_path,{'config':'test'},resume=True)
    writer.append(3,[3]); writer.append(4,[4]); writer.flush()
    assert Trajectory(tmp_path,verify=True).at(4)[0]==4
    assert (tmp_path/'chunk_000001.npz').read_bytes()==orphan
