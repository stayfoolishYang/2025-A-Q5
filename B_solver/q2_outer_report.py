"""Prepare and independently summarize the local Q2 experiment evidence."""
import argparse
import ast
import csv
from decimal import Decimal as D, localcontext
import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import shutil
import zipfile
import numpy as np
from q2_continuous_search import baseline, PLAN, write_json, write_csv, regions
from q2_scoring import adaptive_score
from q2_visibility import verify_guaranteed_reception, boundary_distance, floating_disks
from geometry import ERROR_DEG

BASE = Path(__file__).resolve().parent
INITIAL_HEAD = '7c90ba18c863d7bb99266ad992dbe5d648a46426'


def protected_state():
    paths = subprocess.check_output(['git','ls-tree','-r','--name-only',INITIAL_HEAD,'B_solver'],cwd=BASE.parent,text=True).splitlines()
    paths = [p for p in paths if Path(p).suffix in ('.py','.cu','.cpp','.hpp','.h','.toml') and p!='B_solver/questions.py']
    paths += ['B_solver/results/q2.json','B_solver/results/q2_candidates.csv']
    state = {}
    for path in paths:
        old = subprocess.check_output(['git','show',INITIAL_HEAD+':'+path],cwd=BASE.parent)
        current = (BASE.parent/path).read_bytes()
        state[path] = dict(before=hashlib.sha256(old).hexdigest(),after=hashlib.sha256(current).hexdigest())
    source = (BASE/'questions.py').read_text(encoding='utf-8')
    original = subprocess.check_output(['git','show',INITIAL_HEAD+':B_solver/questions.py'],cwd=BASE.parent,text=True)
    def q1_hash(text):
        function = next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=='solve_q1')
        return hashlib.sha256(ast.dump(function,include_attributes=False).encode()).hexdigest()
    state['B_solver/questions.py::solve_q1_AST'] = dict(before=q1_hash(original),after=q1_hash(source))
    if not all(v['before']==v['after'] for v in state.values()):
        raise AssertionError('Protected file changed')
    return state


def prepare(root):
    root.mkdir(parents=True,exist_ok=True)
    write_json(root/'PROTECTED_BEFORE.json',protected_state())
    poly,points,_ = baseline()
    pilot = []
    for index in (0,106,176):
        score = adaptive_score((points[index],poly))
        pilot.append(dict(legacy_index=index,elapsed_s=score['elapsed_s'],
                          posterior_evaluations=score['posterior_evaluations'],inner_gap_m=score['inner_gap_m']))
    write_json(root/'PILOT_COST.json',dict(points=pilot,used_for_parameter_tuning=False,
                                         planned_parameters=PLAN,official_calls=0))
    tests = subprocess.run([sys.executable,str(BASE/'tests/test_q2_continuous_search.py')],capture_output=True,text=True)
    (root/'TESTS_BEFORE.txt').write_text(tests.stdout+tests.stderr,encoding='utf-8')
    if tests.returncode:
        raise RuntimeError(tests.stdout+tests.stderr)
    print(json.dumps(dict(pilot=pilot,tests_passed=25,protected_files_unchanged=True)))


