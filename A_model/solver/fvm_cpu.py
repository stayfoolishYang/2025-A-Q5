"""Nodal cylindrical FVM, conservative ALE, implicit Picard and BE/BDF2."""
import numpy as np
from numba import njit
from physics.material import properties, moisture_faces
from physics.boundary import Boundary

@njit(cache=True)
def geometry(n):
    faces = np.empty(n+1)
    faces[0], faces[-1] = 0., 1.
    for i in range(1, n):
        faces[i] = (i-0.5)/(n-1)
    return faces, 0.5*(faces[1:]**2-faces[:-1]**2)

@njit(cache=True)
def assemble(p, capacity, old, prev, R, Ro, Rp, dt, alpha, beta, gamma, h, ambient, ale):
    n = len(old)
    faces, v = geometry(n)
    # Material-coordinate comparison has no grid-advection term.
    if not ale:
        Ro, Rp = R, R
    g = (alpha*R*R-beta*Ro*Ro+gamma*Rp*Rp)/(2*dt)
    if abs(g) < 1e-20:
        g = 0.
    diag = capacity * alpha * R*R * v / dt
    rhs = capacity * v * (beta*Ro*Ro*old-gamma*Rp*Rp*prev) / dt
    lower, upper = np.zeros(n-1), np.zeros(n-1)
    for j in range(n-1):
        pf = p[j] if len(p) == n-1 else 2*p[j]*p[j+1]/(p[j]+p[j+1])
        G = faces[j+1]*(n-1)*pf
        diag[j] += G
        diag[j+1] += G
        upper[j] -= G
        lower[j] -= G
        # Conservative grid flux; upwind for standard velocity -Rdot*xi/R.
        q = g * faces[j+1]**2
        if abs(q)*max(capacity[j],capacity[j+1]) <= 1.8*G:
            # Centered grid flux is second order when the face Peclet number
            # keeps both off-diagonal coefficients nonpositive.
            diag[j] -= .5*capacity[j]*q
            upper[j] -= .5*capacity[j]*q
            lower[j] += .5*capacity[j+1]*q
            diag[j+1] += .5*capacity[j+1]*q
        elif q <= 0:
            diag[j] -= capacity[j]*q
            lower[j] += capacity[j+1]*q
        else:
            upper[j] -= capacity[j]*q
            diag[j+1] += capacity[j+1]*q
    diag[-1] += R*h - capacity[-1]*g
    rhs[-1] += R*h*ambient
    return lower, diag, upper, rhs, g

@njit(cache=True)
def thomas(lower, diag, upper, rhs):
    b, x = diag.copy(), rhs.copy()
    for i in range(1, len(b)):
        z = lower[i-1]/b[i-1]
        b[i] -= z*upper[i-1]
        x[i] -= z*x[i-1]
    x[-1] /= b[-1]
    for i in range(len(b)-2, -1, -1):
        x[i] = (x[i]-upper[i]*x[i+1])/b[i]
    return x

@njit(cache=True)
def step(Told, Cold, Tprev, Cprev, R, Ro, Rp, ambient, dt, model, mode, scales, omega, alpha, beta, gamma, ale):
    T, C = Told.copy(), Cold.copy()
    for iteration in range(120):
        cap, k, D = properties(T, C, model, mode, scales)
        D = moisture_faces(T, C, model, mode, scales)
        l, d, u, b, _ = assemble(k, cap, Told, Tprev, R, Ro, Rp, dt, alpha, beta, gamma, 25*scales[2], ambient[0], ale)
        Tnew = thomas(l, d, u, b)
        l, d, u, b, g = assemble(D, np.ones(len(C)), Cold, Cprev, R, Ro, Rp, dt, alpha, beta, gamma, 8e-7*scales[1], ambient[1], ale)
        Cnew = thomas(l, d, u, b)
        eT, eC = np.max(np.abs(Tnew-T)), np.max(np.abs(Cnew-C))
        T = omega*Tnew+(1-omega)*T
        C = omega*Cnew+(1-omega)*C
        if eT < 1e-7 and eC < 1e-9:
            if not np.all(np.isfinite(T)) or not np.all(np.isfinite(C)) or np.min(C) <= 0:
                raise ValueError('Invalid solution')
            return T, C, iteration+1, g
    raise RuntimeError('Picard did not converge')

