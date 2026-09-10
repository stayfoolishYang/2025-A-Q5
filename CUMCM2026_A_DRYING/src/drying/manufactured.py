"""Explicitly isolated, constant-coefficient manufactured solutions (TEST ONLY)."""
from dataclasses import dataclass
import numpy as np
from .physics import Material, R0, ELL, T0


@dataclass(frozen=True)
class TestBoundary:
    T_inf: float
    C_eq: float
    R: float
    Rdot: float


@dataclass(frozen=True)
class ManufacturedCase:
    """A26-04-v2 V1, with nonuniform axial perturbation for route C.

    Constants/backgrounds are never multiplied by the axial perturbation.
    Source arrays are (s_T in W/m3, s_C in kg/kg/s), interleaved like state.
    """
    moving: bool = False
    route: str = "B"
    tau: float = 1000.
    D: float = 1e-8
    k: float = .36
    a: float = 820. * 2600.
    C_b: float = 1.
    A_C: float = .2
    T_b: float = T0
    A_T: float = 2.

    def __post_init__(self):
        if self.route not in ("B", "C"):
            raise ValueError("MMS route must be B or C")
        if (self.tau, self.D, self.k, self.a) != (1000., 1e-8, .36, 820. * 2600.):
            raise ValueError("MMS physical constants are fixed by A26-04-v2")

    def boundary(self, t):
        if not np.isfinite(t) or t < 0 or t > self.tau:
            raise ValueError("manufactured case is defined only for 0 <= t <= 1000 s")
        R = R0 * (1. - .1 * t / self.tau) if self.moving else R0
        Rdot = -.1 * R0 / self.tau if self.moving else 0.
        return TestBoundary(self.T_b, self.C_b, R, Rdot)

    def material(self, T, C):
        T, C = np.broadcast_arrays(np.asarray(T, float), np.asarray(C, float))
        if np.any(~np.isfinite(T)) or np.any(~np.isfinite(C)) or np.any(T <= 0) or np.any(C < 0):
            raise ValueError("invalid manufactured state")
        zeros = np.zeros_like(T)
        return Material(zeros + self.a, zeros + self.k, zeros + self.D,
                        zeros, zeros, zeros, zeros, zeros.astype(bool))

    def _moments(self, grid):
        if grid.route != self.route:
            raise ValueError("manufactured case and grid routes differ")
        xf = grid.xi_faces
        p = 1. - .5 * (xf[:-1] ** 2 + xf[1:] ** 2)
        if self.route == "B":
            q = np.ones(1)
        else:
            zf = grid.z_faces
            q = 1. - (zf[1:] ** 3 - zf[:-1] ** 3) / (3 * grid.dz * ELL ** 2)
        return p[:, None], q[None, :]

    def averages(self, grid, t):
        self.boundary(t)
        p, q = self._moments(grid)
        perturbation = np.exp(-t / self.tau) * p * q
        return np.stack((self.T_b + self.A_T * perturbation,
                         self.C_b + self.A_C * perturbation), axis=-1).reshape(-1)

    def average_derivative(self, grid, t):
        p, q = self._moments(grid)
        e = -np.exp(-t / self.tau) * p * q / self.tau
        return np.stack((self.A_T * e, self.A_C * e), axis=-1).reshape(-1)

    def exact(self, xi, z, t):
        self.boundary(t)
        xi, z = np.broadcast_arrays(np.asarray(xi, float), np.asarray(z, float))
        q = 1. if self.route == "B" else 1. - (z / ELL) ** 2
        e = np.exp(-t / self.tau) * (1. - xi ** 2) * q
        return self.T_b + self.A_T * e, self.C_b + self.A_C * e

    def sources(self, grid, t):
        R = self.boundary(t).R
        p, q = self._moments(grid)
        e = np.exp(-t / self.tau)
        axial_C = 0. if self.route == "B" else 2 * self.D * p / ELL ** 2
        axial_T = 0. if self.route == "B" else 2 * self.k * p / ELL ** 2
        sC = self.A_C * e * (-p * q / self.tau + 4 * self.D * q / R ** 2 + axial_C)
        sT = self.A_T * e * (-self.a * p * q / self.tau + 4 * self.k * q / R ** 2 + axial_T)
        return np.stack((sT, sC), axis=-1).reshape(-1)

    def boundary_environments(self, grid, t, h, hm):
        """Exact area-averaged side (nz,2) and end (nr,2) environments."""
        if h <= 0 or hm <= 0:
            raise ValueError("Robin MMS requires positive h and hm")
        R = self.boundary(t).R
        p, q = self._moments(grid)
        e = np.exp(-t / self.tau)
        side = np.column_stack((self.T_b - 2 * self.k * self.A_T * e * q.ravel() / (R * h),
                                self.C_b - 2 * self.D * self.A_C * e * q.ravel() / (R * hm)))
        end = np.column_stack((self.T_b - 2 * self.k * self.A_T * e * p.ravel() / (ELL * h),
                               self.C_b - 2 * self.D * self.A_C * e * p.ravel() / (ELL * hm)))
        return side, end
