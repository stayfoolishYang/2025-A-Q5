"""Latest CPU strategies for a freshly UI-verified official PRACTICE session."""
import argparse,hashlib,json,msvcrt,re,subprocess,sys,time
from pathlib import Path

BASE=Path(__file__).resolve().parents[2]/'runtime'
(BASE/'official_latest').mkdir(parents=True,exist_ok=True)
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--problem',type=int,choices=(3,4),required=True)
    p.add_argument('--case',required=True)
    p.add_argument('--before',type=Path,required=True,help='Fresh computer-use document_text saved from waiting PRACTICE screen')
    a=p.parse_args()
    if not re.fullmatch(r'[A-Z0-9]{4}(?:-[A-Z0-9]{4}){3}',a.case):p.error('Invalid case code')
    evidence=a.before.read_text(encoding='utf-8')
    age=time.time()-a.before.stat().st_mtime
    # Some external-drive filesystems round modification timestamps up to two seconds.
    if not -2<=age<=120:p.error(f'Observe the waiting practice screen again; evidence age={age:.3f}s, must be <=120 seconds old')
    if not re.search(rf'问题{a.problem}\s+演练\s+测试\s+等待机器狗进入',evidence):p.error('No matching waiting PRACTICE session in UI evidence')
    if a.case not in evidence or '队号 202627002054' not in evidence:p.error('Case/team mismatch')
    if '测试已结束' in evidence:p.error('The observed session has ended')
    sender_lock=(BASE/'official_latest/sender.lock').open('a+b');sender_lock.seek(0)
    try:msvcrt.locking(sender_lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:p.error('Another official client is running; refusing concurrent actions')
    if a.problem==3:
        root=BASE/'q3_latest_79766ec';src=root/'source/q3better'
        commit='79766ecf0d2577289f814edba310327f55424111'
    else:
        root=BASE/'q4_latest_7228633';src=root/'source/q4better'
        commit='7228633906262bb035f4ea1d859792e9f4484d20'
    checked={str(src/name):h for name,h in json.loads((src.parent/'PORTABLE_SOURCE_HASHES.json').read_bytes()).items()}
    if not checked:raise RuntimeError('Missing frozen source hashes')
    for name,h in checked.items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=h:raise RuntimeError('Frozen source changed: '+name)
    sys.path[:0]=[str(src),str(src/'B_solver'),str(src/'B_solver/experiments')]
    from simulator import Client
    out=BASE/'official_latest'/f'q{a.problem}_{a.case}'
    out.mkdir(exist_ok=False)
    (out/'before.txt').write_text(evidence,encoding='utf-8')
    class PracticeClient(Client):
        def action(self,path,position=None,channel=None):
            if path=='/enter':
                observed=subprocess.run(['powershell.exe','-NoProfile','-File',str(Path(__file__).with_name('read_practice_ui.ps1'))],capture_output=True,timeout=12,creationflags=subprocess.CREATE_NO_WINDOW)
                if observed.returncode:raise RuntimeError('Cannot verify live practice UI; no enter sent')
                current=json.loads(observed.stdout.decode('utf-8-sig'))['text']
                if (not re.search(rf'问题{a.problem}\s+演练\s+测试\s+等待机器狗进入',current)
                        or not re.search(r'测试案例编码\s+'+re.escape(a.case)+r'\b',current)
                        or '队号 202627002054' not in current):
                    raise RuntimeError('Live practice case changed; no enter sent')
            return super().action(path,position,channel)
    api=PracticeClient('202627002054',out/'wire.jsonl',base_url='http://127.0.0.1:2026')
    api.stage='discovery'  # Q3 TaggedSolver only annotates stages; official Client needs this initial field.
    if a.problem==3:
        from active_failure import ActiveFailureSolver
        from q3_stop16_pilot import CONFIG
        cfg=dict(CONFIG,local_order=True)
        solver=ActiveFailureSolver(api,False,'P3',device='cpu',diagnostic=cfg)
        solver.discovery_route='refresh_after_localize'
        variant='D'
    else:
        from solver import Solver
        cfg=json.loads((src/'configs/q4_known16_tri25_R12.yaml').read_bytes())
        solver=Solver(api,True,'P4',device='cpu',diagnostic=cfg)
        variant='R12'
    meta=dict(problem=a.problem,case=a.case,variant=variant,commit=commit,config=cfg,device='cpu',
              source_hashes=checked,robot_id=api.robot_id,endpoint=api.base_url,evidence='official_practice',
              ui_evidence_age_s=age,full_clear_verified=False)
    (out/'manifest.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        result=solver.run()
    except Exception as e:
        (out/'error.json').write_text(json.dumps(dict(error=repr(e),virtual_time_s=api.virtual_time),indent=2),encoding='utf-8')
        raise
    result.update(problem=a.problem,case=a.case,variant=variant,device='cpu',evidence='official_practice',full_clear_verified=False)
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