@njit(cache=True)
def integrate(n, dt, ambient, radius, model, mode, scales, omega, bdf2, ale, stride, event):
    T, C = np.full(n, 28.), np.full(n, 2.55)
    Tp, Cp = T.copy(), C.copy()
    nsteps = len(radius)-1
    output = np.empty((nsteps//stride+2, 2*n+2))
    output[0, 0], output[0, 1] = 0., radius[0]
    output[0, 2:2+n], output[0, 2+n:] = T, C
    count, maxit, residual, balance = 1, 0, 0., 0.
    _, v = geometry(n)
    integral0 = np.sum(v*C)*radius[0]**2
    loss, lossp = 0., 0.
    # The no-ALE equation conserves the reference/material integral, not R²*C.
    if not ale:
        integral0 = np.sum(v*C)
    for j in range(1, nsteps+1):
        alpha, beta, gamma = (1.5, 2., 0.5) if bdf2 and j > 1 else (1., 1., 0.)
        R, Ro, Rp = radius[j], radius[j-1], radius[max(0,j-2)]
        Tn, Cn, it, g = step(T, C, Tp, Cp, R, Ro, Rp, ambient[j], dt, model, mode, scales, omega, alpha, beta, gamma, ale)
        maxit = max(maxit, it)
        V, Vo, Vp = v*R*R, v*Ro*Ro, v*Rp*Rp
        if not ale:
            Vo, Vp = V, V
        flux = -R*8e-7*scales[1]*(Cn[-1]-ambient[j,1]) + g*Cn[-1]
        err = np.sum(alpha*V*Cn-beta*Vo*C+gamma*Vp*Cp)-dt*flux
        residual = max(residual, abs(err)/(integral0 if ale else integral0*R*R))
        audited_flux = flux if ale else flux/(R*R)
        lossn = (beta*loss-gamma*lossp+dt*audited_flux)/alpha
        lossp, loss = loss, lossn
        audited_integral = np.sum(V*Cn) if ale else np.sum(v*Cn)
        balance = max(balance, abs(audited_integral-integral0-loss)/integral0)
        if event and np.max(Cn) <= 0.15:
            # Return left bracket states so Python can evaluate exact interpolants during bisection.
            return output[:count], j, T, C, Tn, Cn, maxit, residual, balance
        Tp, Cp, T, C = T, C, Tn, Cn
        if j % stride == 0:
            output[count, 0], output[count, 1] = j*dt, R
            output[count, 2:2+n], output[count, 2+n:] = T, C
            count += 1
    return output[:count], nsteps, T, C, T, C, maxit, residual, balance

def solve(model=2, moving=False, n=81, dt=1., end=432000., interval=60., event=True,
          scheme='be', interpolation='pchip', tail='last', mode=0, scales=None, omega=1., ale=True):
    if n < 3 or dt <= 0 or abs(interval/dt-round(interval/dt)) > 1e-9:
        raise ValueError('Invalid grid or sampling interval')
    scales = np.ones(4) if scales is None else np.asarray(scales, dtype=float)
    if scales.shape != (4,) or np.min(scales) <= 0:
        raise ValueError('Expected four positive scales: D, hm, hT, k')
    boundary = Boundary(interpolation, tail)
    times = np.arange(int(end/dt)+1)*dt
    ambient = boundary.ambient(times)
    radii = boundary.radius(times) if moving else np.full(len(times), .02)
    out, j, Tleft, Cleft, T, C, maxit, residual, balance = integrate(n, dt, ambient, radii, model, mode, scales, omega, scheme == 'bdf2', ale, int(round(interval/dt)), event)
    event_s = None
    bracket = None
    if event:
        if np.max(C) > .15:
            raise RuntimeError(f'No threshold by {end/3600:g} h')
        left, lo, hi = (j-1)*dt, 0., dt
        while hi-lo > .1:
            mid = (lo+hi)/2
            R = float(boundary.radius(left+mid)) if moving else .02
            Tmid, Cmid, _, _ = step(Tleft, Cleft, Tleft, Cleft, R, radii[j-1], radii[j-1], boundary.ambient(left+mid), mid, model, mode, scales, omega, 1., 1., 0., ale)
            if np.max(Cmid) <= .15:
                hi = mid
            else:
                lo = mid
        event_s, bracket = left+hi, [left+lo, left+hi]
        R = float(boundary.radius(event_s)) if moving else .02
        T, C, _, _ = step(Tleft, Cleft, Tleft, Cleft, R, radii[j-1], radii[j-1], boundary.ambient(event_s), hi, model, mode, scales, omega, 1., 1., 0., ale)
        out = np.vstack((out, np.r_[event_s, R, T, C]))
    meta = dict(model=model, moving=moving, n=n, dt=dt, scheme=scheme, interpolation=interpolation, tail=tail, mode=mode,
                scales=scales.tolist(), omega=omega, ale=ale, event_s=event_s, event_h=None if event_s is None else event_s/3600,
                event_bracket_s=bracket, max_picard_iterations=int(maxit), max_step_balance_relative=float(residual),
                max_cumulative_balance_relative=float(balance),
                balance_quantity='geometric_integral_with_swept_boundary' if ale else 'material_integral_uniform_dry_density',
                balance_includes_event_bisection=False,
                final_max_C=float(np.max(C)), radius_extrapolated=bool(event_s and moving and event_s>259200))
    return out, meta
