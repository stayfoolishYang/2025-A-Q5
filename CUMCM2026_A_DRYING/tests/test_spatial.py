"""Numerical implementation tests, not validation of drying predictions."""
from dataclasses import dataclass
import numpy as np
import pytest
from numpy.polynomial.legendre import leggauss
from drying.physics import properties, surface, conductance, R0, L0, ELL
from drying.spatial import Grid, DryingSystem
from drying.manufactured import ManufacturedCase


@dataclass
class Boundary:
    T_inf: float = 325.
    C_eq: float = .15
    R: float = R0
    Rdot: float = 0.


class ConstantInputs:
    def at(self, t, question=23, geometry="fixed", side="point"):
        return Boundary(R=R0 * (1. - t * 1e-5) if geometry == "moving" else R0,
                        Rdot=-R0 * 1e-5 if geometry == "moving" else 0.)


@pytest.mark.parametrize("question", [1, 23, 4])
def test_material_derivatives_and_zero_limit(question):
    T, C = np.array([303., 322., 345.]), np.array([.04, .7, 2.5])
    m = properties(question, T, C)
    eps_C, eps_T = 2e-7, 2e-4
    plus, minus = properties(question, T, C + eps_C), properties(question, T, C - eps_C)
    for name in ("a", "k", "D"):
        np.testing.assert_allclose((getattr(plus, name) - getattr(minus, name)) / (2 * eps_C),
                                   getattr(m, name + "_C"), rtol=2e-7, atol=1e-15)
    dT = (properties(question, T + eps_T, C).D - properties(question, T - eps_T, C).D) / (2 * eps_T)
    np.testing.assert_allclose(dT, m.D_T, rtol=1e-8, atol=1e-20)
    z = properties(question, T, np.array([0., 1e-300, .01]))
    assert z.D[0] == z.D_C[0] == z.D_T[0] == 0.
    assert z.D[1] == z.D_C[1] == 0. and z.diffusion_underflow[1]
    assert np.all(np.isfinite(z.a))
    with pytest.raises(ValueError):
        properties(question, 300., -.01)


def test_empirical_values_are_original_question_formulas():
    m1 = properties(1, 301.15, 2.55)
    assert float(m1.a) == 820 * 2600
    assert float(m1.k) == .36
    assert float(m1.D) == pytest.approx(7e-9 * np.exp(-.89 / 2.55))
    for q, rho0, rho1, cp0, cp1, k0, k1, pref, b in (
        (23, 650, 128, 1450, 2736, .21, .38, 2.4e-3, .45),
        (4, 760, 90, 1850, 2150, .12, .20, 4.2e-4, .30)):
        m = properties(q, 321., 1.3)
        assert float(m.a) == pytest.approx((rho0 + rho1 * 1.3) * (cp0 + cp1 * 1.3 / 2.3))
        assert float(m.k) == pytest.approx(k0 + k1 * 1.3 / 2.3)
        assert float(m.D) == pytest.approx(pref * np.exp(-b / 1.3 - 3850 / 321.))


def test_robin_sign_limits_and_shared_flux():
    U = np.array([2., .1, 1.])
    env = np.array([.2, .2, 1.])
    A, b, delta = 1e-8, 8e-7, .001
    Us, p, beta = surface(U, env, A, b, delta)
    np.testing.assert_allclose(p, A * (U - Us) / delta, rtol=1e-13, atol=1e-22)
    np.testing.assert_allclose(p, b * (Us - env), rtol=1e-13, atol=1e-22)
    assert p[0] > 0 and p[1] < 0 and p[2] == 0
    assert np.all((Us >= np.minimum(U, env)) & (Us <= np.maximum(U, env)))
    uz, pz, bz = surface(U, env, 0., 0., delta)
    np.testing.assert_array_equal(uz, U)
    assert np.all(pz == 0) and np.all(bz == 1)
    ud, pd, bd = surface(U, env, 0., b, delta)
    np.testing.assert_array_equal(ud, env)
    assert np.all(pd == 0) and np.all(bd == 0)
    assert np.all(beta > 0)


def test_tiny_conductance_does_not_create_diffusion_floor():
    g, gl, gr = conductance(np.array([0., 1e-300, 1e-200]), np.array([1e-8, 1e-8, 1e-200]), .001, .002)
    assert g[0] == 0 and gl[0] == gr[0] == 0
    assert np.all(np.isfinite(g)) and np.all(np.isfinite(gl)) and np.all(np.isfinite(gr))
    assert g[1] == pytest.approx(1e-297, rel=1e-12, abs=0.)
    assert g[2] == pytest.approx(1e-200 / .003, rel=1e-12, abs=0.)


@pytest.mark.parametrize("route,nz", [("B", 1), ("C", 4)])
def test_grid_uses_volume_centroids_and_full_domain_weights(route, nz):
    grid = Grid(7, nz, route)
    assert np.sum(grid.dry_weights) == pytest.approx(1.)
    assert np.sum(grid.volumes(.017)) == pytest.approx(np.pi * .017 ** 2 * L0)
    assert grid.xi[0] == pytest.approx(2 / (3 * grid.nr))
    assert grid.xi[0] != .5 / grid.nr
    assert np.dot(grid.omega, grid.xi) == pytest.approx(1. / 3.)


