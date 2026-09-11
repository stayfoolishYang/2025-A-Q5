"""Run validated Q3 revision D against a supplied offline engine."""
import argparse
import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE/'B_solver'))
sys.path.insert(0, str(BASE/'B_solver/experiments'))
from phase_audit import TaggedSolver
from active_failure import ActiveFailureSolver
from recovered_benchmark import EngineAdapter
from q3_stop16_pilot import CONFIG, audit


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sim-root', type=Path, required=True)
    p.add_argument('--scene', type=Path, default=BASE/'B_solver/results/q3_stop16_pilot_01/scenes/000.json')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--baseline', action='store_true', help='Run original scheduling for comparison')
    a = p.parse_args()
    if a.output.exists():
        p.error('Output already exists; use a new filename')
    sys.path.insert(0, str(a.sim_root.resolve()))
    from engine import Engine
    from scenario_io import load_scenario
    raw = json.loads(a.scene.read_bytes())
    scenario = load_scenario(raw)
    if scenario.problem != 3:
        p.error('Only Q3 scenarios are supported')
    engine = Engine(scenario)
    api = EngineAdapter(engine)
    cls = TaggedSolver if a.baseline else ActiveFailureSolver
    solver = cls(api, False, 'P3', diagnostic=dict(CONFIG, local_order=not a.baseline))
    if not a.baseline:
        solver.discovery_route = 'refresh_after_localize'
    result = solver.run()
    audit(api.log, False)
    assert not solver.tracks
    assert engine.cleared == {j.channel for j in engine.scenario.jammers}
    result.update(variant='A' if a.baseline else 'D', audit_passed=True,
                  execution_backend='LOCAL_DEV', execution_purpose='FRAMEWORK_INTEGRATION',
                  production_eligible=False)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(dict(result=result, actions=api.log), f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
