"""Exact integer rectangle certificate for the supplied 21 station decimals.
No point sampling, floating geometry, simulation, or external dependencies.
"""
from pathlib import Path
from decimal import Decimal
import json, hashlib, time

BASE = Path(__file__).resolve().parent
MAX_DEPTH = 16
SCALE = 10**16 * 2**MAX_DEPTH

def integer_decimal(v):
    sign, digits, exponent = Decimal(v).as_tuple()
    mantissa = int(''.join(map(str, digits))) * (-1 if sign else 1)
    if exponent >= 0:
        return mantissa * 10**exponent * SCALE
    factor, rem = divmod(SCALE, 10**(-exponent))
    assert rem == 0, 'Scale does not represent the supplied coordinate exactly'
    return mantissa * factor

def cross(o, a, b):
    return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])

def hull(points):
    points = sorted(set(points))
    if len(points) < 3:
        return []
    lo, hi = [], []
    for seq, stack in [(points, lo), (points[::-1], hi)]:
        for p in seq:
            while len(stack) >= 2 and cross(stack[-2], stack[-1], p) <= 0:
                stack.pop()
            stack.append(p)
    result = lo[:-1] + hi[:-1]
    return result if len(result) >= 3 else []

def corners(box):
    x0, y0, x1, y1 = box
    return [(x0,y0),(x1,y0),(x1,y1),(x0,y1)]

def children(box):
    a,b,c,d=box; x=(a+c)//2; y=(b+d)//2
    assert (a+c)%2 == 0 and (b+d)%2 == 0
    return [(a,b,x,y),(x,b,c,y),(a,y,x,d),(x,y,c,d)]

def main():
    start=time.perf_counter()
    raw=(BASE/'points21.json').read_bytes()
    parsed=json.loads(raw,parse_float=Decimal,parse_int=Decimal)
    stations=[tuple(integer_decimal(v) for v in p) for p in parsed['points']]
    assert len(stations)==21 and len(set(stations))==21
    domain_radius=1800*SCALE; receiver_radius=1000*SCALE
    leaves=[]; nodes=0; max_depth=0
    def visit(path,box):
        nonlocal nodes,max_depth
        nodes+=1; max_depth=max(max_depth,len(path))
        x0,y0,x1,y1=box
        dx=max(x0,0,-x1); dy=max(y0,0,-y1)
        if dx*dx+dy*dy>domain_radius*domain_radius:
            leaves.append({'path':path,'kind':'outside'}); return
        cc=corners(box)
        ids=[i for i,(x,y) in enumerate(stations) if all((x-a)**2+(y-b)**2<=receiver_radius**2 for a,b in cc)]
        hp=hull([stations[i] for i in ids])
        if hp and all(cross(hp[i],hp[(i+1)%len(hp)],p)>=0 for i in range(len(hp)) for p in cc):
            leaves.append({'path':path,'kind':'covered','stations':ids}); return
        if len(path)>=MAX_DEPTH:
            raise RuntimeError('Unresolved cell '+path+'; no complete certificate issued')
        for i,b in enumerate(children(box)): visit(path+str(i),b)
    visit('',(-domain_radius,-domain_radius,domain_radius,domain_radius))
    cert={'schema':'coverage21-rectangle-v1','points_sha256':hashlib.sha256(raw).hexdigest(),
          'scale':SCALE,'source_radius_m':1800,'reception_radius_m':1000,
          'half_plane':'closed: u dot (station-source) >= 0',
          'root_scaled':[-domain_radius,-domain_radius,domain_radius,domain_radius],
          'child_order':'0 southwest; 1 southeast; 2 northwest; 3 northeast','leaves':leaves}
    payload=json.dumps(cert,separators=(',',':')).encode()
    (BASE/'certificate.json').write_bytes(payload)
    counts={k:sum(e['kind']==k for e in leaves) for k in ['covered','outside']}
    summary={'status':'PASS','nodes':nodes,'leaves':len(leaves),**counts,
             'maximum_depth':max_depth,'unresolved':0,'arithmetic':'integer predicates',
             'certificate_sha256':hashlib.sha256(payload).hexdigest(),
             'points_sha256':hashlib.sha256(raw).hexdigest(),
             'runtime_s':time.perf_counter()-start}
    (BASE/'build_result.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary))

if __name__=='__main__': main()
