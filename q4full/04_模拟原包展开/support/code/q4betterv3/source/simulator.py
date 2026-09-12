"""Offline reference environment and official four-endpoint client."""
import hashlib
import json
import math
import time
import uuid
from http.client import HTTPException
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import numpy as np


class Client:
    def __init__(self, robot_id, log_path, base_url='http://127.0.0.1:2026'):
        if not robot_id or len(robot_id.encode('utf-8')) > 64:
            raise ValueError('Invalid team identifier')
        self.robot_id, self.base_url = robot_id, base_url.rstrip('/')
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.position, self.channel = np.zeros(2), 1
        self.virtual_time = 0.
        self.deadline = math.inf
        self.started = False
        self.log = []
        self.stage = 'discovery'
        self.distance, self.measures, self.switches, self.clear_attempts = 0., 0, 0, 0

    def action(self, path, position=None, channel=None):
        if path not in ('/enter', '/measure', '/clear', '/exit'):
            raise ValueError('Unknown protocol endpoint')
        if time.monotonic() >= self.deadline - 3 and path != '/exit':
            raise TimeoutError('Remaining real-time budget exhausted')
        payload = dict(arena_id='default', robot_id=self.robot_id, request_id=uuid.uuid4().hex)
        if position is not None:
            p = np.asarray(position, dtype=float)
            if p.shape != (2,) or not np.isfinite(p).all() or abs(p).max() > 2000000:
                raise ValueError('Invalid coordinate')
            if isinstance(channel, bool) or not isinstance(channel, (int, np.integer)) or not 1 <= channel <= 20:
                raise ValueError('Invalid channel')
            payload.update(position=dict(x=float(p[0]), y=float(p[1])), channel=int(channel))
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
        request = Request(self.base_url+path, data=data, headers={'Content-Type':'application/json'}, method='POST')
        for attempt in range(3):
            try:
                with urlopen(request, timeout=5) as response:
                    status, result = response.status, json.load(response)
                break
            except HTTPError as error:
                self._log(path, payload, {'http_error': error.code})
                raise RuntimeError(f'HTTP {error.code}; action state must be inspected') from error
            except (URLError, TimeoutError, ConnectionError, OSError, HTTPException) as error:
                self._log(path, payload, {'network_error':str(error), 'attempt':attempt+1})
                if attempt == 2:
                    raise
                time.sleep(0.2*(attempt+1))  # same serialized body and request_id, never a new action.
        self._log(path, payload, result)
        if status != 200 or result.get('accepted') is not True:
            raise RuntimeError(f'Rejected {path}: {result}')
        virtual_time = float(result['virtual_time_s'])
        if not math.isfinite(virtual_time) or virtual_time < self.virtual_time-1e-6:
            raise RuntimeError('Invalid virtual time in accepted response')
        if path == '/measure':
            if result.get('measure_result') not in ('direction','near','no_signal'):
                raise RuntimeError('Invalid measurement result')
            if result['measure_result']=='direction' and not math.isfinite(float(result.get('svd_deg',float('nan')))):
                raise RuntimeError('Missing or nonfinite bearing')
        if path == '/clear' and result.get('clear_result') not in ('success','no_target_in_range'):
            raise RuntimeError('Invalid clear result')
        if path == '/enter' and not 0 < result.get('remaining_real_duration_s',0) <= 1200:
            raise RuntimeError('Invalid remaining real-time budget')
        old_position, old_channel, old_time = self.position.copy(), self.channel, self.virtual_time
        self.virtual_time = virtual_time
        if position is not None:
            self.position = p
        if path == '/measure':
            self.channel = int(channel)
        if path == '/enter':
            self.started = True
            self.deadline = time.monotonic() + result['remaining_real_duration_s']
        if path == '/exit':
            self.started = False
        travel = 0. if position is None else float(np.linalg.norm(p-old_position))
        self.distance += travel
        if path == '/measure':
            self.measures += 1
            self.switches += int(int(channel) != old_channel)
        if path == '/clear':
            self.clear_attempts += 1
        # CT's BridgeFacade reads and annotates one entry per accepted action.
        # Retries are wire diagnostics only and must not create extra actions.
        self.log.append(dict(path=path, position=None if position is None else p.tolist(),
                             channel=None if channel is None else int(channel),
                             response=result, stage=self.stage, travel_m=travel,
                             elapsed_s=virtual_time-old_time))
        return result

    def _log(self, path, request, response):
        with self.log_path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(dict(path=path, request=request, response=response), ensure_ascii=False)+'\n')


