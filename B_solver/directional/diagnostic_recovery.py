"""Sampled short-horizon planning. Hypothetical branches never modify real geometry."""
import numpy as np
from geometry import wedge, intersect_disk, diameter, ERROR_DEG
from particles import signal_counts, feasible
from directional.diagnostic_candidates import candidates
from directional.fallback_cost import estimate_optical_fallback_cost


def branches(poly, particles, point):
    """Empirical signal fraction and sampled noisy bearings; NOT a probability guarantee."""
    if len(particles):
        no = feasible(particles, (point, 'no_signal', None))
        p_signal = 1-float(no.mean())
        sig = particles[~no]
        if no.any():
            yield 1-p_signal, poly.copy(), particles[no]
        representatives = sig[np.linspace(0, len(sig)-1, min(3, len(sig))).astype(int), :2] if len(sig) else []
    else:
        # Exhausted hypotheses cannot establish absence or justify excluding no-signal.
        yield 0.5, poly.copy(), particles
        p_signal = 0.5
        representatives = poly[np.linspace(0, len(poly)-1, min(3, len(poly))).astype(int)]
    for x in representatives:
        bearing = np.rad2deg(np.arctan2(*(x-point)[::-1]))
        for error in (-ERROR_DEG, 0., ERROR_DEG):
            angle = bearing+error
            post = intersect_disk(wedge(poly, point, angle), point, 1500)
            if len(post):
                subset = particles[feasible(particles, (point, 'direction', angle))] if len(particles) else particles
                yield p_signal/(len(representatives)*3), post, subset


def choose(poly, particles, current, channel, target_channel, config, history=(), depth=None, device='cpu'):
    depth = config.get('depth', 1) if depth is None else depth
    pts = candidates(poly, current, history, config.get('offsets', [100,200,300,500,700]))
    if not len(pts):
        return None
    move = np.linalg.norm(pts-current, axis=1)/5+5+int(channel != target_channel)
    # CUDA screens particle/candidate pairs only; CPU FP64 reranks ALL candidates so
    # threshold disagreements cannot silently remove the true CPU best candidate.
    gpu_counts = signal_counts(particles, pts, device, candidate_chunk=None) if len(particles) else np.zeros(len(pts))
    counts = signal_counts(particles, pts, 'cpu') if device != 'cpu' and len(particles) else gpu_counts
    p = counts/len(particles) if len(particles) else np.full(len(pts), 0.5)
    mismatch = float(np.max(np.abs(counts-gpu_counts))) if len(pts) else 0.
    # Geometric angular diversity estimate cheaply screens beam candidates.
    _, a, b = diameter(poly)
    va, vb = a-pts, b-pts
    cross = abs(va[:,0]*vb[:,1]-va[:,1]*vb[:,0])
    angular = cross/np.maximum(np.linalg.norm(va,axis=1)*np.linalg.norm(vb,axis=1), 1e-9)
    split_weight = config.get('split_weight', 0.5)
    proxy = (split_weight*np.minimum(p,1-p)+(1-split_weight)*p*angular)/move
    width = config.get('beam_width', 4)
    ids = np.argsort(-proxy, kind='stable')[:width]
    records = []
    for i in ids:
        outcomes = list(branches(poly, particles, pts[i]))
        total = 0.
        for weight, post, subset in outcomes:
            terminal = estimate_optical_fallback_cost(post, pts[i], exact=False,
                         grid_version=config.get('grid_version', 'grid_v0'))
            total += weight*terminal
        # Limited beam over nominal continuation, then weighted into first-step outcomes.
        if depth > 1 and outcomes:
            selected = sorted(range(len(outcomes)), key=lambda j: -outcomes[j][0])[:2]
            for j in selected:
                weight, post, subset = outcomes[j]
                old = estimate_optical_fallback_cost(post, pts[i], exact=False,
                         grid_version=config.get('grid_version', 'grid_v0'))
                child = choose(post, subset, pts[i], target_channel, target_channel, config,
                               (*history, pts[i]), depth-1, device)
                if child:
                    total += weight*(min(old, child['estimated_cost'])-old)
        records.append(dict(point=pts[i].tolist(), estimated_cost=float(move[i]+total),
                            move_time=float(move[i]), signal_fraction=float(p[i]),
                            split=float(min(p[i],1-p[i])), proxy_score=float(proxy[i]),
                            gpu_count_max_difference=mismatch))
    best = dict(min(records, key=lambda r: r['estimated_cost']))
    best['candidate_scores'] = records
    best['depth'] = depth
    return best


def recover(solver, channel, config):
    log = solver.target_trace(channel)
    for _ in range(config.get('max_steps', 3)):
        if channel not in solver.tracks:
            return True
        track = solver.tracks[channel]
        from geometry import mec
        center, radius = mec(track['poly'])
        if radius <= 19.999:
            return solver.clear(channel, center, certified=True)
        p = track['hyp'].p if track['hyp'] is not None else np.empty((0,5))
        # Deterministic cap only for planning; retained full hypothesis history is untouched.
        p = p[np.linspace(0,len(p)-1,min(len(p),1024)).astype(int)] if len(p) else p
        plan = choose(track['poly'], p, solver.api.position, solver.api.channel, channel,
                      config, [o[0] for o in solver.history[channel]], device=solver.device)
        grid_cost = estimate_optical_fallback_cost(track['poly'], solver.api.position,
                          local=config.get('local_order', True),
                          grid_version=config.get('grid_version', 'grid_v0'))
        if plan is None or plan['estimated_cost'] >= config.get('alpha',1.0)*grid_cost:
            log['diagnostic_decisions'].append(dict(accepted=False, grid_cost=grid_cost, plan=plan))
            break
        # Detach record to avoid self-reference in candidate_scores.
        log['diagnostic_decisions'].append(dict(accepted=True, grid_cost=grid_cost, plan=plan))
        log['diagnostic_count'] += 1
        solver.measure(channel, np.asarray(plan['point']))
    if channel in solver.tracks:
        center, radius = mec(solver.tracks[channel]['poly'])
        if radius <= 19.999:
            return solver.clear(channel, center, certified=True)
    return channel not in solver.tracks
