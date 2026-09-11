"""Offline integration checks and archive integrity for the Q1-Q4 handoff."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT=Path('J:/2026B_delivery/2026B_Q1-Q4_统一交接_20260911')

def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    checks={}
    q1=read(ROOT/'verification/q1_counterexample.json')
    checks['q1_counterexample']=q1['diameter_all_pairs_crosscheck'] and abs(q1['mec_radius']-23.094010777585)<1e-7
    checks['q2_default_exact']=read(ROOT/'verification/q2_default/q2.json')==read(ROOT/'q1q2/B_solver/results/q2.json')
    for q,name,v in [(3,'q3_latest_79766ec','D'),(4,'q4_latest_7228633','R12')]:
        root=ROOT/'runtime'/name
        if q==3:
            new=read(ROOT/'verification/q3_seed0.json');r=new['result'];actions=new['actions']
            old=read(root/'cpu519/runs/q3_0000_D.json')
            with gzip.open(root/'cpu519/runs/q3_0000_D.json.gz','rt',encoding='utf-8') as f:old_actions=json.load(f)
            full=r['audit_passed']
        else:
            r=read(ROOT/'verification/q4_seed0/core/rows/R12_0000.json');old=read(root/'cpu519/core/rows/R12_0000.json')
            with gzip.open(ROOT/'verification/q4_seed0/core/traces/R12_0000.json.gz','rt',encoding='utf-8') as f:actions=json.load(f)['actions']
            with gzip.open(root/'cpu519/core/traces/R12_0000.json.gz','rt',encoding='utf-8') as f:old_actions=json.load(f)['actions']
            full=r['run_status']=='FULL_CLEAR' and r['audit_passed']
        checks[f'q{q}_complete_offline_run']=full
        checks[f'q{q}_exact_actions']=actions==old_actions
        checks[f'q{q}_exact_virtual_time']=r['virtual_time_s']==old['virtual_time_s']
        portable=read(root/'source/PORTABLE_SOURCE_HASHES.json')
        checks[f'q{q}_frozen_source_hashes']=all(sha(root/'source'/f'q{q}better'/path)==h for path,h in portable.items())
    for p in [ROOT/'run.py',ROOT/'programs/official/run_latest_practice.py',ROOT/'programs/official/practice_resident.py']:
        compile(p.read_text(encoding='utf-8'),str(p),'exec')
    spec=importlib.util.spec_from_file_location('packaged_resident',ROOT/'programs/official/practice_resident.py')
    resident=importlib.util.module_from_spec(spec);spec.loader.exec_module(resident)
    accepted=[]
    for q in [3,4]:
        for mode in ['演练','正式']:
            text=f'队号 202627002054\n问题{q}\n{mode}\n测试\n等待机器狗进入\n测试案例编码\nAAAA-BBBB-CCCC-DDDD\n'
            ui=resident.parse_ui(text)
            accepted.append(bool(ui and ui['mode']=='演练' and ui['status']=='等待机器狗进入'))
            if mode=='正式':
                before=ROOT/'verification'/f'formal_refusal_q{q}.txt';before.write_text(text,encoding='utf-8')
                proc=subprocess.run([sys.executable,str(ROOT/'programs/official/run_latest_practice.py'),'--problem',str(q),'--case','AAAA-BBBB-CCCC-DDDD','--before',str(before)],capture_output=True,text=True)
                checks[f'q{q}_formal_rejected_before_client_import']=proc.returncode!=0 and 'No matching waiting PRACTICE session' in proc.stderr
                (ROOT/'verification'/f'formal_refusal_q{q}_output.txt').write_text(proc.stdout+proc.stderr,encoding='utf-8')
    checks['ui_practice_formal_separation']=accepted==[True,False,True,False]
    rawlog=(ROOT/'verification/q2_regression.txt').read_bytes()
    testlog=rawlog.decode('utf-16' if rawlog.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig')
    checks['q2_25_regressions']='Ran 25 tests' in testlog and 'OK' in testlog
    assert all(checks.values()),checks
    payload=dict(status='PASS',checks=checks,official_calls=0,formal_tests=0,
        new_offline_solver_runs=2,interpretation='Packaging integration only; not new independent benchmark seeds.',
        practice_port='Static saved-text UI classification, direct refusal tests and source hashes checked; no GUI launched and no live official requests.',
        source_change='Frozen Q3/Q4 strategy source unchanged. Entry paths portable; Q1 wrapper rejects diameter disagreement; Q2 baseline unchanged.')
    (ROOT/'PACKAGE_VERIFICATION.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    shutil.copy2(Path(__file__),ROOT/'programs/verify_unified_handoff.py')
    # Preserve portable core pin and builder source provenance after the dependency correction.
    shutil.copy2(Path(__file__).with_name('build_unified_handoff.py'),ROOT/'programs/build_unified_handoff.py')
    files=[p for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='FILE_HASHES.json']
    hashes={p.relative_to(ROOT).as_posix():sha(p) for p in files}
    (ROOT/'FILE_HASHES.json').write_text(json.dumps(hashes,ensure_ascii=False,indent=2),encoding='utf-8')
    subprocess.run([sys.executable,str(ROOT/'run.py'),'verify'],check=True)
    archive=ROOT.with_suffix('.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in files+[ROOT/'FILE_HASHES.json']:z.write(p,p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for name,h in hashes.items():assert hashlib.sha256(z.read(name)).hexdigest()==h,name
    archive.with_suffix('.zip.sha256').write_text(sha(archive),encoding='ascii')
    print(json.dumps(dict(archive=str(archive),bytes=archive.stat().st_size,files=len(hashes),checks=checks),ensure_ascii=False))

if __name__=='__main__':main()
