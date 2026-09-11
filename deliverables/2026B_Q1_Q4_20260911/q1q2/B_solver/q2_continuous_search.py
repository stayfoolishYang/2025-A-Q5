"""Frozen local Q2 station search. No simulator or client is imported."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import platform
import time
import numpy as np
from q2_scoring import adaptive_score
from q2_visibility import (exact_disk, explicit_safe_inner_region_q0, direction_region_q5,
                           floating_disks, boundary_distance, verify_guaranteed_reception)

BASE = Path(__file__).resolve().parent
PLAN = dict(top_k=5, steps_m=[50,20,10,5,2,1], eps_J_m=.05, eps_q_m=2.,
            lambda_m_per_s=.2, inner_gap_m=.01, boundary_inset_m=.0001,
            acceptance_relative_J=.01, acceptance_interval_margin_m=.1,
            initial_x=[0,1500,50], initial_y=[-1000,1000,40], workers=4,
            main_example_only=True, official_calls=0, parent_separation_m=50.,
            group_new_score_cap=2000, wall_budget_s=2700,
            final_review_reserved_scores_per_group=150, final_inner_gap_m=.001,
            final_half_step_m=.5, auto_adopt=False, auto_push=False)
ANGLE = np.deg2rad(30.)
BASIS = np.array([[np.cos(ANGLE),-np.sin(ANGLE)],[np.sin(ANGLE),np.cos(ANGLE)]])


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')


def write_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def baseline():
    data = json.loads((BASE/'results/q2.json').read_text(encoding='utf-8'))
    with (BASE/'results/q2_candidates.csv').open(encoding='utf-8-sig') as stream:
        rows = list(csv.DictReader(stream))
    poly = np.array(data['polygon'])
    points = [np.array([float(row['x']),float(row['y'])]) for row in rows]
    index = min(range(len(rows)),key=lambda i:float(rows[i]['worst_sampled_diameter_m'])+.2*float(rows[i]['action_time_s']))
    anchor = points[index]
    return poly, points, anchor


def regions(poly):
    return dict(Csafe=[exact_disk(v) for v in poly],
                Q0=explicit_safe_inner_region_q0(), Q5=direction_region_q5())


def point_key(q):
    return ','.join(float(v).hex() for v in q)


def circle_intersections(c, r, d, s):
    delta = d-c
    length = float(np.linalg.norm(delta))
    if length == 0 or length > r+s or length < abs(r-s):
        return []
    along = (r*r-s*s+length*length)/(2*length)
    height = math.sqrt(max(0.,r*r-along*along))
    foot = c+along*delta/length
    normal = np.array([-delta[1],delta[0]])/length
    return [foot+height*normal, foot-height*normal]


def boundary_proposals(disks, anchor, step, parents=None, previous=50):
    floats = floating_disks(disks)
    proposals = []
    for i,(c,r) in enumerate(floats):
        if parents is None:
            angles = [(z,'global_boundary') for z in np.linspace(0,2*np.pi,math.ceil(2*np.pi*r/step),endpoint=False)]
        else:
            n = math.floor(previous/step)
            angles = [(math.atan2(*(q-c)[::-1])+offset*step/r,key)
                      for key,q in parents for offset in range(-n,n+1)]
        proposals.extend((c+r*np.array([math.cos(z),math.sin(z)]),parent) for z,parent in angles)
        if parents is None:
            for d,s in floats[i+1:]:
                proposals.extend((q,'circle_intersection') for q in circle_intersections(c,r,d,s))
    result = []
    for q,parent in proposals:
        distance = float(np.linalg.norm(anchor-q))
        if distance:
            q = q+min(1.,PLAN['boundary_inset_m']/distance)*(anchor-q)
        result.append((q,parent))
    return result


def refinement_proposals(parents, disks, anchor, step, previous):
    n = math.floor(previous/step)
    proposals = [(q+np.array([i*step,j*step])@BASIS.T,key)
                 for key,q in parents for i in range(-n,n+1) for j in range(-n,n+1)]
    return proposals+boundary_proposals(disks,anchor,step,parents,previous)


def separated_parents(ordered, admitted):
    parents = []
    for key in ordered:
        q = admitted[key]
        if all(np.linalg.norm(q-other)>=PLAN['parent_separation_m'] for _,other in parents):
            parents.append((key,q))
            if len(parents) == PLAN['top_k']:
                break
    return parents


def run(output, modes):
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    poly, legacy, anchor = baseline()
    region_map = regions(poly)
    names = {'M0':'Csafe','M1':'Csafe','M2':'Q0','M3':'Q5'}
    sources = ['q2_scoring.py','q2_visibility.py','q2_continuous_search.py',
               'Q2_CONTINUOUS_SEARCH_PLAN.md','geometry.py','experiments/q2_score_audit.py',
               'results/q2.json','results/q2_candidates.csv']
    hashes = {name:hashlib.sha256((BASE/name).read_bytes()).hexdigest() for name in sources}
    head = subprocess.check_output(['git','rev-parse','HEAD'],cwd=BASE,text=True).strip()
    write_json(output/'FROZEN.json',dict(plan=PLAN,head=head,source_sha256=hashes,modes=modes,
                                      mathematical_scope='main full direction annular sector'))
    write_json(output/'plan.json',PLAN)
    write_json(output/'environment.json',dict(python=sys.version,executable=sys.executable,
                                             numpy=np.__version__,platform=platform.platform(),head=head))
    context = hashlib.sha256(json.dumps(dict(hashes=hashes,plan=PLAN),sort_keys=True).encode()).hexdigest()
    cache, certificates, trajectory, rejected = {}, {}, [], []
    mode_winners, mode_pools = {}, {}
    final_review = []
    budget_used = {'A':0,'B':0,'C':0}
    mode_timings, budget_limited = {}, False
    with ProcessPoolExecutor(max_workers=PLAN['workers']) as pool:
        for mode in modes:
            mode_started = time.perf_counter()
            group = 'A' if mode=='M0' else ('B' if mode=='M1' else 'C')
            name = names[mode]
            disks = region_map[name]
            admitted, previous_best = {}, None
            for level,step in enumerate(PLAN['steps_m'] if mode!='M0' else [50]):
                if level == 0:
                    proposals = [(q,'legacy_213') for q in legacy]
                    if mode in ('M2','M3'):
                        proposals += [(q,'retained_B_pool') for q in mode_pools.get('M1',{}).values()]
                    if mode == 'M3':
                        proposals += [(q,'retained_Q0_pool') for q in mode_pools.get('M2',{}).values()]
                    if mode != 'M0':
                        proposals += [(np.array([x,y])@BASIS.T,'coarse_grid')
                                      for x in range(0,1501,50) for y in range(-1000,1001,40)]
                        proposals += boundary_proposals(disks,anchor,step)
                else:
                    ordered = sorted(admitted, key=lambda k:(cache[k]['D_upper_m']+.2*np.linalg.norm(admitted[k])/5, k))
                    parents = separated_parents(ordered,admitted)
                    proposals = refinement_proposals(parents,disks,anchor,step,PLAN['steps_m'][level-1])
                selected = {}
                for q,parent in proposals:
                    key = context+'|'+point_key(q)
                    if key in selected:
                        continue
                    # Float prefilter only rejects proposals; it never certifies one.
                    if boundary_distance(q,disks) < -1e-7:
                        rejected.append(dict(mode=mode,level=level,x=q[0],y=q[1],parent=parent,reason='float_prefilter'))
                        continue
                    if key not in certificates:
                        certificates[key] = {n:verify_guaranteed_reception(q,d) for n,d in region_map.items()}
                    cert = certificates[key]
                    if not cert[name]['verified'] or not cert['Q5']['verified']:
                        rejected.append(dict(mode=mode,level=level,x=q[0],y=q[1],parent=parent,reason='hard_verifier_rejected'))
                        continue
                    if key not in cache and (budget_used[group]+sum(k not in cache for k in selected)>=
                       PLAN['group_new_score_cap']-PLAN['final_review_reserved_scores_per_group'] or
                       time.perf_counter()-started>=PLAN['wall_budget_s']):
                        budget_limited = True
                        rejected.append(dict(mode=mode,level=level,x=q[0],y=q[1],parent=parent,reason='budget_limit'))
                        continue
                    selected[key] = (q,parent)
                    admitted[key] = q
                new = [key for key in selected if key not in cache]
                for key,score in zip(new,pool.map(adaptive_score,[(selected[k][0],poly) for k in new],chunksize=8)):
                    cache[key] = score
                budget_used[group] += len(new)
                order = sorted(admitted, key=lambda k:(cache[k]['D_upper_m']+.2*(np.linalg.norm(admitted[k])/5+5), k))
                ranks = {k:i+1 for i,k in enumerate(order)}
                rows = []
                for key,(q,parent) in selected.items():
                    score = cache[key]
                    action_time = float(np.linalg.norm(q)/5+5)
                    cert = certificates[key]
                    rows.append(dict(mode=mode,region=name,level=level,step_m=step,key=key,x=q[0],y=q[1],
                                     parent=parent,rank_cumulative=ranks[key],in_Csafe=cert['Csafe']['verified'],
                                     in_Q0=cert['Q0']['verified'],in_Qvis_Q5=cert['Q5']['verified'],
                                     squared_slack_lower_m2=cert[name]['squared_slack_lower_m2'],
                                     boundary_distance_m=boundary_distance(q,disks),
                                     D_lower_m=score['D_lower_m'],D_upper_m=score['D_upper_m'],
                                     inner_gap_m=score['inner_gap_m'],T_s=action_time,
                                     J_lower_m=score['D_lower_m']+.2*action_time,
                                     J_upper_m=score['D_upper_m']+.2*action_time,
                                     near_possible=score['near_possible'],near_upper_m=score['near_upper_m'],
                                     score_elapsed_s=score['elapsed_s'],safety_status=cert[name]['status']))
                rows.sort(key=lambda r:r['rank_cumulative'])
                write_csv(output/f'{mode}_level_{level}.csv',rows)
                key = order[0]
                q = admitted[key]
                score = cache[key]
                action_time = float(np.linalg.norm(q)/5+5)
                best = dict(mode=mode,region=name,level=level,step_m=step,candidate_count=len(rows),
                            cumulative_count=len(admitted),new_score_count=len(new),key=key,x=q[0],y=q[1],
                            D_lower_m=score['D_lower_m'],D_upper_m=score['D_upper_m'],T_s=action_time,
                            J_lower_m=score['D_lower_m']+.2*action_time,J_upper_m=score['D_upper_m']+.2*action_time,
                            inner_gap_m=score['inner_gap_m'],boundary_distance_m=boundary_distance(q,disks),
                            delta_J_m=0.,delta_q_m=0.,
                            stop_reason='BUDGET_LIMITED' if budget_limited else ('MIN_STEP' if step==1 else 'CONTINUE'))
                if previous_best:
                    best['delta_J_m'] = best['J_upper_m']-previous_best['J_upper_m']
                    best['delta_q_m'] = float(np.linalg.norm(q-np.array([previous_best['x'],previous_best['y']])))
                trajectory.append(best)
                previous_best = best
                print(json.dumps(best),flush=True)
            mode_winners[mode] = best
            mode_pools[mode] = admitted
            mode_timings[mode] = time.perf_counter()-mode_started
        # Prespecified half-step cross-checks, then independent finer inner audits.
        for mode,best in mode_winners.items():
            if time.perf_counter()-started>=PLAN['wall_budget_s']:
                budget_limited = True
                break
            group = 'A' if mode=='M0' else ('B' if mode=='M1' else 'C')
            disks = region_map[names[mode]]
            q = np.array([best['x'],best['y']])
            proposals = ([(q,'serialized_finalist')] if mode=='M0' else
                         refinement_proposals([('finalist',q)],disks,anchor,.5,1.))
            verified_points = {}
            for point,parent in proposals:
                key = context+'|'+point_key(point)
                cert = verify_guaranteed_reception(point,disks)
                if cert['verified'] and verify_guaranteed_reception(point,region_map['Q5'])['verified']:
                    verified_points[key] = (point,parent,cert)
            new = [key for key in verified_points if key not in cache]
            remaining = PLAN['group_new_score_cap']-budget_used[group]
            if len(new)>remaining:
                new = new[:remaining]
                budget_limited = True
            for key,score in zip(new,pool.map(adaptive_score,[(verified_points[k][0],poly) for k in new],chunksize=8)):
                cache[key] = score
            budget_used[group] += len(new)
            available = [key for key in verified_points if key in cache]
            local_key = min(available,key=lambda k:cache[k]['D_upper_m']+.2*(np.linalg.norm(verified_points[k][0])/5+5))
            local_q = verified_points[local_key][0]
            # Always re-evaluate the serialized table winner and the half-step winner at .001 m.
            for role,point in [('table_finalist',q),('half_step_best',local_q)]:
                if budget_used[group]>=PLAN['group_new_score_cap']:
                    budget_limited = True
                    continue
                serialized = np.array(json.loads(json.dumps(point.tolist())))
                cert = verify_guaranteed_reception(serialized,disks)
                if not cert['verified'] or not verify_guaranteed_reception(serialized,region_map['Q5'])['verified']:
                    raise ArithmeticError('Serialized finalist lost reception certificate')
                score = adaptive_score((serialized,poly,PLAN['final_inner_gap_m']))
                budget_used[group] += 1
                action_time = float(np.linalg.norm(serialized)/5+5)
                final_review.append(dict(mode=mode,role=role,x=serialized[0],y=serialized[1],
                                         certificate=cert,score=score,T_s=action_time,
                                         J_lower_m=score['D_lower_m']+.2*action_time,
                                         J_upper_m=score['D_upper_m']+.2*action_time,
                                         half_step_delta_q_m=float(np.linalg.norm(local_q-q))))
            review_rows = []
            for key in available:
                point,parent,cert = verified_points[key]
                score = cache[key]
                action_time = float(np.linalg.norm(point)/5+5)
                review_rows.append(dict(mode=mode,source=parent,x=point[0],y=point[1],key=key,
                                        safety_status=cert['status'],step_m=.5,
                                        D_lower_m=score['D_lower_m'],D_upper_m=score['D_upper_m'],T_s=action_time,
                                        J_lower_m=score['D_lower_m']+.2*action_time,
                                        J_upper_m=score['D_upper_m']+.2*action_time,
                                        inner_gap_m=score['inner_gap_m'],score_elapsed_s=score['elapsed_s']))
            write_csv(output/f'{mode}_half_step.csv',review_rows)
    write_json(output/'FINAL_REVIEW.json',final_review)
    write_csv(output/'refinement.csv',trajectory)
    if rejected:
        write_csv(output/'rejected_proposals.csv',rejected)
    with gzip.open(output/'inner_scores.json.gz','wt',encoding='utf-8') as stream:
        json.dump(cache,stream,allow_nan=False)
    disk_evidence = {name:[dict(center_intervals=[[str(lo),str(hi)] for lo,hi in d['center']],
                                radius=str(d['radius'])) for d in disks] for name,disks in region_map.items()}
    write_json(output/'RECEPTION_DISKS.json',disk_evidence)
    write_json(output/'COMPLETED.json',dict(head=head,elapsed_s=time.perf_counter()-started,
                                          unique_scores=len(cache),winners=mode_winners,
                                          posterior_evaluations=sum(v['posterior_evaluations'] for v in cache.values()),
                                          max_clip_residual_m=max(v['max_clip_residual_m'] for v in cache.values()),
                                          max_inner_gap_m=max(v['inner_gap_m'] for v in cache.values()),
                                          rejected_proposals=len(rejected),official_calls=0,
                                          budget_used=budget_used,budget_limited=budget_limited,
                                          mode_wall_s=mode_timings,cache_context=context))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--q2-candidate-mode',choices=['legacy_213','adaptive_safe_region'],default='adaptive_safe_region')
    args = parser.parse_args()
    run(args.output,['M0'] if args.q2_candidate_mode=='legacy_213' else ['M0','M1','M2','M3'])
