"""Development observations and portable return bundles; no Stage07 verdict."""
from pathlib import Path
import csv
import json
import zipfile
import numpy as np
from .execution import inspect_run,code_identity
from .reconstruction import reconstruct
from .events import scan_events
from .trajectory import atomic_json, fingerprint


def summarize_run(run_dir):
    path=Path(run_dir)
    system,trajectory,config=inspect_run(path)
    events=scan_events(system,trajectory)
    atomic_json(path/'event_scan.json',events)
    # Explicitly partial trajectory observations, never competition workbooks.
    step=60 if config.question==1 else 600
    times=np.unique(np.r_[np.arange(0,trajectory.end_time+1e-9,step),trajectory.end_time])
    with (path/'field_observations.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.writer(stream)
        writer.writerow(['time_s','radius_m','axis_T_Celsius','axis_C_kgkg',
                         'surface_T_Celsius','surface_C_kgkg','global_max_C_kgkg','max_location'])
        for t in times:
            rec=reconstruct(system,float(t),trajectory.at(t))
            axis=rec.query(0); surf=rec.surface()
            writer.writerow([t,system.boundary(t).R,axis[0]-273.15,axis[1],surf[0]-273.15,surf[1],rec.max_C,str(rec.max_position)])
    paper_times=([100,300,600,900,1200,1500,1800] if config.question==1 else
                 ([1800,3600,5400,7200,9000,10800] if config.question==23 else
                  list(np.arange(21600,trajectory.end_time+1e-9,21600))))
    with (path/'specified_points.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.writer(stream)
        writer.writerow(['time_s','r_cm','T_Celsius','C_kgkg','domain_status','scope'])
        for t in paper_times:
            if t>trajectory.end_time: continue
            rec=reconstruct(system,t,trajectory.at(t))
            for r in [0,.005,.01,.015,.02]:
                if rec.domain_relation(r)>0:
                    writer.writerow([t,r*100,None,None,'OUTSIDE_DOMAIN','DEVELOPMENT_UNQUALIFIED'])
                else:
                    value=rec.query(r)
                    writer.writerow([t,r*100,value[0]-273.15,value[1],'INSIDE_OR_SURFACE','DEVELOPMENT_UNQUALIFIED'])
    report={'run_id':path.name,'coverage_end':trajectory.end_time,'event':events,
            'postprocessing_source':code_identity(),
            'trajectory_fingerprint':fingerprint(trajectory.index),
            'observations':'field_observations.csv','specified_points':'specified_points.csv',
            'scope':'DEVELOPMENT_OBSERVATIONS_NOT_STAGE07'}
    atomic_json(path/'observation_summary.json',report)
    return report


def compare_q1_development(run_a,run_b,out):
    """Actual early/axis/surface/required-point check; not a global error bound."""
    a,ta,ca=inspect_run(run_a); b,tb,cb=inspect_run(run_b)
    if ca.question!=1 or cb.question!=1 or min(ta.end_time,tb.end_time)<1800:
        raise ValueError('Q1 comparison requires two full 1800 s runs')
    times=np.unique(np.r_[0,.001,.01,.1,1,2,5,10,20,30,np.arange(60,1801,60)])
    radii=np.unique(np.r_[0,.0001,.0005,.001,.005,.01,.015,.019,.0195,.02])
    rows=[]; delta=np.zeros(2); positions=[None,None]
    for t in times:
        ra=reconstruct(a,t,ta.at(t)); rb=reconstruct(b,t,tb.at(t))
        for r in radii:
            ua=np.asarray(ra.query(r)); ub=np.asarray(rb.query(r)); d=np.abs(ua-ub)
            for j in range(2):
                if d[j]>delta[j]: delta[j]=d[j]; positions[j]=[float(t),float(r)]
            rows.append([t,r,*ua,*ub,*d])
    out=Path(out); out.parent.mkdir(parents=True,exist_ok=True)
    with out.with_suffix('.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.writer(stream); writer.writerow(['time_s','r_m','Ta_K','Ca_kgkg','Tb_K','Cb_kgkg','abs_dT_K','abs_dC_kgkg']); writer.writerows(rows)
    report={'scope':'DEVELOPMENT_SAMPLED_Q1_COMPARISON_NOT_GLOBAL_ERROR_BOUND',
            'runs':[str(run_a),str(run_b)],'nr':[ca.nr,cb.nr],
            'max_sampled_dT_K':delta[0],'max_sampled_dC_kgkg':delta[1],
            'maximum_locations_t_r':positions,'rows':len(rows),
            'sample_budgets_passed':bool(delta[0]<=.05 and delta[1]<=.0005),
            'strict_error_certified':False,'four_decimal_accuracy_claimed':False}
    atomic_json(out,report)
    return report


def pack_return(root,out,full=False):
    root=Path(root).resolve(); out=Path(out).resolve()
    if out.exists(): raise FileExistsError(out)
    out.parent.mkdir(parents=True,exist_ok=True)
    files=[]
    for p in sorted(root.rglob('*')):
        if not p.is_file() or p.resolve()==out or p.name.endswith('.tmp') or p.name=='.campaign.lock': continue
        rel=p.relative_to(root)
        if not full and any(x in rel.parts for x in ['trajectory','checkpoints','source_snapshot','__pycache__']): continue
        if not full and p.name in ['checkpoint.json','steps.jsonl']: continue
        files.append((p,rel))
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for p,rel in files: z.write(p,str(rel))
    with zipfile.ZipFile(out) as z:
        if z.testzip() is not None: raise ValueError('return ZIP integrity failure')
    return {'path':str(out),'files':len(files),'full':full,'bytes':out.stat().st_size}