class LocalSimulator:
    """A documented synthetic environment, NOT the official simulator or its random generator."""
    def __init__(self, seed=0, mixed=False, stress='random', sources=None):
        self.seed, self.stress = seed, stress
        rng = np.random.default_rng(seed)
        n = int(rng.integers(10, 17))
        angle = rng.uniform(0, 2*np.pi, n)
        radius = 1800*np.sqrt(rng.random(n))
        if stress == 'edge':
            radius[:] = 1800
        if stress == 'cluster':
            radius = 500 + 30*rng.random(n)
            angle = 0.2 + 0.04*rng.random(n)
        self.sources = sources if sources is not None else {
            int(c): dict(position=[float(r*np.cos(a)), float(r*np.sin(a))], radius=float(rng.uniform(1000, 1500)),
                         direction=float(a if stress=='edge' else rng.uniform(-np.pi, np.pi)) if mixed and rng.random()<0.65 else None)
            for c, r, a in zip(rng.choice(np.arange(1,21), n, replace=False), radius, angle)}
        self.cleared = set()
        self.position, self.channel = np.zeros(2), 1
        self.virtual_time, self.distance, self.switches, self.measures, self.clear_attempts = 0., 0., 0, 0, 0
        self.started = False
        self.log = []
        self.deadline = math.inf

    def action(self, path, position=None, channel=None):
        if path == '/enter':
            if self.started:
                raise RuntimeError('Already entered')
            self.started = True
            return dict(accepted=True, virtual_time_s=0, remaining_real_duration_s=1200)
        if not self.started:
            raise RuntimeError('Not entered')
        result = dict(accepted=True)
        if path == '/exit':
            self.started = False
            result['exit_reason'] = 'user_exit'
        else:
            p = np.asarray(position, dtype=float)
            if p.shape != (2,) or not np.isfinite(p).all() or np.abs(p).max()>2000000 or not 1<=channel<=20:
                raise ValueError('Invalid action')
            travel = float(np.linalg.norm(p-self.position))
            self.distance += travel
            self.virtual_time += travel/5
            self.position = p.copy()
            source = self.sources.get(channel) if channel not in self.cleared else None
            d = np.asarray(source['position'])-p if source else np.array([math.inf, math.inf])
            dist = float(np.linalg.norm(d))
            if path == '/clear':
                self.clear_attempts += 1
                success = dist <= 20
                self.virtual_time += 5 if success else 3
                result['clear_result'] = 'success' if success else 'no_target_in_range'
                if success:
                    self.cleared.add(channel)
            elif path == '/measure':
                self.switches += int(channel != self.channel)
                self.virtual_time += 5 + int(channel != self.channel)
                self.channel = channel
                self.measures += 1
                visible = source is not None and dist <= source['radius']
                if visible and source['direction'] is not None:
                    phi = source['direction']
                    visible = float((-d) @ np.array([np.cos(phi),np.sin(phi)])) >= -1e-9
                result['measure_result'] = 'no_signal'
                if visible:
                    result['measure_result'] = 'near' if dist<=5 else 'direction'
                    if dist>5:
                        key = f'{self.seed}:{channel}:{p[0]:.9f}:{p[1]:.9f}'.encode()
                        # Spatially deterministic bounded errors, identical on repeat visits.
                        noise = int.from_bytes(hashlib.blake2b(key,digest_size=8).digest(),'little')/(2**64-1)*2-1
                        if self.stress == 'bias':
                            noise = 1. if channel%2 else -1.
                        result['svd_deg'] = round((np.rad2deg(np.arctan2(d[1],d[0]))+noise)%360,2)%360
            else:
                raise ValueError('Unknown endpoint')
        result['virtual_time_s'] = self.virtual_time
        self.log.append(dict(path=path, position=self.position.tolist(), channel=channel, response=result.copy()))
        if self.virtual_time > 360000:
            raise TimeoutError('Virtual time limit')
        return result
