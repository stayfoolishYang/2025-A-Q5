"""Prepare and independently summarize the local Q2 experiment evidence."""
import argparse
import ast
import csv
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
from q2_continuous_search import baseline, PLAN, write_json
from q2_scoring import adaptive_score

BASE = Path(__file__).resolve().parent
INITIAL_HEAD = '7c90ba18c863d7bb99266ad992dbe5d648a46426'


def protected_state():
    paths = subprocess.check_output(['git','ls-tree','-r','--name-only',INITIAL_HEAD,'B_solver'],cwd=BASE.parent,text=True).splitlines()
    paths = [p for p in paths if Path(p).suffix in ('.py','.cu','.cpp','.hpp','.h','.toml') and p!='B_solver/questions.py']
    paths += ['B_solver/results/q2.json','B_solver/results/q2_candidates.csv']
    state = {}
    for path in paths:
        old = subprocess.check_output(['git','show',INITIAL_HEAD+':'+path],cwd=BASE.parent)
        current = (BASE.parent/path).read_bytes()
        state[path] = dict(before=hashlib.sha256(old).hexdigest(),after=hashlib.sha256(current).hexdigest())
    source = (BASE/'questions.py').read_text(encoding='utf-8')
    original = subprocess.check_output(['git','show',INITIAL_HEAD+':B_solver/questions.py'],cwd=BASE.parent,text=True)
    def q1_hash(text):
        function = next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=='solve_q1')
        return hashlib.sha256(ast.dump(function,include_attributes=False).encode()).hexdigest()
    state['B_solver/questions.py::solve_q1_AST'] = dict(before=q1_hash(original),after=q1_hash(source))
    if not all(v['before']==v['after'] for v in state.values()):
        raise AssertionError('Protected file changed')
    return state


def prepare(root):
    root.mkdir(parents=True,exist_ok=True)
    write_json(root/'PROTECTED_BEFORE.json',protected_state())
    poly,points,_ = baseline()
    pilot = []
    for index in (0,106,176):
        score = adaptive_score((points[index],poly))
        pilot.append(dict(legacy_index=index,elapsed_s=score['elapsed_s'],
                          posterior_evaluations=score['posterior_evaluations'],inner_gap_m=score['inner_gap_m']))
    write_json(root/'PILOT_COST.json',dict(points=pilot,used_for_parameter_tuning=False,
                                         planned_parameters=PLAN,official_calls=0))
    tests = subprocess.run([sys.executable,str(BASE/'tests/test_q2_continuous_search.py')],capture_output=True,text=True)
    (root/'TESTS_BEFORE.txt').write_text(tests.stdout+tests.stderr,encoding='utf-8')
    if tests.returncode:
        raise RuntimeError(tests.stdout+tests.stderr)
    print(json.dumps(dict(pilot=pilot,tests_passed=25,protected_files_unchanged=True)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare',type=Path)
    args = parser.parse_args()
    if args.prepare:
        prepare(args.prepare)
