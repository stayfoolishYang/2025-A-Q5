"""Authoritative empirical material and half-cell Robin laws (A26-04-v2)."""
from dataclasses import dataclass
import numpy as np

T0 = 301.15
C0 = 2.55
R0 = 0.02
L0 = 0.25
ELL = L0 / 2.0


@dataclass(frozen=True)
class Material:
    a: np.ndarray
    k: np.ndarray
    D: np.ndarray
    a_C: np.ndarray
    k_C: np.ndarray
    D_C: np.ndarray
    D_T: np.ndarray
    diffusion_underflow: np.ndarray | None = None


def properties(question, T, C):
    """Return vectorized SI properties and exact derivatives, without clipping.

    The zero-moisture diffusion and its right derivatives are zero. Positive
    moisture may give true binary64 underflow; this is exposed rather than
    replacing it by an arbitrary diffusion floor.
    """
    T, C = np.broadcast_arrays(np.asarray(T, dtype=float), np.asarray(C, dtype=float))
    if np.any(~np.isfinite(T)) or np.any(~np.isfinite(C)) or np.any(T <= 0) or np.any(C < 0):
        raise ValueError("material requires finite T > 0 K and C >= 0 kg/kg")
    zero = np.zeros_like(C)
    if question == 1:
        rho, cp = zero + 820.0, zero + 2600.0
        rho_C, cp_C, k_C = zero, zero, zero
        k, prefactor, exponent, gamma = zero + .36, 7e-9, .89, 0.0
    elif question in (23, 4):
        if question == 23:
            rho0, rho1, cp0, cp1, k0, k1 = 650., 128., 1450., 2736., .21, .38
            prefactor, exponent = 2.4e-3, .45
        else:
            rho0, rho1, cp0, cp1, k0, k1 = 760., 90., 1850., 2150., .12, .20
            prefactor, exponent = 4.2e-4, .30
        ratio = C / (1. + C)
        rho, cp, k = rho0 + rho1 * C, cp0 + cp1 * ratio, k0 + k1 * ratio
        rho_C = zero + rho1
        cp_C = cp1 / (1. + C) ** 2
        k_C = k1 / (1. + C) ** 2
        gamma = 3850.
    else:
        raise ValueError("question must be 1, 23, or 4")
    D, D_C, D_T = zero.copy(), zero.copy(), zero.copy()
    positive = C > 0
    with np.errstate(over="ignore", under="ignore", divide="ignore"):
        log_D = np.log(prefactor) - exponent / C[positive] - gamma / T[positive]
        D[positive] = np.exp(log_D)
        D_C[positive] = np.exp(log_D + np.log(exponent) - 2 * np.log(C[positive]))
        if gamma:
            D_T[positive] = np.exp(log_D + np.log(gamma) - 2 * np.log(T[positive]))
    return Material(rho * cp, k, D, rho_C * cp + rho * cp_C,
                    k_C, D_C, D_T, positive & (D == 0))


def surface(U, env, A, b, delta):
    """Return (surface value, outward flux, beta) from exact F2 algebra.

    ``A`` is the adjacent *cell* coefficient, ``delta`` is its physical
    half-cell distance, and zero exchange retains the adjacent value.
    """
    U, env, A, b, delta = np.broadcast_arrays(*map(
        lambda x: np.asarray(x, dtype=float), (U, env, A, b, delta)))
    if any(np.any(~np.isfinite(x)) for x in (U, env, A, b, delta)):
        raise ValueError("Robin arguments must be finite")
    if np.any(A < 0) or np.any(b < 0) or np.any(delta <= 0):
        raise ValueError("Robin requires A >= 0, b >= 0, delta > 0")
    beta = np.ones_like(U)
    exposed = b > 0
    denominator = A[exposed] + b[exposed] * delta[exposed]
    beta[exposed] = A[exposed] / denominator
    value = env + beta * (U - env)
    # Avoid cancellation in the zero-exchange identity U_s = U.
    value = np.where(exposed, value, U)
    flux = b * beta * (U - env)
    return value, flux, beta


def robin_derivative(U, env, A, b, delta):
    """F2 flux derivatives (partial p / partial U, partial p / partial A)."""
    _, _, beta = surface(U, env, A, b, delta)
    U, env, A, b, delta = np.broadcast_arrays(U, env, A, b, delta)
    d_A = np.zeros_like(beta)
    active = b > 0
    d_A[active] = (b[active] * (1. - beta[active]) /
                   (A[active] + b[active] * delta[active])) * (U[active] - env[active])
    return b * beta, d_A


def conductance(A_left, A_right, distance_left, distance_right):
    """Stable series conductance and its derivatives, in physical meters.

    A zero adjacent coefficient has zero limiting conductance. Its actual
    material derivatives are also zero at C=0 and at recorded underflow.
    """
    al, ar, dl, dr = np.broadcast_arrays(*map(
        lambda x: np.asarray(x, dtype=float),
        (A_left, A_right, distance_left, distance_right)))
    if np.any(al < 0) or np.any(ar < 0) or np.any(dl <= 0) or np.any(dr <= 0):
        raise ValueError("invalid face coefficients or distances")
    g, dleft, dright = np.zeros_like(al), np.zeros_like(al), np.zeros_like(al)
    active = (al > 0) & (ar > 0)
    m = np.minimum(al[active], ar[active])
    denominator = dl[active] * (m / al[active]) + dr[active] * (m / ar[active])
    g[active] = m / denominator
    dleft[active] = dl[active] * (g[active] / al[active]) ** 2
    dright[active] = dr[active] * (g[active] / ar[active]) ** 2
    return g, dleft, dright
