"""Experimental independent-grid posterior; R12 and production sampler untouched."""
import math
import numpy as np
from scipy.special import logsumexp
from world_sampler_v2 import WorldSampler,SamplingUnavailable,SampledEngine,Jammer
from paired_noise_v2 import PairedNoise
from geometry import sample_poly
from particles import feasible
from grid_measure import GridMeasure,summarize

class WeightedWorldSampler(WorldSampler):
    def sample(self,seed,source_count=128,noise_count=256):
        rng=np.random.default_rng(seed);sources=[];fields={};diagnostics={}
        for c in sorted(self.known):
            proposals=[]
            for _ in range(16):
                xy=sample_poly(self.polys[c],4096,rng)
                ps=np.c_[xy,rng.uniform(-np.pi,np.pi,len(xy)),rng.uniform(1000,1500,len(xy)),rng.integers(0,2,len(xy))]
                ps=ps[np.linalg.norm(xy,axis=1)<=1800]
                for obs in self.hist[c]:ps=ps[feasible(ps,obs)]
                for p,success in self.clear_obs[c]:
                    d=np.linalg.norm(ps[:,:2]-p,axis=1);ps=ps[(d<=20) if success else (d>20)]
                proposals.extend(ps.tolist())
                if len(proposals)>=source_count:break
            proposals=np.array(proposals[:source_count])
            if len(proposals)<source_count:raise SamplingUnavailable('Incomplete source proposal bank')
            banks=[];logs=[];stats=[]
            for particle in proposals:
                model=GridMeasure(particle[:2],self.hist[c]);X,weights=model.draw_pivot(noise_count,int(rng.integers(2**63)))
                st=summarize(weights);st.update(impossible=model.impossible,dimension=len(model.keys),constraints=len(model.lo));stats.append(st);logs.append(st['log_volume'])
                if st['positive']:
                    k=rng.choice(noise_count,p=np.exp(weights-logsumexp(weights)))
                    banks.append(dict(zip(model.keys,X[k])))
                else:banks.append(None)
            z=logsumexp(logs)
            if not np.isfinite(z):
                error=SamplingUnavailable(f'Zero joint importance weight channel {c}')
                error.diagnostics=dict(channel=c,proposals=proposals.tolist(),noise_stats=stats,history=[(p.tolist(),r,a) for p,r,a in self.hist[c]])
                raise error
            w=np.exp(np.array(logs)-z);selected=int(rng.choice(len(proposals),p=w))
            x,y,phi,radius,kind=proposals[selected]
            sources.append(Jammer(c,x,y,radius,'directional' if kind else 'omni',np.degrees(phi)))
            field=PairedNoise.__new__(PairedNoise);field.seed=int(rng.integers(2**63));field.grid=banks[selected];fields[c]=field
            diagnostics[c]=dict(source_ess=float(1/(w@w)),source_proposals=len(proposals),noise_samples=noise_count,selected_noise_ess=stats[selected]['ess'],zero_source_weights=sum(not s['positive'] for s in stats))
        for c in self.unknown_subset(rng):
            indexes=np.flatnonzero(self.belief.masks[c]);v=self.belief.states[rng.choice(indexes)]
            x,y,radius,kind,phi=v;sources.append(Jammer(c,x,y,radius,'directional' if kind else 'omni',np.degrees(phi)))
            fields[c]=PairedNoise([x,y],[],int(rng.integers(2**63)))
        engine=SampledEngine(sources,fields)
        for a in self.actions:
            request={} if a['position'] is None else dict(position=dict(zip(['x','y'],a['position'])),channel=a['channel'])
            response=engine.apply(a['path'],request)
            if any(response.get(k)!=v for k,v in a['response'].items()):raise SamplingUnavailable('Weighted world failed exact replay')
        return engine,dict(channels=diagnostics,history_actions=len(self.actions),sampled_count=len(sources))