def read_csv(path):
    with path.open(encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def independent_reception(q, poly):
    """80-digit independent cross-check, explicitly NOT an interval certificate."""
    with localcontext() as context:
        context.prec = 80
        pi = D('3.141592653589793238462643383279502884197169399375105820974944592307816406286208998628')
        h = [D.from_float(float(v)) for v in q]
        k = sum(v*v for v in h)
        witnesses = []
        for angle in [D(30)-D.from_float(ERROR_DEG),D(30)+D.from_float(ERROR_DEG)]:
            x = angle*pi/180
            cosine = sum(((-1)**j*x**(2*j)/D(math.factorial(2*j)) for j in range(50)),D(0))
            sine = sum(((-1)**j*x**(2*j+1)/D(math.factorial(2*j+1)) for j in range(50)),D(0))
            dot = h[0]*cosine+h[1]*sine
            for r in [D(5),D(1000),D(1500)]:
                value = k-2*r*dot+r*r-max(D(1000)**2,r*r)
                witnesses.append(dict(F_m2=str(value),source=[str(r*cosine),str(r*sine)],
                                      radius_m=str(r),angle_deg=str(angle),
                                      witness_kind='closure_supremum' if r==5 else 'bounded_model_position'))
        worst = max(witnesses,key=lambda w:D(w['F_m2']))
        old_F = max(sum((h[i]-D.from_float(float(v[i])))**2 for i in (0,1))-D(1000)**2 for v in poly)
        return dict(method='independent Decimal80 Taylor; not a strict interval certificate',
                    q5_max_F_m2=worst['F_m2'],worst_bounded_source=worst,
                    old_Csafe_max_F_m2=str(old_F),q5_pass=D(worst['F_m2'])<=0)


def make_plots(run, output, table, rows):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon
    poly,legacy,_ = baseline()
    regs = regions(poly)
    colors = {'Csafe':'#6c7183','Q0':'#c07713','Q5':'#008c83'}
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes = plt.subplots(1,2,figsize=(13,6),gridspec_kw={'width_ratios':[1.25,1]})
    for ax in axes:
        ax.add_patch(Polygon(poly,facecolor='#dce3f0',edgecolor='#64748b',label='First posterior outer polygon'))
        ax.scatter(*np.array(legacy).T,s=7,c='#94a3b8',label='Legacy 213')
        for mode,color in [('M1','#71717a'),('M2','#d99b37'),('M3','#39aea5')]:
            points = np.unique([[float(r['x']),float(r['y'])] for r in rows if r.get('mode')==mode],axis=0)
            ax.scatter(points[:,0],points[:,1],s=2,alpha=.3,c=color,label=f'{mode} evaluated')
        for name,disks in regs.items():
            floats = floating_disks(disks)
            first = True
            for c,r in floats:
                angles = np.linspace(0,2*np.pi,16000)
                points = c+r*np.c_[np.cos(angles),np.sin(angles)]
                inside = np.logical_and.reduce([np.linalg.norm(points-d,axis=1)<=s+1e-7 for d,s in floats])
                points[~inside] = np.nan
                ax.plot(points[:,0],points[:,1],c=colors[name],lw=1.7,
                        label=f'{name} analytic arcs (sampled display)' if first else None)
                first = False
        ax.scatter([0],[0],s=65,c='#111827',marker='+',label='First station p')
        for i,row in enumerate(table):
            ax.scatter(row['x'],row['y'],marker='*' if i==0 else 'X',s=95,
                       color=['#b91c1c','#6c7183','#c07713','#008c83'][i],edgecolors='white',zorder=5)
        ax.set_aspect('equal'); ax.set_xlabel('x (m)'); ax.set_ylabel('y (m)'); ax.grid(alpha=.15)
    axes[0].set_xlim(-800,1650); axes[0].set_ylim(-800,1250)
    axes[0].set_title('Reception regions and actually evaluated stations')
    axes[0].legend(fontsize=7,loc='lower right')
    axes[1].set_xlim(420,500); axes[1].set_ylim(850,920)
    axes[1].set_title('Finalists near the reception boundary')
    for row in table:
        if row['mode']!='M2':
            axes[1].annotate(row['mode'],(row['x'],row['y']),xytext=(5,7),textcoords='offset points')
    fig.suptitle('Q2: proof-backed domains; boundary discretization is for display only')
    fig.tight_layout(); fig.savefig(output/'reception_regions.png',dpi=180); plt.close(fig)
    traces = read_csv(run/'refinement.csv')
    fig,axes = plt.subplots(1,3,figsize=(13,4))
    for mode,color in [('M1','#6c7183'),('M2','#c07713'),('M3','#008c83')]:
        selected = [r for r in traces if r['mode']==mode]
        for ax,key,label in zip(axes,['J_upper_m','D_upper_m','T_s'],['J upper proxy (m)','D upper proxy (m)','Second action time (s)']):
            ax.plot([float(r['step_m']) for r in selected],[float(r[key]) for r in selected],'-o',label=mode,color=color)
            ax.set_xscale('log'); ax.invert_xaxis(); ax.set_xticks([50,20,10,5,2,1],labels=['50','20','10','5','2','1'])
            ax.set_xlabel('Station step (m)'); ax.set_ylabel(label); ax.grid(alpha=.2)
    axes[0].legend(); fig.suptitle('Frozen refinement trajectory (.01 m inner numerical tolerance)')
    fig.tight_layout(); fig.savefig(output/'convergence.png',dpi=180); plt.close(fig)


def report(root, output):
    run = root/'run'
    output.mkdir(parents=True,exist_ok=False)
    completed = json.loads((run/'COMPLETED.json').read_text())
    final = json.loads((run/'FINAL_REVIEW.json').read_text())
    frozen = json.loads((run/'FROZEN.json').read_text())
    for name,digest in frozen['source_sha256'].items():
        assert hashlib.sha256((BASE/name).read_bytes()).hexdigest()==digest, name
    protected = protected_state()
    poly,_,_ = baseline()
    regs = regions(poly)
    rows, pools = [], {}
    from collections import defaultdict
    pools = defaultdict(dict)
    trajectory = read_csv(run/'refinement.csv')
    for path in sorted(run.glob('M*_level_*.csv')):
        stage = read_csv(path)
        for row in stage:
            q = np.array([float(row['x']),float(row['y'])])
            assert verify_guaranteed_reception(q,regs[row['region']])['verified']
            assert verify_guaranteed_reception(q,regs['Q5'])['verified']
            assert abs(float(row['T_s'])-(np.linalg.norm(q)/5+5))<1e-10
            assert abs(float(row['J_upper_m'])-float(row['D_upper_m'])-.2*float(row['T_s']))<1e-10
            assert float(row['inner_gap_m'])<=.010000001
            pools[row['mode']][row['key']] = row
        best = min(pools[stage[0]['mode']].values(),key=lambda r:(float(r['J_upper_m']),r['key']))
        trace = next(r for r in trajectory if r['mode']==stage[0]['mode'] and r['level']==stage[0]['level'])
        assert best['key']==trace['key']
        rows.extend(stage)
    with gzip.open(run/'inner_scores.json.gz','rt',encoding='utf-8') as stream:
        scores = json.load(stream)
    assert len(scores)==completed['unique_scores']
    for key,score in scores.items():
        q = np.array([float.fromhex(v) for v in key.split('|')[-1].split(',')])
        assert verify_guaranteed_reception(q,regs['Q5'])['verified']
        assert score['inner_gap_m']<=.010000001
        leaves = score['direction_envelope']['leaves']
        if leaves:
            assert leaves[0][0]==0 and leaves[-1][1]==360
            assert all(a[1]==b[0] for a,b in zip(leaves,leaves[1:]))
    extra_rows = []
    for path in run.glob('M*_half_step.csv'):
        for row in read_csv(path):
            q = np.array([float(row['x']),float(row['y'])])
            assert verify_guaranteed_reception(q,regs['Q5'])['verified']
            extra_rows.append(dict(row,level='half_step',parent=row['source'],region=completed['winners'][row['mode']]['region']))
    table, independent = [], []
    old = next(r for r in final if r['mode']=='M0' and r['role']=='table_finalist')
    for entry in final:
        q = np.array([entry['x'],entry['y']])
        check = independent_reception(q,poly)
        assert check['q5_pass']
        independent.append(dict(mode=entry['mode'],role=entry['role'],**check))
        extra_rows.append(dict(mode=entry['mode'],level='final_inner_audit',parent=entry['role'],
                               region=completed['winners'][entry['mode']]['region'],x=q[0],y=q[1],
                               D_lower_m=entry['score']['D_lower_m'],D_upper_m=entry['score']['D_upper_m'],
                               T_s=entry['T_s'],J_lower_m=entry['J_lower_m'],J_upper_m=entry['J_upper_m'],
                               inner_gap_m=entry['score']['inner_gap_m'],safety_status='SAFE',
                               score_elapsed_s=entry['score']['elapsed_s']))
        if entry['role']!='table_finalist':
            continue
        mode = entry['mode']; name = completed['winners'][mode]['region']; score = entry['score']
        certs = {n:verify_guaranteed_reception(q,d)['verified'] for n,d in regs.items()}
        assert certs[name] and certs['Q5'] and score['inner_gap_m']<=.001000001
        table.append(dict(mode=mode,region=name,x=entry['x'],y=entry['y'],
                          D_lower_m=score['D_lower_m'],D_upper_m=score['D_upper_m'],T_s=entry['T_s'],
                          lambda_T_m=.2*entry['T_s'],J_lower_m=entry['J_lower_m'],J_upper_m=entry['J_upper_m'],
                          inner_gap_m=score['inner_gap_m'],boundary_distance_m=boundary_distance(q,regs[name]),
                          in_Csafe=certs['Csafe'],in_Q0=certs['Q0'],in_Qvis_Q5=certs['Q5'],
                          displacement_from_legacy_m=float(np.linalg.norm(q-[old['x'],old['y']])),
                          worst_sampled_report_deg=score['direction_envelope']['argmax_sampled_report_deg'],
                          near_possible=score['near_possible'],mode_wall_s=completed['mode_wall_s'][mode],
                          cumulative_points=completed['winners'][mode]['cumulative_count'],
                          newly_scored_points=sum(int(r['new_score_count']) for r in trajectory if r['mode']==mode),
                          candidate_references=sum(1 for r in rows if r['mode']==mode),
                          half_step_delta_q_m=entry['half_step_delta_q_m']))
    bymode = {r['mode']:r for r in table}
    for r in table:
        r['delta_J_from_legacy_m'] = r['J_upper_m']-bymode['M0']['J_upper_m']
        r['relative_gain'] = -r['delta_J_from_legacy_m']/bymode['M0']['J_upper_m']
    comparisons = []
    for a,b in [('M0','M1'),('M1','M2'),('M1','M3'),('M0','M3')]:
        x,y = bymode[a],bymode[b]
        comparisons.append(dict(comparison=a+'->'+b,delta_J_upper_m=y['J_upper_m']-x['J_upper_m'],
                                numerical_improvement_separation_m=x['J_lower_m']-y['J_upper_m'],
                                relative_gain=(x['J_upper_m']-y['J_upper_m'])/x['J_upper_m'],
                                delta_D_upper_m=y['D_upper_m']-x['D_upper_m'],delta_T_s=y['T_s']-x['T_s']))
    stable = all(abs(completed['winners'][m]['delta_J_m'])<PLAN['eps_J_m'] and
                 completed['winners'][m]['delta_q_m']<PLAN['eps_q_m'] for m in ['M1','M2','M3'])
    meets_gain = bymode['M3']['relative_gain']>=PLAN['acceptance_relative_J']
    acceptance = dict(task='Q2_RECEPTION_AWARE_OUTER_REFINEMENT',code_commit=completed['head'],
                      legacy_reproduced=True,domain_proof_checked=True,feasibility_tests_passed=True,
                      finalists_feasibility_verified=True,finalists_inner_audit_passed=True,
                      protected_files_unchanged=True,score_comparison_valid=True,
                      search_scope='Csafe(P_outer), Q0 and Q5 for the full bounded main-example sector; not general clipped or exact quantized Qvis',
                      budget_exhausted=completed['budget_limited'],budget_used=completed['budget_used'],
                      continuous_global_optimality_proved=False,certified_score_interval=False,
                      reception_certificate='exact rational interval disk verifier with analytical sector proof',
                      numeric_final_refinement_criteria_met=stable,adoption_gain_threshold_met=meets_gain,
                      disposition='SAFE_INNER_DOMAIN_REFINEMENT_REVIEW_ONLY',auto_adopted=False,auto_pushed=False,
                      failure_reasons=[] if meets_gain else ['Relative J gain below frozen 1% adoption threshold'],
                      finalists=table,comparisons=comparisons,official_practice_starts=0,official_test_starts=0,
                      verification=dict(raw_rows_rechecked=len(rows),unique_scores=len(scores),tests=25,
                                        finalist_finer_score_calls=len(final),
                                        total_score_calls_excluding_pilot=len(scores)+len(final),
                                        total_posterior_evaluations_excluding_pilot=completed['posterior_evaluations']+
                                            sum(r['score']['posterior_evaluations'] for r in final),
                                        max_clip_residual_m=completed['max_clip_residual_m'],
                                        elapsed_s=completed['elapsed_s']))
    write_json(output/'acceptance.json',acceptance)
    write_json(output/'PROTECTED_FILES_SHA256.json',protected)
    write_json(output/'INDEPENDENT_FINALIST_RECEPTION.json',independent)
    write_csv(output/'finalists.csv',table)
    write_csv(output/'comparisons.csv',comparisons)
    fields = list(dict.fromkeys(k for r in rows+extra_rows for k in r))
    write_csv(output/'candidates.csv',[{k:r.get(k,'') for k in fields} for r in rows+extra_rows])
    shutil.copy2(run/'refinement.csv',output/'convergence.csv')
    for path in run.iterdir():
        shutil.copy2(path,output/path.name)
    for name in ['START_STATE.json','PILOT_COST.json','TESTS_BEFORE.txt','PROTECTED_BEFORE.json','RUN_LOG.txt']:
        shutil.copy2(root/name,output/name)
    make_plots(run,output,table,rows)
    write_json(BASE/'Q2_CONTINUOUS_SEARCH_AUDIT.json',acceptance)
    print(json.dumps(dict(output=str(output),acceptance=acceptance),ensure_ascii=False,indent=2))


def package(evidence, destination):
    """Package explicit Q2 paths only; verify every archive member after writing."""
    evidence, destination = evidence.resolve(), destination.resolve()
    if destination.exists():
        raise FileExistsError(destination)
    source_files = ['q2_scoring.py','q2_visibility.py','q2_continuous_search.py','q2_outer_report.py',
                    'questions.py','geometry.py','experiments/q2_score_audit.py',
                    'tests/test_q2_continuous_search.py','results/q2.json','results/q2_candidates.csv',
                    'results/q2_score_20260911/CALIPERS_DIAGNOSTIC.json',
                    'Q2_CURRENT_IMPLEMENTATION_AUDIT.md','Q2_VISIBILITY_REGION_DERIVATION.md',
                    'Q2_RECEPTION_DOMAIN_PROOF.md','Q2_CONTINUOUS_SEARCH_PLAN.md',
                    'Q2_CONTINUOUS_SEARCH_RESULTS.md','Q2_CONTINUOUS_SEARCH_AUDIT.json',
                    'Q2_OUTER_REFINEMENT_REPORT.md']
    files = [BASE/name for name in source_files]+[p for p in evidence.rglob('*') if p.is_file()]
    manifest = {str(p.relative_to(BASE.parent)).replace('\\','/'):
                dict(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in files}
    state = dict(source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=BASE,text=True).strip(),
                 frozen_experiment_commit=json.loads((evidence/'FROZEN.json').read_text())['head'],
                 files=manifest,contains_credentials=False,official_calls=0,automatic_push=False)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for path in files:
            archive.write(path,str(path.relative_to(BASE.parent)).replace('\\','/'))
        archive.writestr('MANIFEST.json',json.dumps(state,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        for name,item in manifest.items():
            contents = archive.read(name)
            assert len(contents)==item['bytes'] and hashlib.sha256(contents).hexdigest()==item['sha256']
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix('.zip.sha256').write_text(digest+'  '+destination.name+'\n',encoding='utf-8')
    write_json(destination.with_suffix('.zip.verification.json'),dict(sha256=digest,verified_members=len(files),
                bytes=destination.stat().st_size,source_commit=state['source_commit'],all_members_verified=True))
    print(json.dumps(dict(path=str(destination),sha256=digest,files=len(files),bytes=destination.stat().st_size)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare',type=Path)
    parser.add_argument('--report',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--package',type=Path)
    parser.add_argument('--zip',type=Path)
    args = parser.parse_args()
    if args.prepare:
        prepare(args.prepare)
    if args.report:
        report(args.report,args.output)
    if args.package:
        package(args.package,args.zip)
