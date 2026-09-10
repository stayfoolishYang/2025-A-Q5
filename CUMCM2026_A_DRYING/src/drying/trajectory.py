"""Bounded-memory accepted trajectory and atomic restart files."""
from __future__ import annotations
from pathlib import Path
import json
import os
import hashlib
import numpy as np


def atomic_json(path, obj):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    with temp.open('w',encoding='utf-8') as f:
        json.dump(obj,f,ensure_ascii=False,indent=2,allow_nan=False)
        f.write('\n'); f.flush(); os.fsync(f.fileno())
    json.loads(temp.read_text(encoding='utf-8'))
    temp.replace(path)


def fingerprint(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


class TrajectoryWriter:
    def __init__(self,path,identity,chunk_size=256,resume=False):
        self.path=Path(path); self.path.mkdir(parents=True,exist_ok=True)
        self.index_path=self.path/'index.json'; self.chunk_size=chunk_size
        self.buffer=[]
        if self.index_path.exists():
            if not resume: raise FileExistsError(self.index_path)
            self.index=json.loads(self.index_path.read_text(encoding='utf-8'))
            if self.index['identity']!=identity: raise ValueError('trajectory identity mismatch')
        else:
            self.index={'identity':identity,'chunks':[],'size':None,'count':0}
            atomic_json(self.index_path,self.index)
        self.last_time=self.index['chunks'][-1]['end'] if self.index['chunks'] else None

    def append(self,t,y):
        t=float(t); y=np.asarray(y,dtype=np.float64)
        if self.last_time is not None and t<=self.last_time: raise ValueError('trajectory times must increase')
        if not np.all(np.isfinite(y)): raise ValueError('nonfinite trajectory')
        if self.index['size'] is None: self.index['size']=int(y.size)
        if y.size!=self.index['size']: raise ValueError('trajectory state size mismatch')
        self.buffer.append((t,y.copy())); self.last_time=t
        if len(self.buffer)>=self.chunk_size: self.flush()

    def flush(self):
        if not self.buffer: return
        number=len(self.index['chunks'])
        name=f'chunk_{number:06d}.npz'; dest=self.path/name
        while dest.exists():
            number+=1; name=f'chunk_{number:06d}.npz'; dest=self.path/name
        times=np.array([t for t,y in self.buffer]); values=np.array([y for t,y in self.buffer])
        with dest.with_suffix('.tmp').open('wb') as f:
            np.savez_compressed(f,t=times,y=values); f.flush(); os.fsync(f.fileno())
        dest.with_suffix('.tmp').replace(dest)
        digest=hashlib.sha256(dest.read_bytes()).hexdigest()
        self.index['chunks'].append({'file':name,'start':float(times[0]),'end':float(times[-1]),'count':len(times),'sha256':digest})
        self.index['count']+=len(times)
        atomic_json(self.index_path,self.index); self.buffer.clear()


class Trajectory:
    def __init__(self,path,verify=False):
        self.path=Path(path)
        self.index=json.loads((self.path/'index.json').read_text(encoding='utf-8'))
        self.chunks=self.index['chunks']
        if not self.chunks: raise ValueError('empty trajectory')
        self.start_time=self.chunks[0]['start']; self.end_time=self.chunks[-1]['end']
        self._cache={}
        if verify:
            for item in self.chunks:
                if hashlib.sha256((self.path/item['file']).read_bytes()).hexdigest()!=item['sha256']:
                    raise ValueError('trajectory chunk hash mismatch')

    def _read(self,i):
        if i not in self._cache:
            with np.load(self.path/self.chunks[i]['file'],allow_pickle=False) as a:
                self._cache[i]=(a['t'].copy(),a['y'].copy())
            if len(self._cache)>3: del self._cache[next(iter(self._cache))]
        return self._cache[i]

    def iter_states(self):
        for i in range(len(self.chunks)):
            times,ys=self._read(i)
            yield from zip(times,ys)

    def iter_segments(self):
        previous=None
        for t,y in self.iter_states():
            if previous is not None: yield previous[0],previous[1],float(t),y
            previous=(float(t),y)

    def at(self,t):
        t=float(t)
        if t<self.start_time or t>self.end_time: raise ValueError('OUT_OF_COVERAGE')
        i=int(np.searchsorted([c['end'] for c in self.chunks],t,side='left'))
        times,ys=self._read(i)
        j=int(np.searchsorted(times,t,side='left'))
        if j<len(times) and times[j]==t: return ys[j].copy()
        if j==0:
            older_t,older_y=self._read(i-1)
            ta,ya=older_t[-1],older_y[-1]
        else: ta,ya=times[j-1],ys[j-1]
        tb,yb=times[j],ys[j]
        return ya+(t-ta)/(tb-ta)*(yb-ya)


def recover_trajectory(path, checkpoint_time):
    """Roll the active index back to a durable checkpoint, retaining crash data.

    Immutable old chunks and the archived old index remain available for audit.
    A partial last chunk gets a new filename; no committed chunk is overwritten.
    """
    path=Path(path)
    trajectory=Trajectory(path,verify=True)
    if trajectory.end_time==checkpoint_time: return False
    if trajectory.end_time<checkpoint_time: raise ValueError('trajectory behind checkpoint')
    archive=path/'recovery_index_rev001.json'
    rev=1
    while archive.exists():
        rev+=1; archive=path/f'recovery_index_rev{rev:03d}.json'
    atomic_json(archive,trajectory.index)
    kept=[]
    for i,item in enumerate(trajectory.chunks):
        if item['end']<=checkpoint_time: kept.append(item); continue
        if item['start']>checkpoint_time: break
        times,ys=trajectory._read(i); mask=times<=checkpoint_time
        if not mask.any(): break
        ts=times[mask]; values=ys[mask]
        name=f'recovery_rev{rev:03d}_chunk.npz'
        dest=path/name
        with dest.open('xb') as stream:
            np.savez_compressed(stream,t=ts,y=values); stream.flush(); os.fsync(stream.fileno())
        kept.append({'file':name,'start':float(ts[0]),'end':float(ts[-1]),'count':len(ts),
                     'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
        break
    if not kept or kept[-1]['end']!=checkpoint_time:
        raise ValueError('checkpoint time is not an accepted trajectory node')
    index=dict(trajectory.index,chunks=kept,count=sum(c['count'] for c in kept))
    atomic_json(path/'index.json',index)
    return True


def save_checkpoint(path,integrator,identity,extra=None):
    atomic_json(path,{'identity':identity,'integrator':integrator.snapshot(),'extra':extra or {}})


def load_checkpoint(path,integrator,identity):
    obj=json.loads(Path(path).read_text(encoding='utf-8'))
    if obj['identity']!=identity: raise ValueError('checkpoint input/config/source mismatch')
    integrator.restore(obj['integrator'])
    return obj['extra']
