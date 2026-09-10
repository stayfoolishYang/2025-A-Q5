"""Conservative B/C finite volumes with exact sparse RHS Jacobian.

The storage permutation is C-order (nr,nz,2), i outer/j inner; this is
permutation-equivalent to the mathematical listing in Stage04 section 8.3.
Every face is evaluated once and assembled with opposite signs. No dense
global matrix is created, including for route C.
"""
from dataclasses import dataclass
import numpy as np
from scipy.sparse import coo_matrix, csc_matrix
from .physics import properties, surface, robin_derivative, conductance, T0, C0, L0, ELL


class Grid:
    def __init__(self, nr, nz=1, route="B"):
        if isinstance(nr, bool) or int(nr) != nr or nr < 2:
            raise ValueError("nr must be an integer >= 2")
        if isinstance(nz, bool) or int(nz) != nz or nz < 1:
            raise ValueError("nz must be a positive integer")
        if route not in ("B", "C") or (route == "B" and nz != 1) or (route == "C" and nz < 2):
            raise ValueError("route B requires nz=1; route C requires nz>=2")
        self.nr, self.nz, self.route = int(nr), int(nz), route
        self.ncell, self.size = self.nr * self.nz, 2 * self.nr * self.nz
        self.xi_faces = np.linspace(0., 1., self.nr + 1)
        lo, hi = self.xi_faces[:-1], self.xi_faces[1:]
        self.omega = (hi ** 2 - lo ** 2) / 2
        self.xi = 2 * (hi ** 3 - lo ** 3) / (3 * (hi ** 2 - lo ** 2))
        self.z_faces = np.linspace(0., ELL, self.nz + 1)
        self.dz = np.diff(self.z_faces)
        self.z = (self.z_faces[:-1] + self.z_faces[1:]) / 2
        self.dry_weights = (2 * self.omega[:, None] * self.dz[None, :] / ELL).reshape(-1)
        self.cell_ids = np.arange(self.ncell).reshape(self.nr, self.nz)
        self.radial_left = self.cell_ids[:-1, :].reshape(-1)
        self.radial_right = self.cell_ids[1:, :].reshape(-1)
        self.axial_left = self.cell_ids[:, :-1].reshape(-1)
        self.axial_right = self.cell_ids[:, 1:].reshape(-1)

    def volumes(self, R):
        if not np.isfinite(R) or R <= 0:
            raise ValueError("radius must be finite and positive")
        return np.pi * R ** 2 * L0 * self.dry_weights


@dataclass
class Eval:
    f: np.ndarray
    jac: csc_matrix | None
    water: float
    water_out: float
    heat_out: float
    source_water: float
    source_heat: float
    a: np.ndarray
    volumes: np.ndarray
    radial_flux: np.ndarray
    axial_flux: np.ndarray
    surface_values: np.ndarray
    end_values: np.ndarray
    diffusion_underflow_count: int = 0


