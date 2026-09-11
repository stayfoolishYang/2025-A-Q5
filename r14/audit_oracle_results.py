from pathlib import Path
import json,gzip
root=Path('r14/results/value_oracle');selection=json.loads((root/'selection.json').read_bytes())['states'];branches=0;max_error=0.
for state in selection:
    i,j=state['id'],state['step']
    with gzip.open(root/'oracle'/f'{i:04d}_{j:02d}.json.gz','rt') as f:d=json.load(f)
    assert d['state']==state and len(d['branches'])==state['nodes']
    row=json.loads((root/'core/rows'/f'R12_{i:04d}.json').read_bytes())
    assert abs(d['branches'][0]['cost']-(row['virtual_time_s']-state['time_s']))<1e-6
    assert [b['index'] for b in d['branches']]==list(range(state['nodes']))
    for b in d['branches']:
        assert b['actions'][-1]['path']=='/exit'
        err=abs(sum(a.get('total_s',0) for a in b['actions'])-b['cost']);max_error=max(max_error,err);assert err<1e-6
        assert all(a['response']['accepted'] for a in b['actions'])
        if state['N']<16:assert not b['release16']
        branches+=1
result=dict(states=len(selection),branches=branches,baseline_remaining_cost_match=True,all_candidate_nodes_present=True,all_actions_accepted=True,max_ledger_error_s=max_error,official_calls=0)
Path('r14/analysis/value_oracle/FINAL_LEDGER_AUDIT.json').write_text(json.dumps(result,indent=2));print(result)
