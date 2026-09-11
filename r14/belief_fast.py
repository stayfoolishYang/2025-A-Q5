"""Soft geometric discovery belief. No engine, scene truth, or solver RNG access."""
import math
import numpy as np
from scipy.stats import qmc


def detects(states, nodes):
    """States columns x,y,R,is_directional,phi; result nodes x states.

    Match engine radius/direction BEFORE near, including its angular tolerance.
    """
    nodes = np.asarray(nodes, dtype=float).reshape(-1, 2)
    d = nodes[:, None, :] - states[None, :, :2]
    distance = np.linalg.norm(d, axis=2)
    angle = np.degrees(np.arctan2(d[..., 1], d[..., 0]))
    delta = np.abs((angle - np.degrees(states[:, 4]) + 180) % 360 - 180)
    return ((distance <= states[:, 2]) &
            ((states[:, 3] == 0) | (distance == 0) | (delta <= 90.000000001)))


def evidence(likelihood, known):
    """Partition function for uniform N in 10..16 and uniform channel subsets.

    Positive-channel geometric likelihood factors cancel when conditioning only
    on existence of those channels. Unknown source geometries independent a priori.
    """
    coeff = np.zeros(21); coeff[0] = 1.
    for value in likelihood:
        coeff[1:] += value * coeff[:-1].copy()
    return sum(coeff[n-known] / math.comb(20, n) / 7
               for n in range(max(10, known), 17) if 0 <= n-known <= len(likelihood))


class DiscoveryBelief:
    def __init__(self, power=17, seed=14001):
        u = qmc.Sobol(5, scramble=True, seed=seed).random_base2(power)
        radius = 2000 * np.sqrt(u[:, 0]); angle = 2*np.pi*u[:, 1]
        self.states = np.column_stack((radius*np.cos(angle), radius*np.sin(angle),
                                      1000+500*u[:, 2], u[:, 3] < .5, 2*np.pi*u[:, 4]))
        self.masks = {c: np.ones(len(u), dtype=bool) for c in range(1, 21)}
        self.seen = set()
        self._hit_cache = {}
        self.negative_points = {c: set() for c in range(1, 21)}

    def hitmatrix(self, nodes):
        rows = []
        for point in nodes:
            key = tuple(map(float, point))
            if key not in self._hit_cache:
                if len(self._hit_cache) >= 128:
                    self._hit_cache.pop(next(iter(self._hit_cache)))
                self._hit_cache[key] = detects(self.states, [point])[0]
            rows.append(self._hit_cache[key])
        return np.asarray(rows)

    def observe(self, channel, point, result):
        if channel not in self.masks or result not in ('no_signal', 'near', 'direction'):
            raise ValueError('Invalid observation')
        if result != 'no_signal':
            self.seen.add(channel)
        elif channel not in self.seen:
            key = tuple(map(float, point))
            if key not in self.negative_points[channel]:
                self.masks[channel] &= ~self.hitmatrix([point])[0]
                self.negative_points[channel].add(key)

    def predict(self, nodes, conditioned=True):
        channels = [c for c in self.masks if c not in self.seen]
        hits = self.hitmatrix(nodes)
        masks = np.array([self.masks[c] if conditioned else np.ones(len(self.states), bool)
                          for c in channels], dtype=bool).reshape(len(channels), -1)
        likelihood = masks.mean(axis=1)
        mass_cache = {}
        masses = []
        for c, mask in zip(channels, masks):
            key = frozenset(self.negative_points[c]) if conditioned else None
            if key not in mass_cache:
                mass_cache[key] = (hits & mask).mean(axis=1)
            masses.append(mass_cache[key])
        masses = np.array(masses)
        z = evidence(likelihood, len(self.seen))
        if z <= 0:
            return dict(available=False, reason='finite_particle_support_exhausted')
        coefficients = np.array([evidence(np.delete(likelihood, i), len(self.seen)+1) / z
                                 for i in range(len(channels))])
        # Coefficient integrates other channels; the numerator contains this
        # channel's prior mass exactly once.
        unconditional = masses * coefficients[:, None]
        any_hit = np.array([1-evidence(likelihood-masses[:, j], len(self.seen))/z
                            for j in range(hits.shape[0])])
        return dict(available=True, channels=channels, expected_new=unconditional.sum(axis=0),
                    probability_any=np.clip(any_hit, 0, 1), probability_channel=unconditional,
                    existence=likelihood*coefficients, likelihood=likelihood,
                    conditional=np.divide(masses, likelihood[:, None], out=np.zeros_like(masses), where=likelihood[:, None]>0),
                    zero_support_channels=[channels[i] for i in np.flatnonzero(likelihood == 0)], particles=len(self.states))

    def survival(self, nodes):
        """Joint probability of no discovery through each ordered node prefix."""
        channels = [c for c in self.masks if c not in self.seen]
        masks = np.array([self.masks[c] for c in channels], bool).reshape(len(channels), -1)
        z = evidence(masks.mean(axis=1), len(self.seen))
        if z <= 0: raise ValueError('finite_particle_support_exhausted')
        out = [1.]
        for hit in self.hitmatrix(nodes):
            masks &= ~hit
            out.append(evidence(masks.mean(axis=1), len(self.seen))/z)
        return np.array(out)
