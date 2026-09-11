"""Public-history-only world sampler. Compatibility is checked, calibration is not assumed."""
import math,copy
import numpy as np
from collect import SRC
from belief1800 import DiscoveryBelief
from geometry import disk,wedge,intersect_disk,sample_poly
from particles import feasible
from engine import Engine,Scenario,Jammer,quantize_bearing
from paired_noise import PairedNoise

class SamplingUnavailable(RuntimeError):pass

class SampledEngine(Engine):
    def __init__(self,sources,fields):
        super().__init__(Scenario('00',4,tuple(sources),'belief_sample'))
        self.fields=fields
    def apply(self,path,request):
        result=super().apply(path,request)
        if result.get('measure_result')=='direction':
            c=request['channel'];p=request['position'];source=self.sources[c]
            base=math.degrees(math.atan2(source.y-p['y'],source.x-p['x']))%360
            result['svd_deg']=quantize_bearing(base,self.fields[c].value([p['x'],p['y']]))
        return result

def public_actions(actions):
    # Explicit projection excludes engine state, targets, seed, true N and costs.
    out=[]
    for a in actions:
        r=a['response'];response={k:r[k] for k in ('accepted','measure_result','svd_deg','clear_result') if k in r}
        out.append(dict(path=a['path'],position=a['position'],channel=a['channel'],response=response))
    return out

class WorldSampler:
    def __init__(self,actions):
        self.actions=public_actions(actions);self.hist={c:[] for c in range(1,21)}
        self.clear_obs={c:[] for c in range(1,21)};self.known=set();self.cleared=set();self.belief=DiscoveryBelief()
        for a in self.actions:
            c=a['channel'];r=a['response'];p=a['position']
            if not r.get('accepted'):raise SamplingUnavailable('Rejected public action')
            if a['path']=='/measure' and c not in self.cleared:
                obs=(np.array(p),r['measure_result'],r.get('svd_deg'));self.hist[c].append(obs)
                self.belief.observe(c,*obs[:2])
                if obs[1]!='no_signal':self.known.add(c)
            elif a['path']=='/clear' and c not in self.cleared:
                success=r['clear_result']=='success';self.clear_obs[c].append((np.array(p),success))
                if success:self.cleared.add(c);self.known.add(c)
        self.belief.seen=set(self.known)
        self.polys={}
        for c in self.known:
            poly=disk()
            for p,result,angle in self.hist[c]:
                if result=='direction':poly=intersect_disk(wedge(poly,p,angle),p,1500)
                elif result=='near':poly=intersect_disk(poly,p,5)
            for p,success in self.clear_obs[c]:
                if success:poly=intersect_disk(poly,p,20)
            if len(poly)<3:raise SamplingUnavailable('Degenerate known-source support')
            self.polys[c]=poly

    def unknown_subset(self,rng):
        channels=[c for c in range(1,21) if c not in self.known];L=np.array([self.belief.masks[c].mean() for c in channels]);n=len(channels)
        dp=np.zeros((n+1,n+1));dp[n,0]=1.
        for i in range(n-1,-1,-1):
            dp[i]=dp[i+1];dp[i,1:]+=L[i]*dp[i+1,:-1]
        sizes=np.array([N-len(self.known) for N in range(max(10,len(self.known)),17)])
        probs=np.array([dp[0,k]/math.comb(20,k+len(self.known)) for k in sizes]);z=probs.sum()
        if z<=0:raise SamplingUnavailable('No compatible count hypothesis')
        k=int(rng.choice(sizes,p=probs/z));selected=[]
        for i,c in enumerate(channels):
            if not k:break
            probability=L[i]*dp[i+1,k-1]/dp[i,k]
            if rng.random()<probability:selected.append(c);k-=1
        assert k==0
        return selected

    def sample(self,seed):
        rng=np.random.default_rng(seed);sources=[];fields={};proposals=0
        for c in sorted(self.known):
            accepted=None
            for batch in range(8):
                xy=sample_poly(self.polys[c],4096,rng)
                particles=np.c_[xy,rng.uniform(-np.pi,np.pi,len(xy)),rng.uniform(1000,1500,len(xy)),rng.integers(0,2,len(xy))]
                particles=particles[np.linalg.norm(xy,axis=1)<=1800]
                for obs in self.hist[c]:particles=particles[feasible(particles,obs)]
                for p,success in self.clear_obs[c]:
                    distance=np.linalg.norm(particles[:,:2]-p,axis=1);particles=particles[(distance<=20) if success else (distance>20)]
                for particle in particles[:32]:
                    proposals+=1
                    try:field=PairedNoise(particle[:2],self.hist[c],int(rng.integers(2**63)))
                    except ValueError:continue
                    accepted=particle;fields[c]=field;break
                if accepted is not None:break
            if accepted is None:raise SamplingUnavailable(f'No compatible source/noise proposal for channel{c}')
            x,y,phi,radius,kind=accepted;sources.append(Jammer(c,x,y,radius,'directional' if kind else 'omni',np.degrees(phi)))
        for c in self.unknown_subset(rng):
            indexes=np.flatnonzero(self.belief.masks[c]);v=self.belief.states[rng.choice(indexes)]
            x,y,radius,kind,phi=v;sources.append(Jammer(c,x,y,radius,'directional' if kind else 'omni',np.degrees(phi)))
            fields[c]=PairedNoise([x,y],[],int(rng.integers(2**63)))
        engine=SampledEngine(sources,fields)
        for a in self.actions:
            request={} if a['position'] is None else dict(position=dict(zip(['x','y'],a['position'])),channel=a['channel'])
            r=engine.apply(a['path'],request)
            for key,value in a['response'].items():
                if r.get(key)!=value:raise SamplingUnavailable(f'History mismatch: {a["path"]} {key}')
        return engine,dict(proposals=proposals,sampled_count=len(sources),history_actions=len(self.actions))
