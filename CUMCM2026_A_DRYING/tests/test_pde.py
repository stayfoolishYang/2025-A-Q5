"""TEST_ONLY real PDE advancement, analytic MMS and structural regression tests."""
from pathlib import Path
import numpy as np
import pytest
from drying.inputs import Inputs
from drying.spatial import Grid,DryingSystem
from drying.manufactured import ManufacturedCase
from drying.integrator import Integrator,Settings
from drying.diagnostics import Diagnostics
from drying.trajectory import TrajectoryWriter,Trajectory,save_checkpoint,load_checkpoint

DATA=Path(__file__).resolve().parents[1]/'data/raw'


def advance(system,end,hmax=2.):
    cfg=Settings(hmax=hmax,wall_seconds=90)
    solver=Integrator(system,cfg); diag=Diagnostics(system,end,cfg)
    history=[]
    def accepted(t0,y0,t1,y1,info,residual):
        diag.add_segment(t0,y0,t1,y1,info,residual)
        history.append((t1,y1.copy()))
    result=solver.run(end,callback=accepted)
    assert result['status']=='COMPLETED_INTERVAL',result
    return solver,diag,history


@pytest.mark.parametrize('route,moving',[('B',False),('B',True),('C',False),('C',True)])
def test_mms_actual_grid_refinement(route,moving):
    errors=[]
    for n in [4,8,16]:
        grid=Grid(n,n if route=='C' else 1,route)
        case=ManufacturedCase(moving=moving,route=route)
        system=DryingSystem(grid,Inputs(DATA),question=4 if moving else 23,
            geometry='moving' if moving else 'fixed',end_condition='C1' if route=='C' else 'C0',test_case=case)
        solver,diag,_=advance(system,100.)
        errors.append(np.max(abs((solver.y-case.averages(grid,100.)).reshape(-1,2)),axis=0))
        assert diag.data['layer_bound_violations']==0
        assert not diag.data['quadrature_unresolved']
    assert np.all(errors[2]<errors[1]) and np.all(errors[1]<errors[0]),errors


@pytest.mark.parametrize('moving',[False,True])
def test_c0_dynamic_degeneracy_and_checkpoint(tmp_path,moving):
    inputs=Inputs(DATA); geometry='moving' if moving else 'fixed'; q=4 if moving else 23
    b=DryingSystem(Grid(6),inputs,question=q,geometry=geometry)
    c=DryingSystem(Grid(6,4,'C'),inputs,question=q,geometry=geometry,end_condition='C0')
    bs,_,_=advance(b,30.); cs,_,_=advance(c,30.)
    expected=np.repeat(bs.y.reshape(6,1,2),4,axis=1)
    np.testing.assert_allclose(cs.y.reshape(6,4,2),expected,rtol=0,atol=1e-10)
    a=Integrator(b,Settings(hmax=2)); writer=TrajectoryWriter(tmp_path/'trajectory',{'test':'ONLY'})
    writer.append(a.t,a.y)
    a.run(15.,callback=lambda t0,y0,t1,y1,info,res:writer.append(t1,y1))
    writer.flush(); save_checkpoint(tmp_path/'checkpoint.json',a,{'test':'ONLY'})
    resumed=Integrator(b,Settings(hmax=2)); load_checkpoint(tmp_path/'checkpoint.json',resumed,{'test':'ONLY'})
    a.run(30.); resumed.run(30.)
    np.testing.assert_array_equal(a.y,resumed.y)
    trajectory=Trajectory(tmp_path/'trajectory',verify=True)
    assert trajectory.start_time==0 and trajectory.end_time==15
    with pytest.raises(ValueError): trajectory.at(15.1)


@pytest.mark.parametrize('moving',[False,True])
def test_closed_nonuniform_water_and_effective_heat(moving):
    system=DryingSystem(Grid(8),Inputs(DATA),question=4,geometry='moving' if moving else 'fixed',h=0,hm=0)
    y=system.initial(); y[1::2]=1.+.2*(1-system.grid.xi**2); y[0::2]+=1
    system.initial=lambda:y.copy()
    solver,diag,_=advance(system,30.)
    assert abs(np.dot(system.grid.dry_weights,solver.y[1::2]-y[1::2]))<1e-11
    np.testing.assert_allclose(solver.y[0::2],y[0::2],rtol=0,atol=1e-11)
    assert diag.summary()['water_max_relative']<1e-11
    assert diag.summary()['heat_max_relative']<1e-11


def test_c1_actual_axial_evolution_and_side_end_balance():
    system=DryingSystem(Grid(6,4,'C'),Inputs(DATA),question=23,end_condition='C1')
    solver,diag,_=advance(system,60.)
    cells=solver.y.reshape(6,4,2)
    assert np.max(abs(cells[:,0,1]-cells[:,-1,1]))>1e-5
    assert system.evaluate(60,solver.y).water_out>0
    assert diag.data['layer_bound_violations']==0
    assert diag.summary()['water_max_relative']<1e-5


def test_independent_heat_path_detects_deliberate_imbalance():
    system=DryingSystem(Grid(4),Inputs(DATA),h=0,hm=0)
    cfg=Settings(); diag=Diagnostics(system,1,cfg)
    y=system.initial(); wrong=y.copy(); wrong[0::2]+=1
    diag.add_segment(0,y,1,wrong)
    assert diag.summary()['heat_max_relative']>.9
