"""Independent action equality audits after completed batches."""
from pathlib import Path
import json,gzip,sys
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'baseline/q4better'))
from public_max37_benchmark import canonical_actions

def read(p):
    with gzip.open(p,'rt',encoding='utf-8') as f:return json.load(f)
def main(cohort):
    folder=ROOT/'results'/cohort;m=json.loads((folder/'manifest.json').read_bytes());checks=[]
    archive=Path('J:/2026B_runs/q4_latest_7228633/cpu519_repeat_20260912')
    for r in m['records']:
        i=r['id'];base=read(folder/'core/traces'/f'R12_{i:04d}.json.gz');a=canonical_actions(base)
        if cohort=='regression':
            old=read(archive/'core/traces'/f'R12_{i:04d}.json.gz');assert a==canonical_actions(old),(cohort,i,'baseline')
        for cfg in m['configs']:
            name=cfg['name']
            if name=='C1' or (name=='D' and r['total']<16):
                cand=read(folder/'core/traces'/f'{name}_{i:04d}.json.gz');assert a==canonical_actions(cand),(cohort,i,name)
                checks.append(dict(id=i,method=name,exact_action_equal=True))
            if name=='D' and r['total']==16:
                cand=read(folder/'core/traces'/f'D_{i:04d}.json.gz');b=canonical_actions(cand)
                time=base['row']['known16_time_s'];prefix=[x for x in a if x['response']['virtual_time_s']<=time];prefix_b=[x for x in b if x['response']['virtual_time_s']<=time]
                assert prefix==prefix_b,(cohort,i,'D prefix')
                checks.append(dict(id=i,method=name,known16_prefix_equal=True))
    out=dict(cohort=cohort,checks=checks,baseline_archive_equal=cohort=='regression',baseline_archive_cases=len(m['records']) if cohort=='regression' else 0,official_calls=0)
    (ROOT/'analysis'/f'{cohort}_ACTION_INVARIANCE.json').write_text(json.dumps(out,indent=2),encoding='utf-8');print(cohort,'invariance checks',len(checks),flush=True)
if __name__=='__main__':main(sys.argv[1])
