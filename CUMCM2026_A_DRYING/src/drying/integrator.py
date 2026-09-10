"""A26-04-v2 section 6.8: custom variable-step BDF2 / full BE.

CUDA sparse linear solves are required by production RunConfig. SciPy solves
remain an explicitly selected CPU reference for comparison tests only.
No library time integrator is used.
All state/history mutations occur after acceptance; auxiliary BE solves are private.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, asdict
import time

import numpy as np
from scipy.sparse import eye, diags, csc_matrix
from scipy.sparse.linalg import splu
from scipy.linalg import solve_banded
from .cuda_backend import CudaLinearSolver, CudaBackendError


class NumericalFailure(RuntimeError):
    pass


@dataclass
class Settings:
    rtol: float = 1e-6
    atol_t: float = 1e-6
    atol_c: float = 1e-9
    h0: float = 0.1
    hmax: float = 60.0
    newton_tol: float = 1e-3
    linear_tol: float = 1e-8
    max_steps: int = 2000000
    wall_seconds: float = 1800.0
    linear_backend: str = "CPU_REFERENCE"
    cuda_device: int = 0
    gpu_memory_mb: int = 2048

    @classmethod
    def from_config(cls, config):
        return cls(**{k: getattr(config, k) for k in cls.__dataclass_fields__})


def coefficients(ratio):
    if not (0 < ratio <= 1.5 * (1 + 8*np.finfo(float).eps)):
        raise ValueError("invalid BDF2 step ratio")
    return np.array([(1+2*ratio)/(1+ratio), -(1+ratio), ratio**2/(1+ratio)])


def physical_scale(y, old, cfg):
    scale = np.empty_like(y)
    scale[0::2] = cfg.atol_t + cfg.rtol*np.maximum(abs(y[0::2]-301.15), abs(old[0::2]-301.15))
    scale[1::2] = cfg.atol_c + cfg.rtol*np.maximum(abs(y[1::2]), abs(old[1::2]))
    return scale


def physical_valid(y, accepted=False, scale=None, formal=True):
    if not np.all(np.isfinite(y)) or np.any(y[0::2] <= 0) or np.any(y[1::2] < 0):
        return False
    if accepted and formal:
        if np.any(y[1::2] <= 0):
            return False
        allowance = 10*scale
        if np.any(y[0::2] < 301.15-allowance[0::2]) or np.any(y[0::2] > 323.396+allowance[0::2]):
            return False
        if np.any(y[1::2] < .01963-allowance[1::2]) or np.any(y[1::2] > 2.55+allowance[1::2]):
            return False
    return True


class Integrator:
    algorithm = "CUSTOM_VSBDF2_BE"

    def __init__(self, system, settings=None, *, scale=None, valid=None):
        self.system = system
        self.cfg = settings or Settings()
        if self.cfg.linear_backend not in ('CUDA','CPU_REFERENCE'):
            raise ValueError('unknown linear backend')
        self.cuda_solver=(CudaLinearSolver(self.cfg.cuda_device,self.cfg.gpu_memory_mb)
                          if self.cfg.linear_backend=='CUDA' else None)
        self.scale = scale or (lambda y, old: physical_scale(y, old, self.cfg))
        formal = getattr(system, 'test_case', None) is None
        self.valid = valid or (lambda y, accepted, s: physical_valid(y, accepted, s, formal))
        self.t = 0.0
        self.y = np.asarray(system.initial(), dtype=np.float64).copy()
        self.t_prev = None
        self.y_prev = None
        self.h_prev = None
        self.h_next = self.cfg.h0
        self.needs_be = True
        self.be_reason = 'STARTUP_BE'
        self.stats = {'accepted': 0, 'rejected': 0, 'newton_iterations': 0,
                      'rhs_evaluations': 0, 'jacobian_evaluations': 0,
                      'linear_seconds': 0., 'newton_seconds': 0.,
                      'be_steps': 0, 'be_time': 0., 'bdf2_steps': 0,
                      'consecutive_fallback': 0, 'longest_fallback': 0,
                      'min_h': None, 'max_h': 0., 'max_E': 0.,
                      'max_newton_residual': 0., 'max_linear_residual': 0.,
                      'reason_counts': {}, 'reject_reasons': {}}
        self.last_step = None
        self.failure = None

    def linear_backend_metadata(self):
        if self.cuda_solver is not None:
            return self.cuda_solver.metadata
        return {'backend':'CPU_REFERENCE','gpu_used':False,'dtype':'float64',
                'purpose':'EXPLICIT_NONPRODUCTION_REFERENCE_NOT_FALLBACK'}

    def snapshot(self):
        return {'t': self.t, 'y': self.y.tolist(), 't_prev': self.t_prev,
                'y_prev': None if self.y_prev is None else self.y_prev.tolist(),
                'h_prev': self.h_prev, 'h_next': self.h_next,
                'needs_be': self.needs_be, 'be_reason': self.be_reason,
                'stats': deepcopy(self.stats), 'last_step': deepcopy(self.last_step),
                'settings': asdict(self.cfg), 'algorithm': self.algorithm,
                'linear_backend_snapshot':self.linear_backend_metadata()}

    def restore(self, state):
        if state['algorithm'] != self.algorithm or state['settings'] != asdict(self.cfg):
            raise ValueError('checkpoint algorithm/settings mismatch')
        self.t = float(state['t']); self.y = np.array(state['y'], dtype=np.float64)
        self.t_prev = state['t_prev']
        self.y_prev = None if state['y_prev'] is None else np.array(state['y_prev'], dtype=np.float64)
        self.h_prev = state['h_prev']; self.h_next = state['h_next']
        self.needs_be = bool(state['needs_be']); self.be_reason = state['be_reason']
        self.stats = deepcopy(state['stats']); self.last_step = deepcopy(state['last_step'])
        if self.y_prev is not None and (self.h_prev <= 0 or self.t_prev >= self.t):
            raise ValueError('invalid checkpoint accepted history')

    def _eval(self, t, y, side, jac):
        ev = self.system.evaluate(t, y, side=side, jacobian=jac)
        self.stats['rhs_evaluations'] += 1
        self.stats['jacobian_evaluations'] += int(jac)
        if not np.all(np.isfinite(ev.f)):
            raise NumericalFailure('NONFINITE_RHS')
        return ev

    def _linear(self, matrix, residual):
        started = time.perf_counter()
        if self.cuda_solver is not None:
            try:
                answer, backward=self.cuda_solver.solve(matrix,residual)
            finally:
                self.stats['linear_seconds'] += time.perf_counter()-started
            if not np.all(np.isfinite(answer)) or backward > self.cfg.linear_tol:
                raise NumericalFailure('LINEAR_RESIDUAL')
            return answer, backward
        # B's 2x2 block-tridiagonal matrix has scalar bandwidth three.
        grid = getattr(self.system, 'grid', None)
        if grid is not None and grid.route == 'B':
            n = matrix.shape[0]; band = np.zeros((7, n))
            coo = matrix.tocoo()
            offsets = coo.row-coo.col
            if np.any(abs(offsets) > 3):
                raise NumericalFailure('BANDWIDTH_CONTRACT')
            band[3+offsets, coo.col] = coo.data
            answer = solve_banded((3, 3), band, -residual, check_finite=False)
        else:
            answer = splu(matrix.tocsc()).solve(-residual)
        norm_a = float(np.max(np.asarray(abs(matrix).sum(axis=1)).ravel()))
        denom = norm_a*np.max(abs(answer))+np.max(abs(residual))
        numer = np.max(abs(matrix@answer+residual))
        backward = float(numer/denom) if denom else (0. if numer == 0 else float('inf'))
        self.stats['linear_seconds'] += time.perf_counter()-started
        if not np.all(np.isfinite(answer)) or backward > self.cfg.linear_tol:
            raise NumericalFailure('LINEAR_RESIDUAL')
        return answer, backward

    def _newton(self, t, h, alpha, old, older, guess, side):
        started = time.perf_counter()
        try:
            return self._newton_impl(t, h, alpha, old, older, guess, side)
        finally:
            self.stats['newton_seconds'] += time.perf_counter()-started

    def _newton_impl(self, t, h, alpha, old, older, guess, side):
        y = guess.copy()
        if not self.valid(y, False, None): y = old.copy()
        # Sum(alpha)=0: differencing around old removes the absolute 300 K baseline.
        history = alpha[2]*(older-old) if alpha[2] != 0 else np.zeros_like(old)
        max_lin = 0.
        for iteration in range(12):
            self.stats['newton_iterations'] += 1
            ev = self._eval(t, y, side, True)
            residual = alpha[0]*(y-old)+history-h*ev.f
            sigma = self.scale(y, old)
            if np.any(sigma <= 0) or not np.all(np.isfinite(sigma)):
                raise NumericalFailure('INVALID_SCALE')
            jac = eye(y.size, format='csc')*alpha[0]-h*csc_matrix(ev.jac)
            scaled = diags(1/sigma)@jac@diags(sigma)
            d, lin = self._linear(scaled.tocsc(), residual/sigma)
            max_lin = max(max_lin, lin)
            correction = sigma*d
            norm_r = float(np.max(abs(residual/(alpha[0]*sigma))))
            norm_d = float(np.max(abs(d)))
            if norm_r <= self.cfg.newton_tol and norm_d <= self.cfg.newton_tol:
                return y, {'residual': norm_r, 'correction': norm_d,
                           'linear': max_lin, 'iterations': iteration+1,
                           'raw_residual': residual}
            old_norm = np.max(abs(residual/sigma))
            damping = 1.
            for _ in range(13):  # lambda=1 followed by at most twelve halvings
                trial = y+damping*correction
                if self.valid(trial, False, None):
                    try:
                        trial_ev = self._eval(t, trial, side, False)
                        trial_r = alpha[0]*(trial-old)+history-h*trial_ev.f
                        if np.max(abs(trial_r/sigma)) <= (1-1e-4*damping)*old_norm:
                            y = trial
                            break
                    except (ValueError, FloatingPointError, NumericalFailure):
                        pass
                damping *= .5
            else:
                raise NumericalFailure('NEWTON_LINE_SEARCH')
        raise NumericalFailure('NEWTON_MAX_ITERATIONS')

    def _attempt(self, h, method, side):
        old = self.y; end = self.t+h
        be_alpha = np.array([1., -1., 0.])
        if method == 'BDF2':
            ratio = h/self.h_prev
            alpha = coefficients(ratio)
            candidate, info = self._newton(end, h, alpha, old, self.y_prev,
                                           old+ratio*(old-self.y_prev), side)
            auxiliary, _ = self._newton(end, h, be_alpha, old, None, old, side)
            E = float(np.max(abs(candidate-auxiliary)/self.scale(candidate, old)))
        else:
            alpha = be_alpha
            candidate, info = self._newton(end, h, be_alpha, old, None, old, side)
            half, _ = self._newton(self.t+h/2, h/2, be_alpha, old, None, old, 'point')
            two, _ = self._newton(end, h/2, be_alpha, half, None, half, side)
            E = float(2*np.max(abs(two-candidate)/self.scale(candidate, old)))
        if not np.isfinite(E) or E > 1:
            raise NumericalFailure('TIME_ERROR')
        if not self.valid(candidate, True, self.scale(candidate, old)):
            raise NumericalFailure('ACCEPTED_STATE_INVALID')
        info['alpha'] = alpha.tolist(); info['E'] = E
        info['absolute_history'] = abs(alpha[0]*candidate)+abs(alpha[1]*old)
        if alpha[2] != 0:
            info['absolute_history'] += abs(alpha[2]*self.y_prev)
        return candidate, info

    def run(self, until, *, callback=None, stop=None, forced_nodes=(), wall_seconds=None):
        """Advance to a finite endpoint. Callback sees only accepted segments.

        Returning True from stop(t,y,info) stops after the accepted state is committed.
        A budget exit is resumable; mathematical failure is recorded distinctly.
        """
        if not np.isfinite(until) or until < self.t:
            raise ValueError('invalid integration endpoint')
        started = time.perf_counter(); before_steps = self.stats['accepted']
        budget = self.cfg.wall_seconds if wall_seconds is None else wall_seconds
        if hasattr(self.system, 'input_nodes'):
            inputs = list(self.system.input_nodes(until))
        elif getattr(self.system, 'test_case', None) is not None:
            inputs = []
        else:
            inputs = list(self.system.inputs.nodes(question=self.system.question,
                          geometry=self.system.geometry, tmax=until))
        input_set = set(map(float, inputs))
        nodes = sorted(set([float(x) for x in inputs]+[float(x) for x in forced_nodes]+[float(until)]))
        nodes = [x for x in nodes if self.t < x <= until]
        node_idx = 0
        status = 'COMPLETED_INTERVAL'
        while self.t < until:
            if time.perf_counter()-started >= budget:
                status = 'WALL_BUDGET_REACHED'; break
            if self.stats['accepted']-before_steps >= self.cfg.max_steps:
                status = 'STEP_BUDGET_REACHED'; break
            while node_idx < len(nodes) and nodes[node_idx] <= self.t: node_idx += 1
            endpoint = nodes[node_idx]
            h = min(self.h_next, self.cfg.hmax, endpoint-self.t)
            if not self.needs_be: h = min(h, 1.5*self.h_prev)
            # Integrate the final ordinary step to the exact requested endpoint
            # when subtraction/addition would otherwise leave an ulp-sized tail.
            # This changes the Newton step itself, never merely its time label.
            tail=endpoint-(self.t+h)
            if 0 < tail <= 32*abs(np.spacing(endpoint)):
                h=endpoint-self.t
            method = self.be_reason if self.needs_be else 'BDF2'
            trial_method = method
            accepted = False
            for retry in range(12):
                if h < max(1e-9, 32*abs(np.spacing(self.t))):
                    self.failure = 'STEP_UNDERFLOW'; break
                # Closed left segment uses node point/left data. Restart acts on right.
                side = 'left' if self.t+h == endpoint and endpoint in input_set else 'point'
                try:
                    candidate, info = self._attempt(h, trial_method, side)
                    accepted = True; break
                except CudaBackendError:
                    # Device/runtime/OOM failures cannot be fixed by a smaller
                    # time step and must never trigger CPU fallback.
                    raise
                except (NumericalFailure, ValueError, FloatingPointError, RuntimeError) as error:
                    reason = str(error)
                    self.stats['rejected'] += 1
                    reasons = self.stats['reject_reasons']; reasons[reason] = reasons.get(reason, 0)+1
                    h *= .5
                    if method == 'BDF2' and retry >= 1: trial_method = 'FALLBACK_BE'
            if not accepted:
                self.failure = self.failure or 'RETRY_LIMIT'
                status = 'NUMERICAL_FAILURE'; break
            old_t = self.t; old_y = self.y.copy()
            previous_h = self.h_prev
            self.t_prev = old_t; self.y_prev = old_y; self.h_prev = h
            self.t = float(old_t+h); self.y = candidate
            self.needs_be = False
            self.h_next = h*(1.5 if info['E'] == 0 else np.clip(.9*info['E']**(-.5), .2, 1.5))
            self.stats['accepted'] += 1
            counts = self.stats['reason_counts']; counts[trial_method] = counts.get(trial_method, 0)+1
            is_be = trial_method != 'BDF2'
            self.stats['be_steps'] += int(is_be); self.stats['bdf2_steps'] += int(not is_be)
            self.stats['be_time'] += h*is_be
            consecutive = self.stats['consecutive_fallback']+1 if trial_method == 'FALLBACK_BE' else 0
            self.stats['consecutive_fallback'] = consecutive
            self.stats['longest_fallback'] = max(self.stats['longest_fallback'], consecutive)
            self.stats['min_h'] = h if self.stats['min_h'] is None else min(h, self.stats['min_h'])
            self.stats['max_h'] = max(h, self.stats['max_h']); self.stats['max_E'] = max(info['E'], self.stats['max_E'])
            self.stats['max_newton_residual'] = max(info['residual'], self.stats['max_newton_residual'])
            self.stats['max_linear_residual'] = max(info['linear'], self.stats['max_linear_residual'])
            raw_residual = info.pop('raw_residual')
            absolute_history = info.pop('absolute_history')
            info.update({'t': self.t, 'h': h, 'method': trial_method,
                         'ratio': None if is_be else h/previous_h})
            info['endpoint_side'] = side
            self.last_step = dict(info)
            if self.t in input_set:
                if hasattr(self.system, 'node_kind'):
                    kind = self.system.node_kind(self.t)
                else:
                    kind = self.system.inputs.node_kind(self.t,question=self.system.question,geometry=self.system.geometry)
                self.needs_be = True
                self.be_reason = 'JUMP_RESTART_BE' if kind == 'JUMP' else 'KINK_RESTART_BE'
                self.h_next = self.cfg.h0
                self.y_prev = None; self.t_prev = None; self.h_prev = None
            if callback is not None:
                info['absolute_history'] = absolute_history
                callback(old_t, old_y, self.t, self.y, info, raw_residual)
                info.pop('absolute_history')
            if consecutive >= 10:
                self.failure = 'BDF2_FALLBACK_PERSISTENT'; status = 'NUMERICAL_FAILURE'; break
            if stop is not None and stop(self.t, self.y, info):
                status = 'STOP_REQUESTED'; break
        return {'status': status, 't': self.t, 'wall_seconds': time.perf_counter()-started,
                'accepted_this_call': self.stats['accepted']-before_steps, 'failure': self.failure,
                'stats': self.stats, 'algorithm': self.algorithm}
