"""Online policy: observations only; no access to hidden source data."""
import argparse
import json
import time
from pathlib import Path
import numpy as np
from geometry import disk, wedge, intersect_disk, mec, diameter, coverage, route, next_view, optical_grid
from particles import Hypotheses
from simulator import Client, LocalSimulator


class Solver:
    def __init__(self, client, mixed=False, policy='P3', device='cpu', particles=16384, use_negative=True, schedule=True, diagnostic=None):
        self.api, self.mixed, self.policy = client, mixed, policy
        self.device, self.particles, self.use_negative = device, particles, use_negative
        self.schedule = schedule
        self.diagnostic = diagnostic or {}
        self.clearance_point = self.diagnostic.get('clearance_point', 'mec_center')
        if self.clearance_point not in ('mec_center', 'nccp'):
            raise ValueError('clearance_point must be mec_center or nccp')
        self.trace = {}
        self.tracks, self.cleared = {}, set()
        self.history = {c: [] for c in range(1,21)}
        self.observations, self.fallbacks, self.certified = 0, 0, 0

    def target_trace(self, c):
        return self.trace.setdefault(c, dict(channel=int(c), first_seen_position=None, first_seen_time=None,
            num_direction_obs=0, num_no_signal_obs=0, num_near_obs=0, geometry_history=[],
            candidate_choices=[], movement_distance=0., fallback_trigger_reason=[], diagnostic_count=0,
            diagnostic_decisions=[], optical_grid_points=0, optical_clear_attempts=0,
            clear_attempts=0, clear_time=0., success=False))

    def clear_certified_polygon(self, c, center, radius):
        """Change only the final certified landing point; preserve the trigger.

        The measured saving is relative to the MEC center at THIS state. A new
        landing point can alter future actions, so it is not a whole-run bound.
        Near-observation clears use their original zero-movement path instead.
        """
        poly = self.tracks[c]['poly']
        start = np.asarray(self.api.position, dtype=float).copy()
        center = np.asarray(center, dtype=float)
        limit = 19.999
        if not np.isfinite(radius) or radius > limit:
            raise RuntimeError('Polygon clearance requires the existing MEC certificate')
        if self.clearance_point == 'nccp':
            from geometry import nearest_certified_clear_point
            point, selection = nearest_certified_clear_point(
                poly, start, clearance_radius=limit, mec_center=center, mec_radius=radius)
        else:
            point, selection = center, {'mode': 'mec_center', 'fallback': False}
        point = np.asarray(point, dtype=float)
        worst = float(np.max(np.linalg.norm(poly-point, axis=1)))
        distance = float(np.linalg.norm(point-start))
        mec_distance = float(np.linalg.norm(center-start))
        if not np.isfinite(point).all() or worst > limit or distance > mec_distance:
            raise RuntimeError('Clearance landing point failed strict distance audit')
        before = self.api.virtual_time
        event = dict(selector=self.clearance_point, start=start.tolist(), polygon=poly.tolist(),
                     mec_center=center.tolist(), mec_radius=float(radius), point=point.tolist(),
                     clearance_radius=limit, max_vertex_distance=worst, travel_m=distance,
                     mec_travel_m=mec_distance, same_state_saving_m=mec_distance-distance,
                     zero_move=bool(distance == 0.), selection=selection, time_before=before)
        self.target_trace(c).setdefault('certified_clearance_events', []).append(event)
        success = self.clear(c, point, certified=True)
        event.update(success=bool(success), time_after=self.api.virtual_time)
        return success

    def clear(self, c, p, certified=False):
        log = self.target_trace(c)
        log['movement_distance'] += float(np.linalg.norm(p-self.api.position))
        before = self.api.virtual_time
        response = self.api.action('/clear', p, int(c))
        log['clear_attempts'] += 1
        log['clear_time'] += self.api.virtual_time-before
        if response['clear_result'] == 'success':
            self.cleared.add(c)
            self.tracks.pop(c, None)
            self.certified += int(certified)
            log['success'] = True
            return True
        if certified:
            raise RuntimeError('Certified clear failed: inspect geometry/protocol, do not silently discard source')
        return False

    def measure(self, c, p):
        p = np.asarray(p)
        log = self.target_trace(c)
        log['movement_distance'] += float(np.linalg.norm(p-self.api.position))
        response = self.api.action('/measure', p, int(c))
        result, angle = response['measure_result'], response.get('svd_deg')
        log['num_'+result+'_obs'] += 1
        log['candidate_choices'].append(dict(point=p.tolist(), result=result, time=self.api.virtual_time))
        if result != 'no_signal' and log['first_seen_position'] is None:
            log['first_seen_position'], log['first_seen_time'] = p.tolist(), self.api.virtual_time
        self.history[c].append((p.copy(),result,angle))
        if result == 'near':
            self.clear(c, p, certified=True)
            return
        if result == 'direction':
            track = self.tracks.setdefault(c, dict(poly=disk(), n=0, negatives=0, views=[], hyp=None))
            poly = wedge(track['poly'], p, angle)
            poly = intersect_disk(poly, p, 1500)
            if not len(poly):
                raise RuntimeError(f'Empty set on channel {c}; observation/model inconsistency')
            track['poly'], track['n'] = poly, track['n']+1
            track['negatives'] = 0
            track['views'].append(p.copy())
            self.observations += 1
        if c in self.tracks:
            track = self.tracks[c]
            track['negatives'] += int(result == 'no_signal')
            if self.mixed and self.policy == 'P4':
                if track['hyp'] is None:
                    track['hyp'] = Hypotheses(c, self.particles, self.device, self.use_negative)
                    track['hyp'].history = list(self.history[c][:-1])
                track['hyp'].update(track['poly'], (p.copy(), result, angle))
            log['geometry_history'].append(dict(time=self.api.virtual_time, diameter=diameter(track['poly'])[0],
                mec_radius=mec(track['poly'])[1], particle_count=len(track['hyp'].p) if track['hyp'] else 0))

    def localize(self, c, one_step=False):
        steps = 0
        while c in self.tracks:
            track = self.tracks[c]
            center, radius = mec(track['poly'])
            if radius <= 19.999:
                self.clear_certified_polygon(c, center, radius)
                return
            if self.policy == 'P0' or track['n'] >= 8 or track['negatives'] >= 3:
                log = self.target_trace(c)
                log['fallback_trigger_reason'].append('policy_P0' if self.policy == 'P0' else
                    'direction_limit' if track['n'] >= 8 else 'consecutive_no_signal')
                if self.mixed and self.policy == 'P4' and self.diagnostic.get('enabled'):
                    from directional.diagnostic_recovery import recover
                    if recover(self, c, self.diagnostic):
                        return
                    track = self.tracks[c]
                self.fallbacks += 1
                from directional.fallback_cost import ordered_grid
                points = ordered_grid(track['poly'], self.api.position, self.diagnostic.get('local_order', False),
                                      grid_version=self.diagnostic.get('grid_version', 'grid_v0'))
                log['optical_grid_points'] += len(points)
                for point in points:
                    log['optical_clear_attempts'] += 1
                    if self.clear(c, point):
                        return
                raise RuntimeError(f'Optical coverage exhausted but channel {c} not cleared')
            if self.policy in ('P2', 'P3'):
                point, _ = next_view(track['poly'], self.api.position)
            elif self.policy == 'P4' and track['hyp'] is not None:
                point = track['hyp'].next(track['poly'], self.api.position)
            else:
                # Baseline geometric side-step, scaled to the current uncertainty.
                _, a, b = diameter(track['poly'])
                u = (b-a)/max(1e-9,np.linalg.norm(b-a))
                point = center + max(25.,min(radius*0.25,150.))*np.array([-u[1],u[0]])
            if any(np.linalg.norm(point-old)<0.1 for old in track['views']):
                point = center + np.array([25., 25.])
            self.measure(c, point)
            steps += 1
            if one_step and steps >= 1:
                return

    def run(self):
        start = time.perf_counter()
        self.api.action('/enter')
        nodes = list(route(coverage(self.mixed), self.api.position))
        while nodes or self.tracks:
            # Candidate clearing/localization costs compete with the next discovery sweep.
            choices = []
            for c, track in self.tracks.items():
                center, radius = mec(track['poly'])
                choices.append((np.linalg.norm(center-self.api.position)/5 + (5 if radius<=19.999 else 20+radius/5), c))
            local = min(choices) if choices else (float('inf'), None)
            explore = np.linalg.norm(nodes[0]-self.api.position)/5 + (20-len(self.cleared))*6 if nodes else float('inf')
            if not self.schedule:
                explore = float('inf')
            if local[1] is not None and (not nodes or local[0] <= explore):
                self.localize(local[1], one_step=self.policy in ('P3','P4'))
                continue
            p = nodes.pop(0)
            channels = [self.api.channel]+[c for c in range(1,21) if c != self.api.channel]
            for c in channels:
                if c in self.cleared:
                    continue
                self.measure(c, p)
                if c in self.tracks and self.policy in ('P0','P1','P2'):
                    self.localize(c)
            if nodes and self.policy in ('P3','P4'):
                nodes = list(route(np.asarray(nodes), self.api.position))
        self.api.action('/exit')
        return dict(policy=self.policy, mixed=self.mixed, cleared=len(self.cleared),
                    virtual_time_s=self.api.virtual_time,
                    mean_time_per_source_s=self.api.virtual_time/max(1,len(self.cleared)),
                    runtime_s=time.perf_counter()-start, localization_observations=self.observations,
                    optical_fallbacks=self.fallbacks, certified_clears=self.certified)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--mode', choices=['local','practice'], default='local')
    p.add_argument('--problem', type=int, choices=[3,4], default=3)
    p.add_argument('--policy', choices=['P0','P1','P2','P3','P4'])
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--device', default='cpu')
    p.add_argument('--particles', type=int, default=16384)
    p.add_argument('--robot-id')
    p.add_argument('--config', help='JSON-compatible YAML diagnostic configuration; default preserves baseline')
    p.add_argument('--output', default='B_solver/results/run.json')
    args = p.parse_args()
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.mode == 'practice' and not args.robot_id:
        p.error('--robot-id is required for an already-open PRACTICE session')
    api = Client(args.robot_id, out.with_suffix('.jsonl')) if args.mode=='practice' else LocalSimulator(args.seed,args.problem==4)
    config = json.loads(Path(args.config).read_text()) if args.config else {}
    solver = Solver(api,args.problem==4,args.policy or ('P4' if args.problem==4 else 'P3'),args.device,args.particles,diagnostic=config)
    result = solver.run()
    result['evidence'] = 'official_practice' if args.mode=='practice' else 'synthetic_local'
    if isinstance(api,LocalSimulator):
        result.update(total=len(api.sources),clear_rate=len(api.cleared)/len(api.sources),sources=api.sources,log=api.log)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('sources','log')},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
