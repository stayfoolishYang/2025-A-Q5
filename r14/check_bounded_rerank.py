"""Verify planned-route constraints for actual saved decision states."""
import json,gzip
from pathlib import Path
import numpy as np
from collect import ROOT
from belief1800 import DiscoveryBelief
from bounded_rerank import choose
b=DiscoveryBelief(power=12);cursor={str(c):0 for c in range(1,21)};checks=[]
with gzip.open(ROOT/'results/prediction/snapshots/0000.json.gz','rt') as f:states=json.load(f)
for step,s in enumerate(states):
    for c,h in s['history'].items():
        for point,result,_ in h[cursor[c]:]:b.observe(int(c),point,result)
        cursor[c]=len(h)
    for budget in (0,5,10,20):
        i,event=choose(b,s['nodes'],np.array(s['position']),budget)
        assert 0<=i<len(s['nodes'])
        if not event['fallback']:
            assert event['planned_detour_s']<=budget+2e-9
            if i:assert event['probability_gain']>.05
        checks.append(dict(step=step,budget=budget,**event))
(ROOT/'BOUNDED_RERANK_CHECK.json').write_text(json.dumps(dict(checks=len(checks),passed=True,events=checks),indent=2))
print('PASS',len(checks),'planned-route budget checks')
