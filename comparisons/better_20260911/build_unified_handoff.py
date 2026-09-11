"""Assemble a relocatable Q1-Q4 engineering handoff without changing strategies."""
import hashlib
import json
from pathlib import Path,PurePosixPath
import shutil
import subprocess
import zipfile

REPO=Path(__file__).resolve().parents[2]
BASE=Path('J:/2026B_runs')
OUT=Path('J:/2026B_delivery/2026B_Q1-Q4_统一交接_20260911')

def copy(src,dst):
    dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)

def tree(src,dst):
    shutil.copytree(src,dst,ignore=shutil.ignore_patterns('__pycache__','.git','*.pyc'),dirs_exist_ok=True)

def write(name,text):
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8')

def main():
    OUT.mkdir(parents=True,exist_ok=False)
    old=next((REPO/'交付包').glob('*正文比较版*含使用说明.zip'))
    with zipfile.ZipFile(old) as z:
        for info in z.infolist():
            rel=PurePosixPath(info.filename)
            assert not rel.is_absolute() and '..' not in rel.parts
            if info.is_dir():continue
            dest=OUT/'q1q2'/Path(*rel.parts[1:]);dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(z.read(info))
    b=REPO/'B_solver'
    # Overlay the current Q1/Q2 engineering files; keep the historical paper as a labeled draft.
    for p in b.rglob('*'):
        rel=p.relative_to(b)
        if not p.is_file() or rel.parts[0] in ('results','paper','figures','__pycache__'):continue
        if '__pycache__' not in rel.parts and p.suffix in ('.py','.md','.json','.yaml','.txt'):
            copy(p,OUT/'q1q2/B_solver'/rel)
    for name in ['q1.json','q2.json','q2_candidates.csv','geometry_checks.json']:
        copy(b/'results'/name,OUT/'q1q2/B_solver/results'/name)
    for name in ['q2_score_20260911','q2_reception_outer_20260911']:
        tree(b/'results'/name,OUT/'q1q2/B_solver/results'/name)
    commits={3:'79766ecf0d2577289f814edba310327f55424111',4:'7228633906262bb035f4ea1d859792e9f4484d20'}
    names={3:'q3_latest_79766ec',4:'q4_latest_7228633'}
    for q,name in names.items():
        root=BASE/name;dest=OUT/'runtime'/name
        tree(root/'source',dest/'source');tree(root/'cpu519',dest/'cpu519')
        src=root/'source'/f'q{q}better'
        original=json.loads((root/'cpu519'/('PLAN.json' if q==3 else 'HASHES.json')).read_bytes())
        hashes=original['hashes'] if q==3 else original
        frozen={Path(p).relative_to(src).as_posix():h for p,h in hashes.items() if Path(p).is_relative_to(src)}
        for rel,h in frozen.items():assert hashlib.sha256((dest/'source'/f'q{q}better'/rel).read_bytes()).hexdigest()==h
        write(Path('runtime')/name/'source/PORTABLE_SOURCE_HASHES.json',json.dumps(frozen,indent=2))
    tree(Path('G:/QQ/jammers_linux'),OUT/'runtime/local_engine')
    snapshot=BASE/'official_latest/resident/snapshot_q3_30_20260911_195454'
    tree(snapshot,OUT/'results/official_snapshot')
    sessions=json.loads((snapshot/'sessions.json').read_bytes())
    for r in sessions:
        folder=f'q{r["problem"]}_{r["case"]}'
        tree(BASE/'official_latest'/folder,OUT/'results/official_cases'/folder)
    comparison=BASE/'practice_comparison_20260911'
    tree(comparison,OUT/'results/practice_comparison')
    here=Path(__file__).parent
    for name in ['run_latest_practice.py','practice_resident.py','read_practice_ui.ps1','RESIDENT_README.md']:
        copy(here/name,OUT/'programs/official'/name)
    p=OUT/'programs/official/run_latest_practice.py';text=p.read_text(encoding='utf-8')
    text=text.replace("BASE=Path('J:/2026B_runs')","BASE=Path(__file__).resolve().parents[2]/'runtime'\n(BASE/'official_latest').mkdir(parents=True,exist_ok=True)")
    text=text.replace("        hashes=json.loads((root/'cpu519/PLAN.json').read_bytes())['hashes']\n",'')
    text=text.replace("        hashes=json.loads((root/'cpu519/HASHES.json').read_bytes())\n",'')
    text=text.replace("checked={name:h for name,h in hashes.items() if Path(name).is_relative_to(src)}","checked={str(src/name):h for name,h in json.loads((src.parent/'PORTABLE_SOURCE_HASHES.json').read_bytes()).items()}")
    p.write_text(text,encoding='utf-8')
    p=OUT/'programs/official/practice_resident.py';text=p.read_text(encoding='utf-8')
    text=text.replace("ROOT=Path('J:/2026B_runs/official_latest')","ROOT=Path(__file__).resolve().parents[2]/'runtime/official_latest'")
    p.write_text(text,encoding='utf-8')
    copy(here/'handoff_run.py',OUT/'run.py')
    write('START_PRACTICE.cmd','@echo off\ncd /d "%~dp0"\nif exist "D:\\Anaconda3\\envs\\torchgpu\\python.exe" (\n "D:\\Anaconda3\\envs\\torchgpu\\python.exe" "%~dp0run.py" practice\n) else (\n python "%~dp0run.py" practice\n)\nif errorlevel 1 pause\n')
    write('requirements-core.txt','numpy==1.26.4\nscipy==1.15.2\n')
    write('requirements-figures.txt','matplotlib==3.10.8\npandas==2.3.3\nPillow\npypdf\n')
    # Existing deep experiment reports are historical evidence, never current default instructions.
    for name in ['NCCP_RESULTS.md','NCCP_IMPLEMENTATION.md','STATE_RESTORING_BRIDGE_AUDIT.md','CLEARANCE_SHADOW_AUDIT.md','Q4_DISCOVERY_RESULTS.md','Q4_WORKLOAD_RESULTS.md','TECHNICAL_AUDIT.md','解题报告.md']:
        copy(b/name,OUT/'docs/history'/name)
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
    write('VERSION.json',json.dumps(dict(package='2026B unified engineering handoff',date='2026-09-11',
        q1_q2_repository_head=head,q3_commit=commits[3],q4_commit=commits[4],
        q2_default='legacy_213; stable all-pairs sampled scoring',q2_candidate_adoption=False,
        runtime='CPU FP64; NumPy1.26.4; no GPU requirement',formal_test_authorized=False,
        packaging_changes='Relative data paths and unified wrapper only; frozen strategy hashes preserved',
        paper_status='Q1/Q2 12-page historical draft plus latest audits; no current complete Q1-Q4 submission paper',
        source_repositories='Same GitHub repository, independently frozen subdirectory revisions; not one common Git HEAD'),ensure_ascii=False,indent=2))
    copy(Path(__file__),OUT/'programs/build_unified_handoff.py')
    print(OUT)

if __name__=='__main__':main()
