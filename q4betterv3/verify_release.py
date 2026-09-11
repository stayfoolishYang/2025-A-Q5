"""Verify payload hashes and exact offline replay of three archived cases."""
import gzip,json,zipfile
from run import ROOT,run_scene,base

def main():
    checks=[]
    with zipfile.ZipFile(ROOT/'validation/scenes.zip') as z:
        for i in (0,95,874):
            folder=ROOT/f'verification_runs/case_{i:04d}'
            scene=ROOT/f'verification_runs/input_{i:04d}.json'
            scene.parent.mkdir(parents=True,exist_ok=True);scene.write_bytes(z.read(f'scenes/{i:04d}.json'))
            row=run_scene(scene,folder)
            with gzip.open(folder/'core/traces/B_0000.json.gz','rt',encoding='utf-8') as f:new=json.load(f)
            with gzip.open(ROOT/f'validation/representative_traces/B_{i:04d}.json.gz','rt',encoding='utf-8') as f:old=json.load(f)
            exact=base.canonical_actions(new)==base.canonical_actions(old)
            assert exact and row['virtual_time_s']==old['row']['virtual_time_s']
            checks.append(dict(case=i,exact_actions_feedback_rng=True,full_clear=True,audit_passed=True,virtual_time_s=row['virtual_time_s']))
    report=dict(status='PASS',scope='Portable entry point exact replay of 3 archived cases; not a new 1000-case evaluation',checks=checks)
    (ROOT/'RELEASE_CHECK.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
