"""Proof-backed reception disks with an independent rational interval verifier."""
from fractions import Fraction as F
from functools import lru_cache
import math
import numpy as np
from geometry import ERROR_DEG


def outward(lo, hi, bits=48):
    scale = 1 << bits
    return F((lo*scale).__floor__(), scale), F((hi*scale).__ceil__(), scale)


@lru_cache(None)
def pi_interval():
    def atan_bounds(n):
        total = sum((F((-1)**k, (2*k+1)*n**(2*k+1)) for k in range(48)), F(0))
        following = total+F(1, 97*n**97)
        return total, following
    a, b = atan_bounds(5), atan_bounds(239)
    return outward(16*a[0]-4*b[1], 16*a[1]-4*b[0], 160)


@lru_cache(None)
def unit_intervals(degrees):
    degrees = F(degrees) % 360
    if degrees > 180:
        degrees -= 360
    exact = {F(0):(1,0), F(90):(0,1), F(-90):(0,-1), F(180):(-1,0)}
    if degrees in exact:
        return tuple((F(v), F(v)) for v in exact[degrees])
    ends = sorted(p*degrees/180 for p in pi_interval())
    x, dx = sum(ends)/2, (ends[1]-ends[0])/2
    values = []
    for parity in (0, 1):
        value = sum(((-1)**k*x**(2*k+parity)/math.factorial(2*k+parity)
                     for k in range(32)), F(0))
        remainder = F(4**(64+parity), math.factorial(64+parity))+dx
        values.append(outward(value-remainder, value+remainder))
    return tuple(values)


def exact_disk(center, radius=1000):
    return dict(center=[(F(float(v)), F(float(v))) for v in center], radius=F(radius))


def shifted_disk(p, radius_from_p, angle):
    unit = unit_intervals(angle)
    return dict(center=[(F(float(v))+radius_from_p*lo, F(float(v))+radius_from_p*hi)
                        for v, (lo, hi) in zip(p, unit)], radius=F(1000),
                known_point=tuple(F(float(v)) for v in p), known_slack=F(1000**2-radius_from_p**2))


def explicit_safe_inner_region_q0(p=(0.,0.), theta=30., alpha=ERROR_DEG):
    if not 0 <= alpha <= 90:
        raise ValueError('Q0 proof requires 0 <= alpha <= 90 degrees')
    return [exact_disk(p)]+[shifted_disk(p, 1000, F(theta)+sign*F(alpha)) for sign in (-1,1)]


def direction_region_q5(p=(0.,0.), theta=30., alpha=ERROR_DEG, arena_radius=1800.):
    if not 0 <= alpha <= 90:
        raise ValueError('Q5 proof requires 0 <= alpha <= 90 degrees')
    # ponytail: only certify exact full annular sectors; clipped exact Qvis is out of scope.
    if np.linalg.norm(p)+1500 > arena_radius:
        raise ValueError('STOP_M3_GENERAL_CLIPPED_UNCERTIFIED')
    return [shifted_disk(p, r, F(theta)+sign*F(alpha)) for r in (5,1000) for sign in (-1,1)]


def verify_guaranteed_reception(q, disks):
    """Exact comparison against outward-enclosed centers, never a sampling test."""
    if np.asarray(q).shape != (2,) or not np.isfinite(q).all() or not disks:
        raise ValueError('Nonempty constraints and finite 2D station required')
    q = tuple(F(float(v)) for v in q)
    slacks, lower_distances = [], []
    for disk in disks:
        if q == disk.get('known_point'):
            upper_distance = disk['radius']**2-disk['known_slack']
            lower_distance = upper_distance
        else:
            upper_distance = sum(max((v-lo)**2,(v-hi)**2) for v,(lo,hi) in zip(q,disk['center']))
            lower_distance = sum(0 if lo<=v<=hi else min((v-lo)**2,(v-hi)**2)
                                 for v,(lo,hi) in zip(q,disk['center']))
        slacks.append(disk['radius']**2-upper_distance)
        lower_distances.append(lower_distance-disk['radius']**2)
    slack = min(slacks)
    status = 'SAFE' if slack>=0 else ('UNSAFE' if max(lower_distances)>0 else 'UNRESOLVED')
    index = slacks.index(slack)
    return dict(verified=status=='SAFE', status=status, squared_slack_lower_m2=str(slack),
                limiting_disk_index=index,
                limiting_center_intervals=[[str(lo),str(hi)] for lo,hi in disks[index]['center']])


def floating_disks(disks):
    return [(np.array([float((lo+hi)/2) for lo,hi in d['center']]), float(d['radius'])) for d in disks]


def boundary_distance(q, disks):
    """FP64 estimate; positive distance to complement for an interior point."""
    return min(r-float(np.linalg.norm(q-c)) for c,r in floating_disks(disks))


def first_response_disposition(kind):
    if kind == 'near':
        return dict(second_station_needed=False, local_clearance_distance_upper_m=5., actions_sent=0)
    if kind == 'direction':
        return dict(second_station_needed=True, source_distance_lower_exclusive_m=5., actions_sent=0)
    raise ValueError('Q2 requires a successful first response')
