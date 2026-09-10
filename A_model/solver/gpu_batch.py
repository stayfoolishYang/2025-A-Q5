"""Batched FP64 reference using installed PyTorch CUDA; no single-path DataParallel.

Small dense solves deliberately reuse torch.linalg instead of adding a raw kernel.
Each process sees one GPU; shard sample rows with --worker/--workers on a server.
"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import argparse
import json
import time
import numpy as np
import torch
from physics.boundary import Boundary
from physics.material import GX,GW
from solver.fvm_cpu import solve

def batch(scales,n=21,dt=60.,end=432000.,device='cuda',dtype=torch.float64):
    sc=torch.as_tensor(scales,dtype=dtype,device=device)
    B=len(sc); T=torch.full((B,n),28.,dtype=dtype,device=device); C=torch.full_like(T,2.55)
    faces=torch.as_tensor((np.arange(n-1)+.5)/(n-1),device=device,dtype=dtype)
    f=torch.cat((torch.zeros(1,device=device,dtype=dtype),faces,torch.ones(1,device=device,dtype=dtype)))
    V=.5*(f[1:]**2-f[:-1]**2)*.02**2
    gx=torch.as_tensor(GX,device=device,dtype=dtype); gw=torch.as_tensor(GW,device=device,dtype=dtype)
    amb=torch.as_tensor(Boundary().ambient(np.arange(int(end/dt)+1)*dt),device=device,dtype=dtype)
    events=torch.full((B,),float('nan'),device=device,dtype=dtype)
    maxiterations=0
    def linear(p,cap,old,h,a,face=False):
        pf=p if face else 2*p[:,:-1]*p[:,1:]/(p[:,:-1]+p[:,1:])
        G=pf*faces*(n-1)
        diag=cap*V/dt
        diag=diag.clone(); diag[:,:-1]+=G; diag[:,1:]+=G; diag[:,-1]+=.02*h
        rhs=cap*V*old/dt; rhs=rhs.clone(); rhs[:,-1]+=.02*h*a
        matrix=torch.diag_embed(diag)+torch.diag_embed(-G,offset=1)+torch.diag_embed(-G,offset=-1)
        return torch.linalg.solve(matrix,rhs.unsqueeze(-1)).squeeze(-1)
    for j in range(1,len(amb)):
        oldT,oldC=T.clone(),C.clone()
        for it in range(120):
            cap=(650+128*C)*(1450+2736*C/(C+1))
            k=(.21+.38*C/(C+1))*sc[:,3,None]
            cq=C[:,:-1,None]*(1-gx)+C[:,1:,None]*gx
            tq=T[:,:-1,None]*(1-gx)+T[:,1:,None]*gx+273.15
            D=(2.4e-3*torch.exp(-.45/cq-3850/tq)*gw).sum(-1)*sc[:,0,None]
            Tn=linear(k,cap,oldT,25*sc[:,2],amb[j,0])
            Cn=linear(D,torch.ones_like(C),oldC,8e-7*sc[:,1],amb[j,1],True)
            error=torch.maximum((Tn-T).abs().max()/1e-7,(Cn-C).abs().max()/1e-9)
            T,C=Tn,Cn
            if error.item()<1: break
        else: raise RuntimeError('GPU Picard failed')
        maxiterations=max(maxiterations,it+1)
        before,after=oldC.max(1).values,C.max(1).values
        hit=torch.isnan(events)&(after<=.15)
        interpolated=(j-1)*dt+dt*(before-.15)/(before-after)
        events=torch.where(hit,interpolated,events)
        if j%500==0: print(f'GPU {j*dt/3600:.1f} h',flush=True)
        if torch.all(torch.isfinite(events)).item(): break
    if not torch.all(torch.isfinite(T)).item() or C.min().item()<=0:
        raise RuntimeError('Invalid GPU output')
    return T.cpu().numpy(),C.cpu().numpy(),events.cpu().numpy(),j*dt,maxiterations

def main():
    p=argparse.ArgumentParser();p.add_argument('--worker',type=int,default=0);p.add_argument('--workers',type=int,default=1)
    p.add_argument('--batch',type=int,default=8);p.add_argument('--end',type=float,default=432000.);p.add_argument('--dt',type=float,default=60.)
    a=p.parse_args()
    if not torch.cuda.is_available(): raise RuntimeError('CUDA unavailable; use a CUDA PyTorch environment')
    from scipy.stats import qmc
    samples=.8+.4*qmc.LatinHypercube(4,seed=2026).random(a.batch)
    samples[0]=1.;samples=samples[a.worker::a.workers]
    if len(samples)==0: raise ValueError('Worker has no samples')
    torch.cuda.synchronize(); start=time.perf_counter()
    T,C,events,final_t,it=batch(samples,dt=a.dt,end=a.end)
    torch.cuda.synchronize();wall=time.perf_counter()-start
    # Full CPU trajectories at matching n/dt isolate backend discrepancies.
    errors=[];cpu_start=time.perf_counter()
    for s,t,c in zip(samples,T,C):
        data,meta=solve(n=21,dt=a.dt,end=final_t,interval=final_t,event=False,scales=s)
        errors.append([float(np.max(abs(data[-1,2:23]-t))),float(np.max(abs(data[-1,23:]-c)))])
    cpu_wall=time.perf_counter()-cpu_start
    assert np.max(np.asarray(errors),axis=0)[0]<1e-5 and np.max(np.asarray(errors),axis=0)[1]<1e-7
    result=dict(device=torch.cuda.get_device_name(),torch=torch.__version__,dtype='float64',n=21,dt=a.dt,
                samples=samples.tolist(),event_s_linear=events.tolist(),event_method='linear interpolation within dt; CPU main results use bisection',
                final_time_s=final_t,max_iterations=it,gpu_wall_s=wall,cpu_wall_s=cpu_wall,
                max_backend_errors=errors,scope='Q3 fixed-domain full coupled batches; Q4 runs on CPU')
    target=Path(__file__).resolve().parents[1]/'results'/f'gpu_worker_{a.worker}.json'
    target.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))

if __name__=='__main__': main()
