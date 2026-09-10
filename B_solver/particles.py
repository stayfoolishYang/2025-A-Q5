"""Mixed omnidirectional/directional feasible hypotheses; never a coverage certificate."""
import numpy as np
from geometry import ERROR_DEG, sample_poly, candidate_views, next_view, diameter


def feasible(p, observation):
    s, result, angle = observation
    delta = np.asarray(s) - p[:, :2]
    distance = np.linalg.norm(delta, axis=1)
    front = np.sum(delta * np.c_[np.cos(p[:, 2]), np.sin(p[:, 2])], axis=1) >= 0
    signal = (distance <= p[:, 3]) & ((p[:, 4] == 0) | front)
    if result == 'no_signal':
        return ~signal
    if result == 'near':
        return signal & (distance <= 5)
    bearing = np.rad2deg(np.arctan2(-delta[:, 1], -delta[:, 0]))
    error = (bearing-angle+180) % 360 - 180
    return signal & (distance > 5) & (np.abs(error) <= ERROR_DEG)


def signal_counts(particles, candidates, device='cpu', particle_chunk=65536, candidate_chunk=16):
    """Chunked CPU or actual Torch CUDA evaluation. At most chunk_P x chunk_C pairs."""
    if device == 'cpu':
        counts = np.zeros(len(candidates))
        for first in range(0, len(particles), particle_chunk):
            p = particles[first:first+particle_chunk]
            direction = np.c_[np.cos(p[:, 2]), np.sin(p[:, 2])]
            for j, s in enumerate(candidates):
                d = s-p[:, :2]
                counts[j] += np.count_nonzero((np.sum(d*d, axis=1) <= p[:, 3]**2)
                    & ((p[:, 4] == 0) | (np.sum(d*direction, axis=1) >= 0)))
        return counts
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA requested but this Python has no usable CUDA runtime')
    if candidate_chunk is None:
        free_bytes, _ = torch.cuda.mem_get_info(device)
        candidate_chunk = max(8, min(32, int(free_bytes*0.05/(particle_chunk*32))))
    counts = torch.zeros(len(candidates), dtype=torch.int64, device=device)
    with torch.inference_mode():
        for first in range(0, len(particles), particle_chunk):
            p = torch.as_tensor(particles[first:first+particle_chunk], dtype=torch.float32, device=device)
            direction = torch.stack((torch.cos(p[:, 2]), torch.sin(p[:, 2])), dim=1)
            for j in range(0, len(candidates), candidate_chunk):
                s = torch.as_tensor(candidates[j:j+candidate_chunk], dtype=torch.float32, device=device)
                d = s[None, :, :] - p[:, None, :2]
                signal = (torch.sum(d*d, dim=2) <= p[:, 3, None]**2) & (
                    (p[:, 4, None] == 0) | (torch.sum(d*direction[:, None, :], dim=2) >= 0))
                counts[j:j+len(s)] += signal.sum(dim=0)
    return counts.cpu().numpy()


class Hypotheses:
    def __init__(self, seed=0, count=16384, device='cpu', use_negative=True):
        self.rng = np.random.default_rng(seed)
        self.count, self.device, self.use_negative = count, device, use_negative
        self.p = np.empty((0, 5))
        self.history = []

    def update(self, poly, observation):
        self.history.append(observation)
        if self.use_negative or observation[1] != 'no_signal':
            self.p = self.p[feasible(self.p, observation)]
        if len(self.p) >= 256:
            return
        # Re-propose spatially from the current OUTER polygon; replay ALL retained history.
        for _ in range(3):
            xy = sample_poly(poly, self.count, self.rng)
            p = np.c_[xy, self.rng.uniform(-np.pi, np.pi, self.count),
                      self.rng.uniform(1000, 1500, self.count), self.rng.integers(0, 2, self.count)]
            p = p[np.linalg.norm(p[:, :2], axis=1) <= 1800]
            for obs in self.history:
                if self.use_negative or obs[1] != 'no_signal':
                    p = p[feasible(p, obs)]
            self.p = np.vstack((self.p, p))
            if len(self.p) >= 256:
                break

    def next(self, poly, current):
        candidates = candidate_views(poly, current)
        if not len(self.p):
            return candidates[0]
        counts = signal_counts(self.p, candidates, self.device)
        probability = counts/max(1, len(self.p))
        # Binary outcomes alone miss the information carried by the bearing itself.
        _, records = next_view(poly,current,candidates=candidates)
        uncertainty = np.array([row[2] for row in records])
        old_d = max(diameter(poly)[0],1e-6)
        gain = probability*np.maximum(0,1-uncertainty/old_d) + 0.15*2*probability*(1-probability)
        cost = np.linalg.norm(candidates-current, axis=1)/5+5
        return candidates[np.argmax(gain/cost)]
