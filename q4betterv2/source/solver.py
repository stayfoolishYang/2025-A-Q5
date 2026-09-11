"""Online policy: observations only; no access to hidden source data."""
import argparse
import json
import time
from pathlib import Path
import numpy as np
from geometry import disk, wedge, intersect_disk, mec, diameter, coverage, route, next_view, optical_grid
from particles import Hypotheses
from simulator import Client, LocalSimulator

PUBLIC_MAX_SOURCES = 16


class Solver:
    def __init__(self, client, mixed=False, policy='P3', device='cpu', particles=16384, use_negative=True, schedule=True, diagnostic=None):
        self.api, self.mixed, self.policy = client, mixed, policy
        self.device, self.particles, self.use_negative = device, particles, use_negative
        self.schedule = schedule
        self.diagnostic = diagnostic or {}
        self.failure_context_repair = self.diagnostic.get('failure_context_repair', False)
        if type(self.failure_context_repair) is not bool:
            raise ValueError('failure_context_repair must be boolean')
        if self.failure_context_repair and (not mixed or policy != 'P4'):
            raise ValueError('Failure context repair requires mixed Q4/P4')
        self.local_no_signal_streak = {c: 0 for c in range(1, 21)}
        self.measurement_purpose = 'localization'
        self.stop_after_public_max_clear = self.diagnostic.get('stop_after_public_max_clear', False)
        self.finish_after_public_max_known = self.diagnostic.get('finish_after_public_max_known', False)
        if type(self.finish_after_public_max_known) is not bool:
            raise ValueError('finish_after_public_max_known must be boolean')
        self.confirmed = set()
        self.known16_trigger = None
        self.discovery_coverage = self.diagnostic.get('discovery_coverage', 'legacy45')
        if type(self.stop_after_public_max_clear) is not bool:
            raise ValueError('stop_after_public_max_clear must be boolean')
        if self.discovery_coverage not in ('legacy45', 'certified37', 'certified25'):
            raise ValueError('Unknown discovery_coverage')
        if (self.finish_after_public_max_known or self.stop_after_public_max_clear or self.discovery_coverage != 'legacy45') and (not mixed or policy != 'P4'):
            raise ValueError('Public-max and coverage experiments require mixed Q4/P4')
        self.clearance_point = self.diagnostic.get('clearance_point', 'mec_center')
        if self.clearance_point not in ('mec_center', 'nccp', 'segment_entry'):
            raise ValueError('clearance_point must be mec_center, nccp or segment_entry')
        self.discovery_route = self.diagnostic.get('discovery_route', 'legacy')
        self.discovery_channels = self.diagnostic.get('discovery_channels', 'legacy')
        if self.discovery_route not in ('legacy', 'refresh_after_localize', 'workload_after_localize'):
            raise ValueError('Unknown discovery_route')
        if self.discovery_channels not in ('legacy', 'unknown_first'):
            raise ValueError('Unknown discovery_channels')
        if (not mixed or policy != 'P4') and (self.discovery_route != 'legacy' or self.discovery_channels != 'legacy'):
            raise ValueError('Discovery scheduling experiments require mixed Q4/P4')
        self.trace = {}
        self.tracks, self.cleared = {}, set()
        self.history = {c: [] for c in range(1,21)}
        self.observations, self.fallbacks, self.certified = 0, 0, 0

    def public_max_complete(self):
        if self.stop_after_public_max_clear and len(self.cleared) > PUBLIC_MAX_SOURCES:
            raise RuntimeError('Successful channels exceed the public source maximum')
        if self.stop_after_public_max_clear and len(self.cleared) == PUBLIC_MAX_SOURCES and self.tracks:
            raise RuntimeError('Uncleared observed source contradicts the public source maximum')
        return self.stop_after_public_max_clear and len(self.cleared) == PUBLIC_MAX_SOURCES

    def confirm_channel(self, c):
        self.confirmed.add(c)
        if self.finish_after_public_max_known and len(self.confirmed) > PUBLIC_MAX_SOURCES:
            raise RuntimeError('Confirmed channels exceed public maximum')
        if self.finish_after_public_max_known and len(self.confirmed) == PUBLIC_MAX_SOURCES and self.known16_trigger is None:
            self.known16_trigger = dict(time_s=self.api.virtual_time, cleared=len(self.cleared),
                                       unresolved=len(self.confirmed-self.cleared), channels=sorted(self.confirmed))

    def release_discovery(self, nodes):
        if self.known16_trigger is not None:
            nodes.clear()
            if not self.tracks and len(self.cleared) < PUBLIC_MAX_SOURCES:
                raise RuntimeError('Known16 but unresolved channels have no tracks')

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
        from geometry import is_certified_clear_point, exact_squared_distance

        def unavailable(reason):
            self.target_trace(c).setdefault('certificate_failures', []).append(
                dict(reason=reason, selector=self.clearance_point, time=self.api.virtual_time))
            return False

        try:
            poly = np.asarray(self.tracks[c]['poly'], dtype=float)
            start = np.asarray(self.api.position, dtype=float).copy()
            center, radius = np.asarray(center, dtype=float), float(radius)
        except (KeyError, TypeError, ValueError):
            return unavailable('invalid_certificate_inputs')
        limit = 19.999
        if poly.ndim != 2 or poly.shape[1] != 2 or not len(poly) or not np.isfinite(poly).all():
            return unavailable('invalid_hard_polygon')
        if start.shape != (2,) or not np.isfinite(start).all():
            return unavailable('invalid_robot_position')
        if not np.isfinite(radius) or not 0 <= radius <= limit:
            return unavailable('invalid_mec_radius')
        if not is_certified_clear_point(poly, center, radius):
            return unavailable('invalid_mec_certificate')
        mec_distance = float(np.linalg.norm(center-start))
        if not np.isfinite(mec_distance):
            return unavailable('invalid_mec_travel_distance')
        baseline_squared = exact_squared_distance(start, center)

        def checked_submission(candidate):
            candidate = np.asarray(candidate, dtype=float)
            if candidate.shape != (2,):
                raise ValueError('Invalid selector point shape')
            # Match Client.action's float -> JSON x/y -> parsed coordinate path.
            wire = json.loads(json.dumps(dict(x=float(candidate[0]), y=float(candidate[1])), allow_nan=False))
            point = np.array([wire['x'], wire['y']], dtype=float)
            if (not is_certified_clear_point(poly, point, limit)
                    or float(np.linalg.norm(point-start)) > mec_distance
                    or exact_squared_distance(point, start) > baseline_squared):
                raise ValueError('Submitted point failed strict clearance/travel audit')
            return point

        point, selection = center, {'mode': 'mec_center', 'fallback': False}
        try:
            if self.clearance_point != 'mec_center':
                from geometry import nearest_certified_clear_point, segment_certified_clear_point
                selector = nearest_certified_clear_point if self.clearance_point == 'nccp' else segment_certified_clear_point
                point, selection = selector(poly, start, clearance_radius=limit, mec_center=center, mec_radius=radius)
                if not isinstance(selection, dict):
                    raise ValueError('Invalid selector metadata')
            point = checked_submission(point)
        except (TypeError, ValueError, ArithmeticError, np.linalg.LinAlgError, RuntimeError) as error:
            if self.clearance_point == 'mec_center':
                return unavailable('no_verified_submission_point')
            selection = dict(mode='mec_fallback', fallback=True,
                             fallback_reason=f'{type(error).__name__}: {error}')
            # This capture ends before clear(): an unresolved HTTP operation
            # must propagate, never be retried as another clearance action.
            try:
                point = checked_submission(center)
            except (TypeError, ValueError, ArithmeticError):
                return unavailable('no_verified_submission_point')
        worst = float(np.max(np.linalg.norm(poly-point, axis=1)))
        distance = float(np.linalg.norm(point-start))
        before = self.api.virtual_time
        verification = ('MEC_FALLBACK' if selection.get('fallback') else
                        'NCCP_CANDIDATE_VERIFIED' if self.clearance_point == 'nccp' else
                        'SEGMENT_ENTRY_VERIFIED' if self.clearance_point == 'segment_entry' else 'MEC_CENTER_VERIFIED')
        event = dict(selector=self.clearance_point, start=start.tolist(), polygon=poly.tolist(),
                     mec_center=center.tolist(), mec_radius=float(radius), point=point.tolist(),
                     clearance_radius=limit, max_vertex_distance=worst, travel_m=distance,
                     mec_travel_m=mec_distance, same_state_saving_m=mec_distance-distance,
                     zero_move=bool(distance == 0.), selection=selection, time_before=before,
                     verification_status=verification, submitted_position=dict(x=float(point[0]), y=float(point[1])),
                     json_roundtrip_verified=True)
        self.target_trace(c).setdefault('certified_clearance_events', []).append(event)
        success = self.clear(c, point, certified=True)
        event.update(success=bool(success), time_after=self.api.virtual_time)
        return success

    def clear(self, c, p, certified=False):
        if self.public_max_complete():
            raise RuntimeError('Clear attempted after public-max completion')
        log = self.target_trace(c)
        log['movement_distance'] += float(np.linalg.norm(p-self.api.position))
        before = self.api.virtual_time
        response = self.api.action('/clear', p, int(c))
        if response.get('accepted') is not True:
            raise RuntimeError('Rejected clear response')
        log['clear_attempts'] += 1
        log['clear_time'] += self.api.virtual_time-before
        if response['clear_result'] == 'success':
            self.cleared.add(c)
            self.confirm_channel(c)
            self.tracks.pop(c, None)
            self.certified += int(certified)
            log['success'] = True
            return True
        if certified:
            raise RuntimeError('Certified clear failed: inspect geometry/protocol, do not silently discard source')
        return False

    def measure_discovery(self, c, p):
        # Business purpose belongs to the policy, not an optional audit adapter.
        previous = self.measurement_purpose
        self.measurement_purpose = 'discovery'
        try:
            return self.measure(c, p)
        finally:
            self.measurement_purpose = previous

    def measure(self, c, p):
        if self.public_max_complete():
            raise RuntimeError('Measure attempted after public-max completion')
        p = np.asarray(p)
        log = self.target_trace(c)
        log['movement_distance'] += float(np.linalg.norm(p-self.api.position))
        response = self.api.action('/measure', p, int(c))
        if response.get('accepted') is not True:
            raise RuntimeError('Rejected measure response')
        if response.get('measure_result') in ('direction', 'near'):
            self.confirm_channel(c)
        result, angle = response['measure_result'], response.get('svd_deg')
        if self.failure_context_repair:
            before_streak = self.local_no_signal_streak[c]
            if result in ('direction', 'near'):
                self.local_no_signal_streak[c] = 0
            elif result == 'no_signal' and self.measurement_purpose != 'discovery':
                self.local_no_signal_streak[c] += 1
            log.setdefault('failure_counter_events', []).append(dict(
                purpose=self.measurement_purpose, result=result, time_s=self.api.virtual_time,
                before=before_streak, after=self.local_no_signal_streak[c]))
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
            if radius <= 19.999 and self.clear_certified_polygon(c, center, radius):
                return
            failures = self.local_no_signal_streak[c] if self.failure_context_repair else track['negatives']
            if self.policy == 'P0' or track['n'] >= 8 or failures >= 3:
                log = self.target_trace(c)
                log['fallback_trigger_reason'].append('policy_P0' if self.policy == 'P0' else
                    'direction_limit' if track['n'] >= 8 else
                    'local_no_signal_streak' if self.failure_context_repair else 'consecutive_no_signal')
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
        nodes = list(route(coverage(self.mixed, version=self.discovery_coverage), self.api.position))
        while (nodes or self.tracks) and not self.public_max_complete():
            self.release_discovery(nodes)
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
                if self.public_max_complete():
                    break
                self.release_discovery(nodes)
                if nodes and self.discovery_route == 'refresh_after_localize':
                    from discovery import refresh_remaining_route
                    nodes = refresh_remaining_route(nodes, self.api.position)
                if nodes and self.discovery_route == 'workload_after_localize':
                    from discovery import workload_remaining_route
                    nodes, event = workload_remaining_route(nodes, self.api.position, self.tracks)
                    self.target_trace(local[1]).setdefault('discovery_refresh_events', []).append(event)
                continue
            p = nodes.pop(0)
            channels = [self.api.channel]+[c for c in range(1,21) if c != self.api.channel]
            if self.discovery_channels == 'unknown_first':
                from discovery import unknown_first
                channels = unknown_first(channels, self.tracks)
            for c in channels:
                if c in self.cleared:
                    continue
                self.measure_discovery(c, p)
                if self.public_max_complete():
                    break
                if self.known16_trigger is not None:
                    self.release_discovery(nodes)
                    break
                if c in self.tracks and self.policy in ('P0','P1','P2'):
                    self.localize(c)
            if self.public_max_complete():
                break
            if nodes and self.policy in ('P3','P4'):
                nodes = list(route(np.asarray(nodes), self.api.position))
        self.release_discovery(nodes)
        self.api.action('/exit')
        return dict(policy=self.policy, mixed=self.mixed, cleared=len(self.cleared),
                    virtual_time_s=self.api.virtual_time,
                    mean_time_per_source_s=self.api.virtual_time/max(1,len(self.cleared)),
                    runtime_s=time.perf_counter()-start, localization_observations=self.observations,
                    optical_fallbacks=self.fallbacks, certified_clears=self.certified,
                    completion_reason='public_max_cleared' if self.public_max_complete() else 'coverage_exhausted')


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
