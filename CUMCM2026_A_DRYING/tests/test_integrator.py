"""TEST_ONLY: exercise the real custom time integrator on independent equations."""
from types import SimpleNamespace
import numpy as np
from scipy.sparse import csc_matrix
import pytest
from drying.integrator import Integrator, Settings, NumericalFailure


class Scalar:
    def __init__(self, rate=-1., nonlinear=False, nodes=()):
        self.rate=rate; self.nonlinear=nonlinear; self.nodes_=nodes
    def initial(self): return np.array([1.])
    def input_nodes(self, until): return [x for x in self.nodes_ if x<=until]
    def node_kind(self,t): return 'JUMP' if t==.5 else 'KINK'
    def evaluate(self,t,y,side='point',jacobian=True):
        rate=self.rate*(2 if t>.5 else 1) if self.nodes_ else self.rate
        if self.nonlinear:
            f=rate*y/(2+y); deriv=2*rate/(2+y)**2
        else: f=rate*y; deriv=np.full_like(y,rate)
        return SimpleNamespace(f=f,jac=csc_matrix(np.diag(deriv)) if jacobian else None)


def make(system,tol=1e-4,cls=Integrator):
    cfg=Settings(rtol=tol,atol_t=tol/100,hmax=.1,wall_seconds=30)
    return cls(system,cfg,scale=lambda y,old:tol/100+tol*np.maximum(abs(y),abs(old)),
               valid=lambda y,accepted,s:np.all(np.isfinite(y)))


@pytest.mark.parametrize('rate,end',[(-1.,1.),(-100.,.1)])
def test_actual_decay_refinement(rate,end):
    errors=[]
    for tol in [1e-3,1e-4,1e-5]:
        solver=make(Scalar(rate),tol)
        # Same small startup across tolerance levels: separate BE startup error
        # from BDF2 accumulation; for the stiff equation scale by known decay time.
        solver.cfg.h0=.001/max(1,abs(rate)); solver.h_next=solver.cfg.h0
        assert solver.run(end)['status']=='COMPLETED_INTERVAL'
        errors.append(abs(solver.y[0]-np.exp(rate*end)))
        assert solver.stats['bdf2_steps']>0 and solver.stats['be_steps']>0
    assert errors[2]<errors[1]<errors[0]


def test_nonlinear_mass_implicit_exact_relation():
    # (2+y)y'=-y, integral: 2 log(y)+y = 1-t.
    solver=make(Scalar(nonlinear=True),1e-5)
    assert solver.run(1.)['status']=='COMPLETED_INTERVAL'
    assert abs(2*np.log(solver.y[0])+solver.y[0])<1e-4


def test_reintegration_endpoint_does_not_leave_ulp_tail():
    solver=make(Scalar(),1e-4)
    solver.cfg.hmax=.00125; solver.cfg.h0=.00125; solver.h_next=.00125
    endpoint=.35010083414859404
    result=solver.run(endpoint)
    assert result['status']=='COMPLETED_INTERVAL' and solver.t==endpoint
    assert solver.stats['rejected']==0
    assert abs(solver.y[0]-np.exp(-endpoint))<1e-5


def test_restore_is_same_accepted_history():
    system=Scalar(); a=make(system); a.run(.4)
    snapshot=a.snapshot(); b=make(system); b.restore(snapshot)
    saved_count=snapshot['stats']['accepted']
    a.run(1.)
    assert snapshot['stats']['accepted']==saved_count
    assert b.stats['accepted']==saved_count
    b.run(1.)
    np.testing.assert_array_equal(a.y,b.y)
    assert a.stats['accepted']==b.stats['accepted']
    bad=dict(snapshot,algorithm='OTHER')
    with pytest.raises(ValueError): b.restore(bad)


def test_input_nodes_restart_output_does_not_change_history():
    solver=make(Scalar(nodes=(.25,.5)),1e-5)
    states=[]
    solver.run(1.,callback=lambda a,b,c,d,e,f: states.append((a,c,e['method'])))
    assert any(a==.25 and method=='KINK_RESTART_BE' for a,b,method in states)
    assert any(a==.5 and method=='JUMP_RESTART_BE' for a,b,method in states)
    assert abs(solver.y[0]-np.exp(-1.5))<1e-4


def test_forced_newton_rejections_fallback_and_recovery():
    class InjectFailure(Integrator):
        triggered=0
        def _attempt(self,h,method,side):
            if method=='BDF2' and self.triggered<2:
                self.triggered+=1
                raise NumericalFailure('TEST_ONLY_FORCED_NEWTON_FAILURE')
            return super()._attempt(h,method,side)
    solver=make(Scalar(),cls=InjectFailure); history=[]
    solver.run(.5,callback=lambda a,b,c,d,e,f: history.append((a,c,e['method'])))
    assert solver.stats['reject_reasons']['TEST_ONLY_FORCED_NEWTON_FAILURE']==2
    assert any(method=='FALLBACK_BE' for a,b,method in history)
    assert any(method=='BDF2' for a,b,method in history)
    assert all(history[i][1]==history[i+1][0] for i in range(len(history)-1))
    assert abs(solver.y[0]-np.exp(-.5))<1e-3


def test_retry_limit_never_commits_failed_state():
    class AlwaysFail(Integrator):
        def _attempt(self,*args): raise NumericalFailure('TEST_ONLY_ALWAYS_FAIL')
    solver=make(Scalar(),cls=AlwaysFail)
    result=solver.run(1.)
    assert result['status']=='NUMERICAL_FAILURE' and solver.t==0.
    assert solver.y[0]==1. and solver.y_prev is None
    assert solver.stats['rejected']==12


def test_stiff_start_exhausts_budget_without_false_success():
    solver=make(Scalar(-100.),1e-5)
    result=solver.run(.1)
    assert result['status']=='NUMERICAL_FAILURE' and solver.t==0
    assert solver.stats['reject_reasons']['TIME_ERROR']==12
