"""Optional permutations of existing discovery obligations; no truth or pruning."""
import numpy as np
from geometry import route


def refresh_remaining_route(nodes, current):
    """Keep the shorter complete open route from this same current position.

    This is a planned-route comparison, not a guarantee for the executed prefix
    or for a run interrupted by localization. Every original node is retained.
    """
    if not len(nodes):
        return []
    points = np.asarray(nodes, dtype=float)
    candidate = route(points, current)
    # Reuse the existing route optimizer, rather than add a second TSP solver.
    def distance(path):
        return float(np.linalg.norm(path[0]-current) + np.linalg.norm(np.diff(path, axis=0), axis=1).sum())
    return list(candidate if distance(candidate) < distance(points)-1e-8 else points)


def unknown_first(channels, tracks):
    """Keep the current channel first, then stably prioritize unseen channels.

    Cleared channels are skipped by the existing caller. This only permutes its
    list, and does not infer that any unseen channel contains a target.
    """
    return channels[:1]+[c for c in channels[1:] if c not in tracks]+[c for c in channels[1:] if c in tracks]


def workload_remaining_route(nodes, current, tracks):
    """Score D1's SAME two routes with a first-future-signal retirement proxy.

    Signal is not clearance. This heuristic neither removes obligations nor
    estimates calibrated clearance probabilities. Particle state is read only.
    """
    import hashlib
    from particles import feasible

    points = np.asarray(nodes, dtype=float).reshape(-1, 2)
    if not len(points):
        return [], None
    refreshed = route(points, current)
    lookup = {tuple(p): i for i, p in enumerate(points)}
    order = np.array([lookup[tuple(p)] for p in refreshed], dtype=int)
    paths = (points, refreshed)
    movement = np.array([np.linalg.norm(p[0]-current)+np.linalg.norm(np.diff(p, axis=0), axis=1).sum()
                         for p in paths])
    distance_choice = int(movement[1] < movement[0]-1e-8)
    workload = np.zeros(2)
    supports = []
    n = len(points)
    scan_counts = np.minimum(np.arange(n+1)+1, n)
    for channel, track in sorted(tracks.items()):
        hyp = track.get('hyp')
        if hyp is None or not len(hyp.p):
            continue
        particles = hyp.p
        masks = np.array([~feasible(particles, (p, 'no_signal', None)) for p in points])
        histograms = []
        for index, mask in enumerate((masks, masks[order])):
            first = np.where(mask.any(axis=0), mask.argmax(axis=0), n)
            histogram = np.bincount(first, minlength=n+1)
            workload[index] += 6*float(histogram @ scan_counts)/len(particles)
            histograms.append(histogram.tolist())
        supports.append(dict(channel=int(channel), particle_count=len(particles),
                             particle_sha256=hashlib.sha256(particles.tobytes()).hexdigest(),
                             first_hit_counts=histograms))
    scores = movement/5+workload
    other = 1-distance_choice
    selected = (other if workload[other] < workload[distance_choice]-1e-8
                and scores[other] < scores[distance_choice]-1e-8 else distance_choice)
    event = dict(start=np.asarray(current).tolist(), cached_nodes=points.tolist(), refreshed_order=order.tolist(),
                 movement_s=(movement/5).tolist(), workload_s=workload.tolist(), score_s=scores.tolist(),
                 distance_choice=distance_choice, selected_choice=selected, supports=supports)
    return list(paths[selected]), event
