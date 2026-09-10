from pathlib import Path
import numpy as np
from scipy.interpolate import PchipInterpolator

DATA = Path(__file__).resolve().parents[1] / 'data'

class Boundary:
    def __init__(self, interpolation='pchip', tail='last'):
        self.data = np.loadtxt(DATA / 'boundary.csv', delimiter=',', skiprows=1)
        self.radius_data = np.loadtxt(DATA / 'radius.csv', delimiter=',', skiprows=1)
        self.interpolation = interpolation
        self.pchip = PchipInterpolator(self.data[:, 0], self.data[:, 1:], axis=0)
        self.rpchip = PchipInterpolator(self.radius_data[:, 0], self.radius_data[:, 1] / 100)
        self.tail = self.data[-1, 1:] if tail == 'last' else self.data[self.data[:, 0] >= 10800, 1:].mean(axis=0)

    def ambient(self, time):
        t = np.asarray(time)
        tc = np.clip(t, 0, self.data[-1, 0])
        if self.interpolation == 'pchip':
            values = self.pchip(tc)
        else:
            values = np.stack([np.interp(tc, self.data[:, 0], self.data[:, j]) for j in (1, 2)], axis=-1)
        return np.where((t > self.data[-1, 0])[..., None], self.tail, values)

    def radius(self, time):
        return self.rpchip(np.clip(time, 0, self.radius_data[-1, 0]))