class DryingSystem:
    def __init__(self, grid, inputs, question=23, geometry="fixed", end_condition="C0",
                 test_case=None, h=25., hm=8e-7):
        if question not in (1, 23, 4):
            raise ValueError("question must be 1, 23, or 4")
        if geometry not in ("fixed", "moving"):
            raise ValueError("geometry must be fixed or moving")
        if end_condition not in ("C0", "C1"):
            raise ValueError("end_condition must be C0 or C1")
        if not np.isfinite(h) or not np.isfinite(hm) or h < 0 or hm < 0:
            raise ValueError("exchange coefficients must be finite and nonnegative")
        if test_case is not None:
            if test_case.route != grid.route:
                raise ValueError("TEST_CASE and grid route mismatch")
            if grid.route == "C" and end_condition != "C1":
                raise ValueError("axially nonuniform MMS requires C1, not zero-flux C0")
            if h == 0 or hm == 0:
                raise ValueError("MMS requires positive Robin exchange")
        self.grid, self.inputs, self.question = grid, inputs, question
        self.geometry, self.end_condition = geometry, end_condition
        self.test_case, self.h, self.hm = test_case, float(h), float(hm)

    def initial(self):
        if self.test_case is not None:
            return self.test_case.averages(self.grid, 0.)
        return np.tile((T0, C0), self.grid.ncell).astype(float)

    def boundary(self, t, side="point"):
        if self.test_case is not None:
            return self.test_case.boundary(t)
        return self.inputs.at(t, question=self.question, geometry=self.geometry, side=side)

    def material(self, T, C):
        if self.test_case is not None:
            return self.test_case.material(T, C)
        return properties(self.question, T, C)

    def boundary_environments(self, t, side="point"):
        if self.test_case is not None:
            return self.test_case.boundary_environments(self.grid, t, self.h, self.hm)
        b = self.boundary(t, side)
        return (np.tile((b.T_inf, b.C_eq), (self.grid.nz, 1)),
                np.tile((b.T_inf, b.C_eq), (self.grid.nr, 1)))

    def rhs(self, t, y, side="point"):
        return self.evaluate(t, y, side=side, jacobian=False).f

    def evaluate(self, t, y, side="point", jacobian=True):
        grid = self.grid
        state = np.asarray(y, dtype=float)
        if state.shape != (grid.size,):
            raise ValueError(f"state shape must be ({grid.size},)")
        cells = state.reshape(grid.ncell, 2)
        material = self.material(cells[:, 0], cells[:, 1])
        R = self.boundary(t, side).R
        volumes = grid.volumes(R)
        side_env, end_env = self.boundary_environments(t, side)
        a = np.asarray(material.a).reshape(-1)
        a_C = np.asarray(material.a_C).reshape(-1)
        if np.any(~np.isfinite(a)) or np.any(a <= 0):
            raise ValueError("heat mass coefficient must be finite and positive")
        # These are rates per volume, before division of the heat equation by a.
        raw = np.zeros_like(cells)
        source = np.zeros_like(cells)
        if self.test_case is not None:
            source = self.test_case.sources(grid, t).reshape(grid.ncell, 2)
            raw += source
        radial_flux = np.zeros((grid.nr + 1, grid.nz, 2))
        axial_flux = np.zeros((grid.nr, grid.nz + 1, 2))
        surface_values, end_values = np.empty((grid.nz, 2)), cells.reshape(grid.nr, grid.nz, 2)[:, -1].copy()
        rows, columns, data = [], [], []

        def add_jac(row, col, values):
            rows.append(np.asarray(row, dtype=np.int64).reshape(-1))
            columns.append(np.asarray(col, dtype=np.int64).reshape(-1))
            data.append(np.asarray(values, dtype=float).reshape(-1))

        def inner_faces(eq, coefficient, dT, dC, left, right, dl, dr, factor_left, factor_right):
            if left.size == 0:
                return np.empty(0)
            U = cells[:, eq]
            g, gl, gr = conductance(coefficient[left], coefficient[right], dl, dr)
            delta = U[left] - U[right]
            flux = g * delta
            np.add.at(raw[:, eq], left, -factor_left * flux)
            np.add.at(raw[:, eq], right, factor_right * flux)
            if jacobian:
                # Partial derivatives include coefficient changes in both cells.
                derivatives = (gl * delta * dT[left] + (g if eq == 0 else 0.),
                               gl * delta * dC[left] + (g if eq == 1 else 0.),
                               gr * delta * dT[right] - (g if eq == 0 else 0.),
                               gr * delta * dC[right] - (g if eq == 1 else 0.))
                for col, value in zip((2 * left, 2 * left + 1, 2 * right, 2 * right + 1), derivatives):
                    add_jac(2 * left + eq, col, -factor_left * value / (a[left] if eq == 0 else 1.))
                    add_jac(2 * right + eq, col, factor_right * value / (a[right] if eq == 0 else 1.))
            return flux

        def outer_faces(eq, coefficient, dT, dC, ids, environment, exchange, distance, factor):
            values, flux, _ = surface(cells[ids, eq], environment, coefficient[ids], exchange, distance)
            np.add.at(raw[:, eq], ids, -factor * flux)
            if jacobian:
                dpU, dpA = robin_derivative(cells[ids, eq], environment, coefficient[ids], exchange, distance)
                scale = -factor / (a[ids] if eq == 0 else 1.)
                add_jac(2 * ids + eq, 2 * ids, scale * (dpA * dT[ids] + (dpU if eq == 0 else 0.)))
                add_jac(2 * ids + eq, 2 * ids + 1, scale * (dpA * dC[ids] + (dpU if eq == 1 else 0.)))
            return values, flux

        xf = np.repeat(grid.xi_faces[1:-1], grid.nz)
        dl_r = R * np.repeat(grid.xi_faces[1:-1] - grid.xi[:-1], grid.nz)
        dr_r = R * np.repeat(grid.xi[1:] - grid.xi_faces[1:-1], grid.nz)
        factor_rl = xf / (R * np.repeat(grid.omega[:-1], grid.nz))
        factor_rr = xf / (R * np.repeat(grid.omega[1:], grid.nz))
        dl_z = np.tile(grid.z_faces[1:-1] - grid.z[:-1], grid.nr)
        dr_z = np.tile(grid.z[1:] - grid.z_faces[1:-1], grid.nr)
        factor_zl, factor_zr = np.tile(1. / grid.dz[:-1], grid.nr), np.tile(1. / grid.dz[1:], grid.nr)
        ids_side, ids_end = grid.cell_ids[-1, :], grid.cell_ids[:, -1]
        zero = np.zeros(grid.ncell)
        fields = ((material.k, zero, material.k_C, self.h),
                  (material.D, material.D_T, material.D_C, self.hm))
        for eq, (coefficient, dT, dC, exchange) in enumerate(fields):
            coefficient, dT, dC = (np.asarray(x).reshape(-1) for x in (coefficient, dT, dC))
            radial_flux[1:-1, :, eq] = inner_faces(eq, coefficient, dT, dC,
                grid.radial_left, grid.radial_right, dl_r, dr_r, factor_rl, factor_rr).reshape(grid.nr - 1, grid.nz)
            surface_values[:, eq], radial_flux[-1, :, eq] = outer_faces(eq, coefficient, dT, dC,
                ids_side, side_env[:, eq], exchange, R * (1. - grid.xi[-1]), 1. / (R * grid.omega[-1]))
            if grid.route == "C":
                axial_flux[:, 1:-1, eq] = inner_faces(eq, coefficient, dT, dC,
                    grid.axial_left, grid.axial_right, dl_z, dr_z, factor_zl, factor_zr).reshape(grid.nr, grid.nz - 1)
                exchange_end = exchange if self.end_condition == "C1" else 0.
                end_values[:, eq], axial_flux[:, -1, eq] = outer_faces(eq, coefficient, dT, dC,
                    ids_end, end_env[:, eq], exchange_end, ELL - grid.z[-1], 1. / grid.dz[-1])

        f = raw.copy()
        f[:, 0] /= a
        if jacobian:
            # Exact derivative of F_T = b_T/a: never omit the variable mass term.
            ids = np.arange(grid.ncell)
            add_jac(2 * ids, 2 * ids + 1, -a_C * f[:, 0] / a)
            jac = coo_matrix((np.concatenate(data), (np.concatenate(rows), np.concatenate(columns))),
                             shape=(grid.size, grid.size)).tocsc()
            jac.eliminate_zeros()
        else:
            jac = None
        water_out = 2. / (ELL * R) * np.dot(grid.dz, radial_flux[-1, :, 1])
        heat_out = 4. * np.pi * R * np.dot(grid.dz, radial_flux[-1, :, 0])
        if grid.route == "C":
            water_out += 2. / ELL * np.dot(grid.omega, axial_flux[:, -1, 1])
            heat_out += 4. * np.pi * R ** 2 * np.dot(grid.omega, axial_flux[:, -1, 0])
        underflow = material.diffusion_underflow
        return Eval(f.reshape(-1), jac, float(np.dot(grid.dry_weights, cells[:, 1])),
                    float(water_out), float(heat_out), float(np.dot(grid.dry_weights, source[:, 1])),
                    float(np.dot(volumes, source[:, 0])), a, volumes, radial_flux, axial_flux,
                    surface_values, end_values, int(np.count_nonzero(underflow)) if underflow is not None else 0)
