"""Negative integrity checks: each corrupted certificate must be rejected."""
import copy, json, sys
sys.dont_write_bytecode=True
from check_certificate import BASE, verify

original=json.loads((BASE/'certificate.json').read_text())
cases={}
c=copy.deepcopy(original); c['leaves'].pop(); cases['missing_leaf']=c
c=copy.deepcopy(original); c['leaves'].append(c['leaves'][0]); cases['duplicate_leaf']=c
c=copy.deepcopy(original); c['points_sha256']='0'*64; cases['wrong_points_hash']=c
c=copy.deepcopy(original)
next(x for x in c['leaves'] if x['kind']=='covered')['stations']=list(range(21))
cases['invalid_reception_witness']=c
c=copy.deepcopy(original)
next(x for x in c['leaves'] if x['kind']=='covered')['kind']='outside'
cases['false_outside_leaf']=c
result={}
for name,c in cases.items():
    try:
        verify(certificate_data=c)
    except (AssertionError,KeyError,ValueError):
        result[name]='REJECTED'
    else:
        raise RuntimeError('Corruption not detected: '+name)
(BASE/'negative_checks.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
