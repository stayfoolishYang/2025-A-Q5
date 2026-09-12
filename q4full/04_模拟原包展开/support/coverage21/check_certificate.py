"""Independent verifier: support half-planes, no hull or builder imports.
Checks exact decimal input, complete prefix tree, disk and hull containment.
"""
from pathlib import Path
from fractions import Fraction
import json, hashlib, time
BASE=Path(__file__).resolve().parent

def verify(certificate_path=None, binary64=False, certificate_data=None):
    start=time.perf_counter()
    raw=(BASE/'points21.json').read_bytes()
    cert_bytes=(json.dumps(certificate_data).encode() if certificate_data is not None else
                (Path(certificate_path) if certificate_path else BASE/'certificate.json').read_bytes())
    cert=json.loads(cert_bytes)
    assert cert['schema']=='coverage21-rectangle-v1'
    assert cert['points_sha256']==hashlib.sha256(raw).hexdigest()
    assert cert['source_radius_m']==1800 and cert['reception_radius_m']==1000
    certified_scale=cert['scale']; assert type(certified_scale) is int and certified_scale>0
    scale=2**64 if binary64 else certified_scale
    source=json.loads(raw,parse_float=str,parse_int=str)['points']
    points=[]
    for pair in source:
        # Optional exact dyadic coordinates of Python's actual JSON float parser.
        # Float is used only to obtain its exact integer ratio, never a predicate.
        q=[(Fraction.from_float(float(s)) if binary64 else Fraction(s))*scale for s in pair]
        assert all(x.denominator==1 for x in q)
        points.append(tuple(x.numerator for x in q))
    assert len(points)==21 and len(set(points))==21
    root=[-1800*scale,-1800*scale,1800*scale,1800*scale]
    assert cert['root_scaled']==[-1800*certified_scale,-1800*certified_scale,1800*certified_scale,1800*certified_scale]
    trie={}; count={'covered':0,'outside':0}; deepest=0
    for leaf in cert['leaves']:
        path=leaf['path']; assert isinstance(path,str) and set(path)<=set('0123') and len(path)<=32
        node=trie
        for digit in path:
            assert '_leaf' not in node, 'A leaf has descendants'
            node=node.setdefault(digit,{})
        assert not node, 'Duplicate leaf or prefix of an existing leaf'
        node['_leaf']=leaf
    nodes=0
    def audit_tree(node,box,depth):
        nonlocal nodes,deepest
        nodes+=1; deepest=max(deepest,depth)
        x0,y0,x1,y1=box
        assert x0<x1 and y0<y1
        if '_leaf' not in node:
            assert set(node)==set('0123'), 'Incomplete four-way subdivision'
            assert (x0+x1)%2==0 and (y0+y1)%2==0
            mx=(x0+x1)//2; my=(y0+y1)//2
            for digit,bb in zip('0123',[(x0,y0,mx,my),(mx,y0,x1,my),(x0,my,mx,y1),(mx,my,x1,y1)]):
                audit_tree(node[digit],bb,depth+1)
            return
        assert set(node)=={'_leaf'}
        leaf=node['_leaf']; kind=leaf['kind']; assert kind in count
        count[kind]+=1
        if kind=='outside':
            nearest_x=0 if x0<=0<=x1 else min(abs(x0),abs(x1))
            nearest_y=0 if y0<=0<=y1 else min(abs(y0),abs(y1))
            assert nearest_x**2+nearest_y**2>(1800*scale)**2, 'Outside rejection is false'
            return
        ids=leaf['stations']; assert len(ids)>=3 and len(set(ids))==len(ids)
        assert all(type(i) is int and 0<=i<21 for i in ids)
        selected=[points[i] for i in ids]
        vertices=[(x,y) for x in [x0,x1] for y in [y0,y1]]
        for sx,sy in selected:
            # Separate-coordinate maximization independently replaces four distances.
            worst_x=max((sx-x0)**2,(sx-x1)**2)
            worst_y=max((sy-y0)**2,(sy-y1)**2)
            assert worst_x+worst_y<=(1000*scale)**2, 'Rectangle outside a reception disk'
        def side(a,b,p):
            return (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])
        assert any(side(selected[0],a,b)!=0 for a in selected[1:] for b in selected[1:]), 'Degenerate station hull'
        supports=0
        for a in selected:
            for b in selected:
                if a==b: continue
                if all(side(a,b,p)>=0 for p in selected):
                    supports+=1
                    assert all(side(a,b,v)>=0 for v in vertices), 'Rectangle violates a hull support'
        assert supports>=3
    audit_tree(trie,root,0)
    return {'status':'PASS','method':'all supporting half-planes; independent prefix-tree check',
            'coordinate_semantics':'exact binary64 dyadic values' if binary64 else 'exact decimal strings',
            'nodes':nodes,'leaves':sum(count.values()),**count,'maximum_depth':deepest,
            'unresolved':0,'certificate_sha256':hashlib.sha256(cert_bytes).hexdigest(),
            'runtime_s':time.perf_counter()-start}

if __name__=='__main__':
    result=verify()
    (BASE/'check_result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
    binary_result=verify(binary64=True)
    (BASE/'binary64_check_result.json').write_text(json.dumps(binary_result,indent=2),encoding='utf-8')
    print(json.dumps(binary_result))
