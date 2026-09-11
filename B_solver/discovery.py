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
