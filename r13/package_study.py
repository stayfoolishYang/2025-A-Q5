"""Package committed research and immutable evidence; no simulation or networking."""
from pathlib import Path
import json,hashlib,zipfile,subprocess,shutil
ROOT=Path(__file__).resolve().parent
DEST=Path('I:/GithubRick/2025-A-Q5/交付包/2026B_Q4_R13_2965次本地研究_20260912')

def main():
    cmd=['git','-c','safe.directory=J:/2026B_experiments/q4-r13-routing-study']
    status=subprocess.check_output(cmd+['status','--porcelain'],cwd=ROOT.parent,text=True,encoding='utf-8')
    assert not status,'Commit research changes before delivery'
    head=subprocess.check_output(cmd+['rev-parse','HEAD'],cwd=ROOT.parent,text=True).strip()
    branch=subprocess.check_output(cmd+['branch','--show-current'],cwd=ROOT.parent,text=True).strip()
    DEST.mkdir(parents=True,exist_ok=False)
    state=dict(head=head,branch=branch,dirty=False,push_status='not_pushed',official_calls=0,formal_test_count=0,decision='KEEP_R12',local_engine_runs=2965)
    (DEST/'DELIVERY_STATE.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    for name in ['R13_FINAL_HANDOFF.md','R13_ALL_METHODS_COMPARISON.csv','FIGURE_GUIDE.md','REPRODUCE.md']:
        shutil.copy2(ROOT/name,DEST/name)
    shutil.copy2(ROOT/'figures/R13_13张机制与效果图谱.pdf',DEST/'R13_13张机制与效果图谱.pdf')
    files=[]
    for p in ROOT.rglob('*'):
        if not p.is_file():continue
        rel=p.relative_to(ROOT)
        if '__pycache__' in rel.parts or 'pdf_check' in rel.parts:continue
        if p.name.endswith('REVIEW.png') or p.name=='CONTACT_SHEET.png':continue
        files.append((p,'r13/'+rel.as_posix()))
    files.append((DEST/'DELIVERY_STATE.json','DELIVERY_STATE.json'))
    full=DEST/'R13_完整代码场景轨迹与图表.zip'
    with zipfile.ZipFile(full,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p,rel in files:z.write(p,rel,compress_type=zipfile.ZIP_STORED if p.suffix=='.gz' else zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(full) as z:assert z.testzip() is None
    review=DEST/'R13_GPT审阅精简包.zip'
    def use(p,rel):
        parts=Path(rel).parts
        if 'results' in parts or 'baseline' in parts or 'local_engine' in parts:return False
        if 'analysis' in parts:
            return p.name.endswith(('_summary.csv','_pairs.csv','_strata.csv','_extremes.csv')) or p.name=='COMPUTE_COLD_WARM.json'
        if p.name.startswith('HISTORICAL_') or p.name.endswith('_MANIFEST.json') or p.name.startswith('USER_REQUEST'):return False
        return True
    with zipfile.ZipFile(review,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p,rel in files:
            if use(p,rel):z.write(p,rel)
    with zipfile.ZipFile(review) as z:assert z.testzip() is None
    info={p.name:dict(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in [full,review]}
    (DEST/'PACKAGE_HASHES.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(destination=str(DEST),state=state,packages=info),ensure_ascii=False),flush=True)
if __name__=='__main__':main()
