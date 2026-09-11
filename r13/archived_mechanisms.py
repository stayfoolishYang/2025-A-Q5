"""Enrich archived certified/known16 states without rerunning any solver."""
from pathlib import Path
import gzip,json
import pandas as pd
import numpy as np
ROOT=Path(__file__).resolve().parent
ARCH=Path('J:/2026B_runs/q4_latest_7228633/cpu519_repeat_20260912')
credit=[];known=[];seen=set()
for path in sorted((ROOT/'results/state_audit').glob('[0-9]*.json.gz')):
    with gzip.open(path,'rt',encoding='utf-8') as f:data=json.load(f)
    seed=data['seed']
    with gzip.open(ARCH/'core/traces'/f'R12_{seed:04d}.json.gz','rt',encoding='utf-8') as f:tr=json.load(f)
    actions=tr['actions'];times=np.array([a['response']['virtual_time_s'] for a in actions])
    for state in data['certified_states']:
        idx=int(np.searchsorted(times,state['time_s'],side='right'))
        nxt=actions[idx] if idx<len(actions) else {}
        for target in state['certified']:
            key=(seed,state['time_s'],target['channel'],len(state['nodes']))
            if key in seen:continue
            seen.add(key)
            credit.append(dict(seed=seed,time_s=state['time_s'],channel=target['channel'],current_channel=state['current_channel'],nodes=len(state['nodes']),scan_credit_s=target['scan_credit_s'],next_action=nxt.get('stage','exit'),next_channel=nxt.get('channel'),next_path=nxt.get('path')))
    if data['total']==16:
        release=data['known16_release'][0] if data['known16_release'] else None
        row=tr['row'];known.append(dict(seed=seed,remaining_nodes=len(release['nodes']) if release else 0,
            remaining_targets=len(release['targets']) if release else row['known16_unresolved'],confirmed16_s=row['known16_time_s'],post_known16_s=row['post_known16_s'],fallback_count=row['fallback_count'],
            nearest_optional_m=float(np.linalg.norm(np.asarray(release['nodes'])-release['position'],axis=1).min()) if release else None))
out=ROOT/'analysis';out.mkdir(exist_ok=True)
pd.DataFrame(credit).to_csv(out/'archived_certified_credit.csv',index=False,encoding='utf-8-sig')
pd.DataFrame(known).to_csv(out/'archived_known16.csv',index=False,encoding='utf-8-sig')
print('Archived certified',len(credit),'N16',len(known),flush=True)
