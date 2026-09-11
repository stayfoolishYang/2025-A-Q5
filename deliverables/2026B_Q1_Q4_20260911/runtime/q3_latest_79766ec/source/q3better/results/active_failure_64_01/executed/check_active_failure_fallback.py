"""Force both retained fallback triggers through the actual localize loop."""
from check_active_failure import Responses, ActiveFailureSolver, np


for reason in ('consecutive_no_signal', 'direction_limit'):
    api = Responses()
    solver = ActiveFailureSolver(api, False, 'P3', diagnostic={'grid_version':'grid_v1','local_order':True})
    api.result = 'direction'
    solver.measure(1, np.zeros(2))
    solver._active_localization = True
    if reason == 'direction_limit':
        for _ in range(7): solver.measure(1, np.zeros(2))
    else:
        api.result = 'no_signal'
        for _ in range(3): solver.measure(1, np.zeros(2))
    solver._active_localization = False
    solver.localize(1, one_step=True)
    assert solver.fallbacks == 1 and 1 in solver.cleared and not solver.tracks
    assert solver.trace[1]['fallback_trigger_reason'] == [reason]
    assert not solver._active_localization and api.stage == 'discovery'
print('PASS: actual localize still executes full-grid fallback for three active misses and eight directions')