@pytest.mark.parametrize("question", [1, 23, 4])
@pytest.mark.parametrize("route,nz,end", [("B", 1, "C0"), ("C", 4, "C0"), ("C", 4, "C1")])
def test_sparse_exact_jacobian_matches_scaled_directional_derivatives(question, route, nz, end):
    grid = Grid(6, nz, route)
    system = DryingSystem(grid, ConstantInputs(), question=question, geometry="moving", end_condition=end)
    rng = np.random.default_rng(431)
    y = np.column_stack((315. + 8 * rng.random(grid.ncell), .35 + 2 * rng.random(grid.ncell))).reshape(-1)
    evaluated = system.evaluate(40., y)
    assert evaluated.jac.format == "csc"
    assert evaluated.jac.nnz <= 20 * grid.ncell
    for _ in range(3):
        direction = rng.normal(size=(grid.ncell, 2)) * np.array([10., .5])
        direction = direction.reshape(-1)
        eps = 1e-5
        fd = (system.rhs(40., y + eps * direction) - system.rhs(40., y - eps * direction)) / (2 * eps)
        analytic = evaluated.jac @ direction
        np.testing.assert_allclose(fd, analytic, rtol=3e-6, atol=1e-8)


@pytest.mark.parametrize("route,nz,end", [("B", 1, "C0"), ("C", 5, "C0"), ("C", 5, "C1")])
def test_conservation_is_exact_instantaneously_with_state_dependent_properties(route, nz, end):
    grid = Grid(9, nz, route)
    system = DryingSystem(grid, ConstantInputs(), question=4, geometry="moving", end_condition=end)
    rng = np.random.default_rng(982)
    y = np.column_stack((310. + 20 * rng.random(grid.ncell), .7 + rng.random(grid.ncell))).reshape(-1)
    ev = system.evaluate(70., y)
    f = ev.f.reshape(-1, 2)
    moisture_terms = grid.dry_weights * f[:, 1]
    heat_terms = ev.volumes * ev.a * f[:, 0]
    assert abs(sum(moisture_terms) + ev.water_out) <= 1e-13 * max(sum(abs(moisture_terms)), abs(ev.water_out))
    assert abs(sum(heat_terms) + ev.heat_out) <= 1e-13 * max(sum(abs(heat_terms)), abs(ev.heat_out))
    assert ev.source_water == ev.source_heat == 0
    assert np.all(ev.radial_flux[0] == 0) and np.all(ev.axial_flux[:, 0] == 0)


@pytest.mark.parametrize("geometry", ["fixed", "moving"])
def test_closed_uniform_state_stays_constant_even_when_radius_moves(geometry):
    for route, nz in (("B", 1), ("C", 3)):
        system = DryingSystem(Grid(5, nz, route), ConstantInputs(), question=4,
                              geometry=geometry, h=0., hm=0.)
        ev = system.evaluate(550., system.initial())
        np.testing.assert_array_equal(ev.f, np.zeros(system.grid.size))
        assert ev.water == pytest.approx(2.55)
        assert ev.water_out == ev.heat_out == 0.


@pytest.mark.parametrize("geometry", ["fixed", "moving"])
def test_C0_reduces_exactly_to_B_for_axially_identical_states(geometry):
    nr, nz = 8, 5
    b = DryingSystem(Grid(nr), ConstantInputs(), question=4, geometry=geometry)
    c = DryingSystem(Grid(nr, nz, "C"), ConstantInputs(), question=4, geometry=geometry)
    cells = np.column_stack((np.linspace(310., 320., nr), np.linspace(2.1, 1.2, nr)))
    vb = b.evaluate(35., cells.reshape(-1))
    vc = c.evaluate(35., np.repeat(cells[:, None, :], nz, axis=1).reshape(-1))
    np.testing.assert_allclose(vc.f.reshape(nr, nz, 2), np.repeat(vb.f.reshape(nr, 1, 2), nz, axis=1), rtol=2e-14, atol=1e-14)
    assert vc.water == pytest.approx(vb.water, rel=1e-14)
    assert vc.water_out == pytest.approx(vb.water_out, rel=1e-14)
    assert vc.heat_out == pytest.approx(vb.heat_out, rel=1e-14)
    direction = np.column_stack((np.linspace(.2, .8, nr), np.linspace(-.3, .2, nr)))
    jvb = vb.jac @ direction.reshape(-1)
    jvc = vc.jac @ np.repeat(direction[:, None, :], nz, axis=1).reshape(-1)
    np.testing.assert_allclose(jvc.reshape(nr, nz, 2), np.repeat(jvb.reshape(nr, 1, 2), nz, axis=1), rtol=2e-12, atol=1e-12)


