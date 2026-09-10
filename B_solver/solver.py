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
    def __init__(self, client, mixed=False, policy='P3', device='cpu', particles=16384, use_negative=True, schedule=True):
        self.api, self.mixed, self.policy = client, mixed, policy
        self.device, self.particles, self.use_negative = device, particles, use_negative
        self.schedule = schedule
        self.tracks, self.cleared = {}, set()
        self.history = {c: [] for c in range(1,21)}
        self.observations, self.fallbacks, self.certified = 0, 0, 0

    def clear(self, c, p, certified=False):
        response = self.api.action('/clear', p, int(c))
        if response['clear_result'] == 'success':
            self.cleared.add(c)
            self.tracks.pop(c, None)
            self.certified += int(certified)
            return True
        if certified:
            raise RuntimeError('Certified clear failed: inspect geometry/protocol, do not silently discard source')
        return False

    def measure(self, c, p):
        p = np.asarray(p)
        response = self.api.action('/measure', p, int(c))
        result, angle = response['measure_result'], response.get('svd_deg')
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

    def localize(self, c, one_step=False):
        steps = 0
        while c in self.tracks:
            track = self.tracks[c]
            center, radius = mec(track['poly'])
            if radius <= 19.999:
                self.clear(c, center, certified=True)
                return
            if self.policy == 'P0' or track['n'] >= 8 or track['negatives'] >= 3:
                self.fallbacks += 1
                points = optical_grid(track['poly'])
                # Fixed distance ordering avoids quadratic TSP on the optical fallback.
                local_order = np.argsort(np.linalg.norm(points-self.api.position, axis=1))
                for i in local_order:
                    if self.clear(c, points[i]):
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
    p.add_argument('--output', default='B_solver/results/run.json')
    args = p.parse_args()
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.mode == 'practice' and not args.robot_id:
        p.error('--robot-id is required for an already-open PRACTICE session')
    api = Client(args.robot_id, out.with_suffix('.jsonl')) if args.mode=='practice' else LocalSimulator(args.seed,args.problem==4)
    solver = Solver(api,args.problem==4,args.policy or ('P4' if args.problem==4 else 'P3'),args.device,args.particles)
    result = solver.run()
    result['evidence'] = 'official_practice' if args.mode=='practice' else 'synthetic_local'
    if isinstance(api,LocalSimulator):
        result.update(total=len(api.sources),clear_rate=len(api.cleared)/len(api.sources),sources=api.sources,log=api.log)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('sources','log')},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
