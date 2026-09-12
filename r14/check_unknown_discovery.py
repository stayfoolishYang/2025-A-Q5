import json,itertools,math
from collect import ROOT
import numpy as np
from unknown_discovery import geometry_integrals,coefficients,UnknownPosterior
from receive_integral import integrate
rng=np.random.default_rng(17231);points=rng.uniform(-800,800,(20,2));h=rng.uniform(-1600,1600,(4,2));nodes=rng.uniform(-1600,1600,(5,2))
a,b=geometry_integrals(points,h,nodes)
for i,p in enumerate(points):
 x,y=integrate(p,[(v,'no_signal',None) for v in h],[],nodes);assert abs(a[i]-x)<1e-12 and np.max(abs(b[i]-y))<1e-12
vals=np.array([.2,.4,.6,.8]);c=coefficients(vals)
for k in range(5):assert abs(c[k]-sum(np.prod(vals[list(ix)]) for ix in itertools.combinations(range(4),k)))<1e-12
class Empty:known=set();hist={c:[] for c in range(1,21)}
u=UnknownPosterior(Empty(),np.array([[0.,0.]]),18001);assert np.allclose(u.pm,1/7)
expected=.75*(1000**2+1000*1500+1500**2)/3/1800**2
observed=next(iter(u.data.values()))['joint'][0];assert abs(observed-expected)<.001
out=ROOT/'results/unknown_discovery';out.mkdir(exist_ok=True)
(out/'checks.json').write_text(json.dumps(dict(vector_scalar_checks=20,subset_polynomial_checks=5,empty_history_count_uniform=True,origin_single_source_exact=expected,origin_single_source_estimate=observed),indent=2));print('UNKNOWN_CHECKS PASS')