@pytest.mark.parametrize("moving", [False, True])
def test_MMS_exact_averages_sources_and_boundary_area_averages(moving):
    grid, case = Grid(5, 4, "C"), ManufacturedCase(moving=moving, route="C")
    t = 317.
    y = case.averages(grid, t).reshape(grid.nr, grid.nz, 2)
    src = case.sources(grid, t).reshape(grid.nr, grid.nz, 2)
    xg, wg = leggauss(4)
    R, e = case.boundary(t).R, np.exp(-t / case.tau)
    for i in range(grid.nr):
        xl, xr = grid.xi_faces[i:i + 2]
        xi, wx = (xl + xr) / 2 + (xr - xl) * xg / 2, (xr - xl) * wg / 2
        for j in range(grid.nz):
            zl, zr = grid.z_faces[j:j + 2]
            z, wz = (zl + zr) / 2 + (zr - zl) * xg / 2, (zr - zl) * wg / 2
            p, q = 1. - xi[:, None] ** 2, 1. - (z[None, :] / ELL) ** 2
            weight = (wx * xi)[:, None] * wz[None, :] / (grid.omega[i] * grid.dz[j])
            exact = case.exact(xi[:, None], z[None, :], t)
            np.testing.assert_allclose(y[i, j], [np.sum(weight * u) for u in exact], rtol=1e-14)
            source_c = case.A_C * e * (-p * q / case.tau + 4 * case.D * q / R ** 2 + 2 * case.D * p / ELL ** 2)
            source_t = case.A_T * e * (-case.a * p * q / case.tau + 4 * case.k * q / R ** 2 + 2 * case.k * p / ELL ** 2)
            np.testing.assert_allclose(src[i, j], [np.sum(weight * source_t), np.sum(weight * source_c)], rtol=1e-13)
    side, end = case.boundary_environments(grid, t, 25., 8e-7)
    assert np.ptp(side[:, 0]) > 0 and np.ptp(end[:, 0]) > 0
    qmean = 1. - (grid.z_faces[1:] ** 3 - grid.z_faces[:-1] ** 3) / (3 * grid.dz * ELL ** 2)
    pmean = 1. - .5 * (grid.xi_faces[1:] ** 2 + grid.xi_faces[:-1] ** 2)
    np.testing.assert_allclose(25. * (case.T_b - side[:, 0]), 2 * case.k * case.A_T * e * qmean / R, rtol=1e-12)
    np.testing.assert_allclose(8e-7 * (case.C_b - end[:, 1]), 2 * case.D * case.A_C * e * pmean / ELL, rtol=1e-12)


@pytest.mark.parametrize("route,nz", [("B", 1), ("C", 5)])
@pytest.mark.parametrize("moving", [False, True])
def test_MMS_sources_enter_both_full_domain_balance_laws(route, nz, moving):
    grid, case = Grid(10, nz, route), ManufacturedCase(moving=moving, route=route)
    system = DryingSystem(grid, None, test_case=case, end_condition="C1")
    ev = system.evaluate(210., case.averages(grid, 210.))
    rates = ev.f.reshape(-1, 2)
    assert abs(np.dot(grid.dry_weights, rates[:, 1]) + ev.water_out - ev.source_water) < 2e-18
    assert abs(np.dot(ev.volumes * ev.a, rates[:, 0]) + ev.heat_out - ev.source_heat) < 1e-11
    assert ev.source_water != 0 and ev.source_heat != 0
    assert np.any(ev.radial_flux[-1] != 0)
    if route == "C":
        assert np.any(ev.axial_flux[:, -1] != 0)


@pytest.mark.parametrize("route", ["B", "C"])
@pytest.mark.parametrize("moving", [False, True])
def test_MMS_weighted_spatial_consistency_improves_under_refinement(route, moving):
    case = ManufacturedCase(moving=moving, route=route)
    errors = []
    for nr in (10, 20, 40):
        grid = Grid(nr, 1 if route == "B" else nr // 2, route)
        system = DryingSystem(grid, None, test_case=case, end_condition="C1")
        error = (system.rhs(220., case.averages(grid, 220.)) - case.average_derivative(grid, 220.)).reshape(-1, 2)
        errors.append(np.sqrt(np.sum(grid.dry_weights[:, None] * error ** 2, axis=0)))
    assert np.all(np.asarray(errors[1:]) < np.asarray(errors[:-1]))
    # This is consistency evidence, not an assumed global solution order.
    assert np.all(errors[-1] < .65 * errors[0])


def test_MMS_C0_is_rejected_and_background_is_not_axially_scaled():
    case, grid = ManufacturedCase(route="C"), Grid(4, 3, "C")
    with pytest.raises(ValueError, match="C1"):
        DryingSystem(grid, None, test_case=case, end_condition="C0")
    y = case.averages(grid, 0.).reshape(-1, 2)
    assert np.all(y[:, 0] > case.T_b) and np.all(y[:, 1] > case.C_b)
    assert case.exact(.3, ELL, 0.) == (case.T_b, case.C_b)
