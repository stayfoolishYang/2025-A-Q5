"""Small sequence regression for the active-only failure counter."""
from pathlib import Path
import sys
import numpy as np

BASE = Path(__file__).resolve().parents[1]/'B_solver'
sys.path.insert(0, str(BASE))
from phase_audit import TaggedSolver
from active_failure import ActiveFailureSolver


class Responses:
    position = np.zeros(2)
    virtual_time = 0.
    channel = 1
    stage = 'discovery'
    result = 'direction'

    def action(self, path, position=None, channel=None):
        self.virtual_time += 5
        return dict(accepted=True, virtual_time_s=self.virtual_time,
                    measure_result=self.result, svd_deg=0., clear_result='success')


def check():
    api = Responses(); solver = ActiveFailureSolver(api, False, 'P3')
    def observe(result, active=False):
        api.result = result
        solver._active_localization = active
        solver.measure(1, np.zeros(2))
        solver._active_localization = False
    observe('no_signal')
    assert not solver.tracks
    observe('direction')
    for _ in range(3): observe('no_signal')
    assert solver.tracks[1]['negatives'] == 0
    observe('no_signal', True)
    observe('no_signal')
    assert solver.tracks[1]['negatives'] == 1
    observe('no_signal', True); observe('no_signal', True)
    assert solver.tracks[1]['negatives'] == 3
    observe('direction')
    assert solver.tracks[1]['negatives'] == 0 and solver.tracks[1]['n'] == 2
    for _ in range(6): observe('direction', True)
    assert solver.tracks[1]['n'] == 8
    observe('near')
    assert 1 in solver.cleared and 1 not in solver.tracks
    original = TaggedSolver.localize
    def fail(*args, **kwargs):
        assert solver._active_localization
        raise RuntimeError('injected')
    try:
        TaggedSolver.localize = fail
        for before in (False, True):
            solver._active_localization = before
            try: solver.localize(1)
            except RuntimeError as e: assert str(e) == 'injected'
            else: raise AssertionError('Expected injected failure')
            assert solver._active_localization == before
    finally:
        TaggedSolver.localize = original
    try: ActiveFailureSolver(Responses(), True, 'P4')
    except ValueError: pass
    else: raise AssertionError('Q4 must be rejected')
    print('PASS: discovery/active counts, positive reset, direction cap, near deletion, context restoration, Q4 guard')


if __name__ == '__main__':
    check()
