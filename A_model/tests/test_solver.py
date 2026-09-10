import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from scipy.linalg import solve_banded
from scipy.optimize import brentq
from scipy.special import j0, j1
from scipy.integrate import quad
from solver.fvm_cpu import assemble, thomas, solve
from physics.material import moisture_faces

def main():
    n = 41
    x = np.linspace(0, 1, n)
    args = (np.full(n, .36), np.full(n, 820*2600.), np.full(n, 28.), np.full(n, 28.), .019, .02, .02, 1., 1., 1., 0., 25., 50., True)
    l, d, u, b, _ = assemble(*args)
    band = np.zeros((3,n)); band[0,1:] = u; band[1] = d; band[2,:-1] = l
    tri_error = float(np.max(np.abs(thomas(l,d,u,b)-solve_banded((1,1), band,b))))
    assert tri_error < 1e-10
    # Geometric conservation, contraction AND expansion, BE AND BDF2.
    constant_error = 0.
    for R in (.019, .021):
        for a, beta, gamma in ((1.,1.,0.),(1.5,2.,.5)):
            l,d,u,b,_ = assemble(np.ones(n), np.ones(n), np.full(n,2.), np.full(n,2.), R,.02,.02,1.,a,beta,gamma,0.,2.,True)
            constant_error = max(constant_error, float(np.max(np.abs(thomas(l,d,u,b)-2))))
    assert constant_error < 1e-7
    # Single exact Robin eigenmode: u=J0(lambda*r/R)*exp(-alpha*lambda²*t/R²).
    Bi, R, diffusivity = 25*.02/.36, .02, .36/(820*2600)
    lam = brentq(lambda z:z*j1(z)-Bi*j0(z), .01, 2.4048)
    errors = []
    for n in (21,41,81):
        x = np.linspace(0,1,n); old = j0(lam*x); dt=.05
        for _ in range(2000):
            l,d,u,b,_ = assemble(np.full(n,.36),np.full(n,820*2600.),old,old,R,R,R,dt,1.,1.,0.,25.,0.,True)
            old = thomas(l,d,u,b)
        exact = j0(lam*x)*np.exp(-diffusivity*lam**2*100/R**2)
        errors.append(float(np.max(np.abs(old-exact))))
    assert errors[2] < errors[1] < errors[0] and errors[2] < 5e-5
    out, meta = solve(model=1,n=21,dt=1,end=1800,interval=1,event=False)
    assert np.all(out[:,2:23] >= 28-1e-7) and np.all(out[:,23:] > 0)
    assert out[-1,22] > out[-1,2] and out[-1,-1] < out[-1,23]
    assert meta['max_cumulative_balance_relative'] < 1e-6
    # Independent adaptive quadrature validates nonlinear face transmissibility.
    quadrature_error = 0.
    for c1,c2 in ((.05,.1),(.1,.4),(2.,2.55)):
        T,C=np.array([45.,50.]),np.array([c1,c2])
        actual=moisture_faces(T,C,2,0,np.ones(4))[0]
        exact=quad(lambda s:2.4e-3*np.exp(-.45/(c1*(1-s)+c2*s)-3850/(45*(1-s)+50*s+273.15)),0,1,epsabs=1e-22)[0]
        quadrature_error=max(quadrature_error,abs(actual-exact)/exact)
    assert quadrature_error<1e-6
    result = dict(thomas_scipy_max_error=tri_error, geometric_constant_error=constant_error,
                  cylindrical_eigenmode_errors=errors, nonlinear_face_quadrature_error=quadrature_error, q1=meta)
    dest = Path(__file__).resolve().parents[1]/'results'; dest.mkdir(exist_ok=True)
    (dest/'tests.json').write_text(json.dumps(result, indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__ == '__main__': main()
