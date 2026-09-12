"""Final Q4 21+R12+F+CT HTTP entry; sends nothing without --execute.

The operator must start the correct official module and verify its case code in
its UI. The robot API does not disclose that mode or the hidden source count.
Importing this module is inert; tests inject a mock URL transport.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlparse

os.environ.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'source'))
import numpy as np
import geometry
import solver
from simulator import Client
from ctspn import CTSolver


def verify_sources():
    expected = json.loads((ROOT/'SOURCE_SHA256.json').read_text(encoding='utf8'))
    for name, digest in expected.items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Source checksum changed: '+name)
    return expected


def build_solver(api):
    """Use the same 21-point substitution/configuration as the offline entry."""
    points = np.asarray(json.loads((ROOT/'points21.json').read_text())['points'])
    config = json.loads((ROOT/'config_21r12ctf.json').read_text())
    if points.shape != (21, 2) or not config['ctspn_enabled'] or not config['failure_context_repair']:
        raise ValueError('Expected frozen 21+R12+F+CT configuration')
    previous_g, previous_s = geometry.coverage, solver.coverage
    def coverage(mixed=False, ring=1130., *, version='legacy45'):
        return points.copy() if mixed and version == 'certified25' else previous_g(mixed, ring, version=version)
    geometry.coverage = solver.coverage = coverage
    instance = CTSolver(api, True, 'P4', device='cpu', diagnostic=config)
    return instance, config, (previous_g, previous_s)


def run_policy(api, output, *, case_code, mode):
    """Run on an injected Client-compatible object; mocks need no server."""
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Use a new or empty output directory")
    output.mkdir(parents=True, exist_ok=True)
    strategy, config, previous = build_solver(api)
    def save(name, value):
        (output/name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    save('manifest.json', dict(case_code=case_code, operator_declared_mode=mode,
         variant='21+R12+F+CT_geometry_revision', config=config,
         source_sha256=verify_sources(), full_clear_verified=False))
    started = time.perf_counter()
    try:
        result = strategy.run()
        result.update(case_code=case_code, operator_declared_mode=mode,
                      wall_time_s=time.perf_counter()-started,
                      full_clear_verified=False)
        if strategy.api.pending is not None:
            raise RuntimeError('Unconsumed CT bridge after completion')
        save('result.json', result)
        return result
    except Exception as error:
        save('error.json', dict(type=type(error).__name__, message=str(error),
             virtual_time_s=api.virtual_time, started=api.started))
        # Do not invent a new action after an uncertain network outcome.
        raise
    finally:
        save('actions.json', api.log)
        save('ct_events.json', strategy.ct_events)
        save('trace.json', strategy.trace)
        geometry.coverage, solver.coverage = previous


@contextmanager
def sender_lock(path):
    """Prevent two copies of this entry from submitting concurrent actions."""
    path = Path(path);path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open('a+b')
    try:
        stream.seek(0, 2)
        if stream.tell() == 0:stream.write(b'0');stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        stream.close()  # OS releases its lock; leave the inode stable.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--robot-id', required=True, help='Your registered team identifier; never hard-code it in source')
    parser.add_argument('--case-code', required=True)
    parser.add_argument('--mode', choices=['formal', 'practice'], required=True)
    parser.add_argument('--base-url', default='http://127.0.0.1:2026')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true', help='Explicitly send requests after checking the simulator UI')
    args = parser.parse_args()
    if not args.execute:parser.error('No request sent: --execute is required')
    url = urlparse(args.base_url)
    if url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost', '::1') or url.path not in ('', '/'):
        parser.error('The simulator uses an HTTP loopback address')
    if not args.case_code.strip():parser.error('Case code is required')
    if args.output.exists():parser.error('Use a new output directory')
    verify_sources()
    with sender_lock(ROOT/'.sender.lock'):
        # Client creates the wire log directory; use its parent as the policy folder.
        api = Client(args.robot_id, args.output/'wire.jsonl', args.base_url)
        result = run_policy(api, args.output, case_code=args.case_code, mode=args.mode)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
