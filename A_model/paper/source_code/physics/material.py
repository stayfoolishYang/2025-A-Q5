import numpy as np
from numba import njit

MODEL_Q1 = 1
MODEL_Q23 = 2
MODEL_Q4 = 4

@njit(cache=True)
def validate_model(model):
    if model != MODEL_Q1 and model != MODEL_Q23 and model != MODEL_Q4:
        raise ValueError('Unknown model: use MODEL_Q1=1, MODEL_Q23=2, MODEL_Q4=4')

GX, GW = np.polynomial.legendre.leggauss(8)
GX, GW = (GX+1)/2, GW/2

@njit(cache=True)
def moisture_faces(T, C, model, mode, scales):
    """Kirchhoff/secant diffusivity: integrate D along each reconstructed edge.

    Harmonic averaging of endpoint D badly resolves the exponential dry skin.
    Positive Gauss quadrature preserves a positive transmissibility.
    """
    validate_model(model)
    result = np.zeros(len(C)-1)
    for i in range(len(result)):
        for j in range(len(GX)):
            c = C[i]*(1-GX[j])+C[i+1]*GX[j]
            t = T[i]*(1-GX[j])+T[i+1]*GX[j]+273.15
            if model == MODEL_Q1:
                d = 7e-9*np.exp(-.89/c)
            elif model == MODEL_Q23:
                d = 2.4e-3*np.exp(-.45/c-3850/t)
                if mode == 2:
                    d = 2.4e-3*np.exp(-.45/2.55-3850/301.15)
            elif model == MODEL_Q4:
                d = 4.2e-4*np.exp(-.30/c-3850/t)
            result[i] += GW[j]*d*scales[0]
    return result

@njit(cache=True)
def properties(T, C, model, mode, scales):
    """SI units; scales ordered D, hm, hT, k. mode 1 freezes thermal properties."""
    validate_model(model)
    n = len(C)
    capacity, k, D = np.empty(n), np.empty(n), np.empty(n)
    for i in range(n):
        c = C[i]
        if c <= 0 or T[i] <= -273.15:
            raise ValueError('Nonphysical Picard iterate')
        ct = 2.55 if mode == 1 else c
        if model == MODEL_Q1:
            capacity[i], k[i] = 820.0 * 2600.0, 0.36
            D[i] = 7e-9 * np.exp(-0.89 / c)
        elif model == MODEL_Q23:
            capacity[i] = (650 + 128 * ct) * (1450 + 2736 * ct / (ct + 1))
            k[i] = 0.21 + 0.38 * ct / (ct + 1)
            D[i] = 2.4e-3 * np.exp(-0.45 / c - 3850 / (T[i] + 273.15))
        elif model == MODEL_Q4:
            capacity[i] = (760 + 90 * ct) * (1850 + 2150 * ct / (ct + 1))
            k[i] = 0.12 + 0.20 * ct / (ct + 1)
            D[i] = 4.2e-4 * np.exp(-0.30 / c - 3850 / (T[i] + 273.15))
        if mode == 2:  # Full fixed-parameter ablation, frozen at the initial state.
            if model == MODEL_Q23:
                capacity[i] = (650+128*2.55)*(1450+2736*2.55/3.55)
                k[i] = 0.21+0.38*2.55/3.55
                D[i] = 2.4e-3*np.exp(-0.45/2.55-3850/301.15)
        k[i] *= scales[3]
        D[i] *= scales[0]
    return capacity, k, D
