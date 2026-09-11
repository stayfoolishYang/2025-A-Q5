"""Paired axisymmetric end-face benchmark for the prescribed material Q4 model.

The axial half-domain is 0 <= z <= L/2, with symmetry at z=0. The
radial coordinate xi=r/R(t) follows the uniformly shrinking material.
Only the benchmark exposes both end faces to the same empirical Robin law
as the cylindrical side. This is an explicit comparison assumption.
"""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import sys
import time

import numpy as np
from numba import njit
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from physics.material import properties, moisture_faces, MODEL_Q4
from physics.boundary import Boundary
from solver.fvm_cpu import geometry, solve


def grid(nr, nz):
    xi = np.linspace(0., 1., nr)
    u = np.linspace(0., 1., nz)
    z = .125*(1.-(1.-u)**2)
    rf, vr = geometry(nr)
    zf = np.r_[0., .5*(z[:-1]+z[1:]), .125]
    vz = np.diff(zf)
    weights = vr[:, None]*vz[None, :]
    node = np.arange(nr*nz).reshape(nr, nz)
    a = np.r_[node[:-1].ravel(), node[:, :-1].ravel()]
    b = np.r_[node[1:].ravel(), node[:, 1:].ravel()]
    rows = np.r_[node.ravel(), a, b]
    cols = np.r_[node.ravel(), b, a]
    return xi, z, rf, vr, vz, weights, rows, cols


@njit(cache=True)
def matrices(T, C, Told, Cold, R, dt, rf, vr, vz, z, ambient, ends):
    nr, nz = T.shape
    n = nr*nz
    scales = np.ones(4)
    cap, k, _ = properties(T.ravel(), C.ravel(), MODEL_Q4, 0, scales)
    dax = moisture_faces(T.ravel(), C.ravel(), MODEL_Q4, 0, scales)
    drad = moisture_faces(T.T.copy().ravel(), C.T.copy().ravel(), MODEL_Q4, 0, scales)
    ne = (nr-1)*nz+nr*(nz-1)
    dataT, dataC = np.zeros(n+2*ne), np.zeros(n+2*ne)
    rhsT, rhsC = np.empty(n), np.empty(n)
    for ir in range(nr):
        for iz in range(nz):
            p = ir*nz+iz
            volume = vr[ir]*vz[iz]
            dataT[p] = cap[p]*volume/dt
            dataC[p] = volume/dt
            rhsT[p] = dataT[p]*Told[ir, iz]
            rhsC[p] = dataC[p]*Cold[ir, iz]
    edge = 0
    for ir in range(nr-1):
        for iz in range(nz):
            a, b = ir*nz+iz, (ir+1)*nz+iz
            geom = rf[ir+1]*(nr-1)*vz[iz]/(R*R)
            gt = geom*2*k[a]*k[b]/(k[a]+k[b])
            gc = geom*drad[iz*nr+ir]
            dataT[a] += gt
            dataT[b] += gt
            dataC[a] += gc
            dataC[b] += gc
            dataT[n+edge] = dataT[n+ne+edge] = -gt
            dataC[n+edge] = dataC[n+ne+edge] = -gc
            edge += 1
    for ir in range(nr):
        for iz in range(nz-1):
            a, b = ir*nz+iz, ir*nz+iz+1
            geom = vr[ir]/(z[iz+1]-z[iz])
            gt = geom*2*k[a]*k[b]/(k[a]+k[b])
            gc = geom*dax[a]
            dataT[a] += gt
            dataT[b] += gt
            dataC[a] += gc
            dataC[b] += gc
            dataT[n+edge] = dataT[n+ne+edge] = -gt
            dataC[n+edge] = dataC[n+ne+edge] = -gc
            edge += 1
    for iz in range(nz):
        p = (nr-1)*nz+iz
        st, sc = 25.*vz[iz]/R, 8e-7*vz[iz]/R
        dataT[p] += st
        dataC[p] += sc
        rhsT[p] += st*ambient[0]
        rhsC[p] += sc*ambient[1]
    if ends:
        for ir in range(nr):
            p = ir*nz+nz-1
            st, sc = 25.*vr[ir], 8e-7*vr[ir]
            dataT[p] += st
            dataC[p] += sc
            rhsT[p] += st*ambient[0]
            rhsC[p] += sc*ambient[1]
    return dataT, dataC, rhsT, rhsC


def step(Told, Cold, R, dt, ambient, ends, mesh):
    _, z, rf, vr, vz, weights, rows, cols = mesh
    T, C = Told.copy(), Cold.copy()
    n = C.size
    for it in range(120):
        dataT, dataC, rhsT, rhsC = matrices(T, C, Told, Cold, R, dt, rf, vr, vz, z, ambient, ends)
        mt = coo_matrix((dataT, (rows, cols)), shape=(n, n)).tocsc()
        mc = coo_matrix((dataC, (rows, cols)), shape=(n, n)).tocsc()
        tn = spsolve(mt, rhsT).reshape(T.shape)
        cn = spsolve(mc, rhsC).reshape(C.shape)
        et, ec = np.max(np.abs(tn-T)), np.max(np.abs(cn-C))
        T, C = tn, cn
        if et < 1e-7 and ec < 1e-9:
            if not np.isfinite(T).all() or not np.isfinite(C).all() or np.min(C) <= 0:
                raise ValueError('Invalid nonlinear solution')
            return T, C, it+1
    raise RuntimeError('2D Picard did not converge')


def run(nr=41, nz=25, dt=30., ends=True, label='coarse'):
    started = time.perf_counter()
    mesh = grid(nr, nz)
    xi, z, _, vr, vz, weights, _, _ = mesh
    ref_volume = weights.sum()
    boundary = Boundary('pchip', 'mean')
    T, C = np.full((nr, nz), 28.), np.full((nr, nz), 2.55)
    snapshots = {0.: (T.copy(), C.copy())}
    history = [[0., .02, 2.55, 2.55, 28., 28., 2.55, 2.55, 0., 0.]]
    times = np.arange(0., 216000.+dt/2, dt)
    ambients, radii = boundary.ambient(times), boundary.radius(times)
    max_step, max_total, maxit = 0., 0., 0
    side_loss, end_loss = 0., 0.
    event_bracket = None
    total_steps = 0
    for j in range(1, len(times)):
        t, tj, cj = times[j], T, C
        T, C, it = step(tj, cj, radii[j], dt, ambients[j], ends, mesh)
        maxit = max(maxit, it)
        actual_dt = dt
        if C.max() <= .15:
            lo, hi = 0., dt
            while hi-lo > .1:
                mid = .5*(lo+hi)
                tm = t-dt+mid
                tt, cc, _ = step(tj, cj, float(boundary.radius(tm)), mid, boundary.ambient(tm), ends, mesh)
                if cc.max() <= .15:
                    hi = mid
                else:
                    lo = mid
            event_bracket = [float(t-dt+lo), float(t-dt+hi)]
            actual_dt, t = hi, t-dt+hi
            T, C, it = step(tj, cj, float(boundary.radius(t)), actual_dt, boundary.ambient(t), ends, mesh)
        R = float(boundary.radius(t))
        ambient = boundary.ambient(t)
        fs = 8e-7/R*np.sum(vz*(C[-1]-ambient[1]))/ref_volume
        fe = 8e-7*np.sum(vr*(C[:, -1]-ambient[1]))/ref_volume if ends else 0.
        oldmean, mean = np.sum(weights*cj)/ref_volume, np.sum(weights*C)/ref_volume
        side_loss += actual_dt*fs
        end_loss += actual_dt*fe
        max_step = max(max_step, abs(mean-oldmean+actual_dt*(fs+fe))/2.55)
        max_total = max(max_total, abs(mean-2.55+side_loss+end_loss)/2.55)
        total_steps += 1
        if any(abs(t-s) < 1e-8 for s in (1800., 14400., 86400.)) or event_bracket:
            snapshots[float(t)] = (T.copy(), C.copy())
        if j % max(1, int(600/dt)) == 0 or event_bracket:
            history.append([t, R, C.max(), mean, T.min(), T.max(), C[0, 0], C[0, -1], side_loss, end_loss])
        if j % max(1, int(21600/dt)) == 0:
            print(f'{label}: {t/3600:.1f} h, maxC={C.max():.6f}, wall={time.perf_counter()-started:.1f}s', flush=True)
        if event_bracket:
            break
    if not event_bracket:
        raise RuntimeError('No event by 60 h')
    result = dict(label=label, model=MODEL_Q4, formulation='material_coordinate', tail='mean',
                  nr=nr, nz=nz, dt_s=dt, scheme='BE', ends=ends,
                  axial_half_length_m=.125, end_hm_m_s=8e-7 if ends else 0.,
                  end_hT_W_m2_K=25. if ends else 0.,
                  z_grid='z=0.125*(1-(1-u)^2), uniform u in [0,1]',
                  event_h=t/3600, event_s=t, event_bracket_s=event_bracket,
                  mean_C_final=float(mean), max_C_final=float(C.max()),
                  side_loss_C_average=float(side_loss), end_loss_C_average=float(end_loss),
                  normalized_dry_mass=1.,
                  normalized_water_mass_definition='Mw/Md = sum(vr*vz*C)/(0.5*L/2)',
                  max_step_water_budget_relative=float(max_step),
                  max_cumulative_water_budget_relative=float(max_total),
                  budget_includes_final_event_step=True, max_picard_iterations=maxit,
                  steps=total_steps, wall_seconds=time.perf_counter()-started,
                  snapshots=[])
    for ts, (tt, cc) in snapshots.items():
        result['snapshots'].append(dict(time_s=ts, max_C=float(cc.max()),
                                       mean_C=float(np.sum(weights*cc)/ref_volume),
                                       center_midplane_C=float(cc[0, 0]),
                                       center_end_C=float(cc[0, -1]),
                                       min_T=float(tt.min()), max_T=float(tt.max())))
    path = ROOT/'results'/f'endface_{label}'
    path.with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    np.savez_compressed(path.with_suffix('.npz'), xi=xi, z=z, weights=weights,
                        times=np.array(list(snapshots)),
                        T=np.array([x[0] for x in snapshots.values()]),
                        C=np.array([x[1] for x in snapshots.values()]), history=np.array(history))
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def paired_1d(nr, dt, label):
    started = time.perf_counter()
    out, meta = solve(model=MODEL_Q4, moving=True, n=nr, dt=dt, interval=600.,
                      ale=False, tail='mean', scheme='be')
    meta['wall_seconds'] = time.perf_counter()-started
    path = ROOT/'results'/f'endface_{label}_1d'
    path.with_suffix('.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    np.savez_compressed(path.with_suffix('.npz'), data=out)
    print(json.dumps(meta, ensure_ascii=False), flush=True)


def summarize():
    import matplotlib
    import scipy
    import numba
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    records, details = [], {}
    for label in ('closed', 'coarse', 'fine'):
        base = ROOT/'results'/f'endface_{label}'
        two = json.loads(base.with_suffix('.json').read_text(encoding='utf-8'))
        one = json.loads((ROOT/'results'/f'endface_{label}_1d.json').read_text(encoding='utf-8'))
        d2 = np.load(base.with_suffix('.npz'))
        d1 = np.load(ROOT/'results'/f'endface_{label}_1d.npz')['data']
        nr = two['nr']
        _, vr = geometry(nr)
        paired = []
        for idx, ts in enumerate(d2['times']):
            j = int(np.argmin(abs(d1[:, 0]-ts)))
            if abs(d1[j, 0]-ts) > 1e-8:
                if ts == two['event_s']:
                    # Do not compare fields evaluated at different event clocks.
                    continue
                raise AssertionError('Missing exact representative 1D time')
            t1, c1 = d1[j, 2:2+nr], d1[j, 2+nr:]
            t2, c2 = d2['T'][idx], d2['C'][idx]
            mean1 = float(2*np.sum(vr*c1))
            mean2 = float(np.sum(d2['weights']*c2)/np.sum(d2['weights']))
            paired.append(dict(time_s=float(ts), max_C_1d=float(c1.max()), max_C_2d=float(c2.max()),
                               max_C_difference=float(c2.max()-c1.max()),
                               mean_C_1d=mean1, mean_C_2d=mean2,
                               mean_C_difference=mean2-mean1,
                               max_abs_T_field_vs_repeated_1d=float(np.max(abs(t2-t1[:, None]))),
                               max_abs_C_field_vs_repeated_1d=float(np.max(abs(c2-c1[:, None])))))
        record = dict(label=label, nr=nr, nz=two['nz'], dt_s=two['dt_s'], ends=two['ends'],
                      event_1d_h=one['event_h'], event_2d_h=two['event_h'],
                      event_difference_s=two['event_s']-one['event_s'],
                      final_mean_C_2d=two['mean_C_final'],
                      final_mean_C_1d=float(2*np.sum(vr*d1[-1, 2+nr:])),
                      max_cumulative_water_budget_relative=two['max_cumulative_water_budget_relative'],
                      end_fraction_of_integrated_loss=two['end_loss_C_average']/(two['end_loss_C_average']+two['side_loss_C_average']))
        records.append(record)
        details[label] = paired
    closed = details['closed']
    if max(r['max_abs_T_field_vs_repeated_1d'] for r in closed) > 1e-8:
        raise AssertionError('Closed-end temperature failed 1D degeneration')
    if max(r['max_abs_C_field_vs_repeated_1d'] for r in closed) > 1e-9:
        raise AssertionError('Closed-end moisture failed 1D degeneration')
    if records[0]['event_difference_s'] != 0.:
        raise AssertionError('Closed-end event failed 1D degeneration')
    result = dict(scope='Conditional engineering end-face benchmark; not a change to frozen Q4 main results',
                  runtime=dict(python=sys.version, numpy=np.__version__, scipy=scipy.__version__, numba=numba.__version__),
                  assumptions=['Same hT and hm on each end and cylindrical side',
                               'Fixed L=0.25m and uniform material radial shrinkage',
                               'Independent conserved dry-solid density; empirical rho*cp only in thermal equation',
                               'Identical effective equilibrium moisture mapping Ceq=Cair'],
                  rows=records, representative_time_pairs=details,
                  closed_end_degeneracy_passed=True,
                  paired_event_difference_change_s=records[2]['event_difference_s']-records[1]['event_difference_s'],
                  sources_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                                  [Path(__file__), ROOT/'physics/material.py', ROOT/'physics/boundary.py',
                                   ROOT/'solver/fvm_cpu.py', ROOT/'data/boundary.csv', ROOT/'data/radius.csv']})
    (ROOT/'results/endface_summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    with (ROOT/'results/endface_summary.csv').open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=records[0].keys())
        w.writeheader()
        w.writerows(records)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.4), constrained_layout=True)
    d2 = np.load(ROOT/'results/endface_fine.npz')
    d1 = np.load(ROOT/'results/endface_fine_1d.npz')['data']
    _, vr = geometry(records[-1]['nr'])
    n = records[-1]['nr']
    axes[0].plot(d1[:, 0]/3600, d1[:, 2+n:].max(axis=1), color='#1b4f72', label='1D max C')
    axes[0].plot(d2['history'][:, 0]/3600, d2['history'][:, 2], '--', color='#e67e22', label='2D max C')
    axes[0].plot(d1[:, 0]/3600, 2*(d1[:, 2+n:]@vr), color='#1b4f72', alpha=.6, label='1D mean C')
    axes[0].plot(d2['history'][:, 0]/3600, d2['history'][:, 3], '--', color='#c0392b', label='2D mean C')
    axes[0].axhline(.15, color='gray', lw=.8)
    axes[0].set(xlabel='Time (h)', ylabel='C (kg water/kg dry solid)', title='Paired 1D / 2D moisture histories')
    axes[0].legend(fontsize=8)
    for idx, ts in enumerate(d2['times']):
        if ts == 0.:
            continue
        axes[1].plot(d2['z']*100, d2['C'][idx, 0], label=f'{ts/3600:.2f} h')
    axes[1].set(xlabel='z from midplane (cm)', ylabel='Axis C (kg/kg)', title='Axial profile at radial center')
    axes[1].legend(fontsize=8)
    for ax in axes:
        ax.grid(alpha=.2)
    fig.savefig(ROOT/'results/endface_comparison.png', dpi=180)
    fig.savefig(ROOT/'results/endface_comparison.svg')
    plt.close(fig)
    fine = records[-1]
    baseline = json.loads((ROOT/'results/q4.json').read_text(encoding='utf-8'))
    closed_t = max(x['max_abs_T_field_vs_repeated_1d'] for x in details['closed'])
    closed_c = max(x['max_abs_C_field_vs_repeated_1d'] for x in details['closed'])
    lines = ['\n## 实际结果与解释\n',
             '| 场景 | Nr × Nz | dt/s | 配对1D时间/h | 2D时间/h | 2D−1D/s |',
             '|---|---:|---:|---:|---:|---:|']
    for x in records:
        lines.append(f"| {x['label']} | {x['nr']} × {x['nz']} | {x['dt_s']:.0f} | {x['event_1d_h']:.9f} | {x['event_2d_h']:.9f} | {x['event_difference_s']:.6f} |")
    lines += ['', f'关闭端面的完整二维场与重复的配对 1D 场一致：代表时刻及事件时刻最大温度差 {closed_t:.3e} K，最大含水率差 {closed_c:.3e} kg/kg；事件时间一致。', '',
              '细级开放端面对照如下。平均量采用干固体质量归一化，所有表中比较都在相同时刻进行。', '',
              '| 时刻/h | 1D max C | 2D max C | 1D mean C | 2D mean C | 均值相对改变 |',
              '|---:|---:|---:|---:|---:|---:|']
    for x in details['fine']:
        if x['time_s'] == 0.:
            continue
        change = 100*x['mean_C_difference']/x['mean_C_1d']
        lines.append(f"| {x['time_s']/3600:.6f} | {x['max_C_1d']:.9f} | {x['max_C_2d']:.9f} | {x['mean_C_1d']:.9f} | {x['mean_C_2d']:.9f} | {change:.4f}% |")
    coarse_delta = records[1]['final_mean_C_2d']-records[1]['final_mean_C_1d']
    fine_delta = fine['final_mean_C_2d']-fine['final_mean_C_1d']
    lines += ['', f"细级全程归一化水质量预算最大相对误差为 {fine['max_cumulative_water_budget_relative']:.3e}（包含事件短步）；累计端面排水占全部排水 {100*fine['end_fraction_of_integrated_loss']:.4f}%。粗、细级终态平均 C 的配对改变量分别为 {coarse_delta:.9f}、{fine_delta:.9f} kg/kg。", '',
              f"较大步长的细级配对 1D 时间比主结果 {baseline['event_h']:.9f} h 晚 {(fine['event_1d_h']-baseline['event_h'])*3600:.3f} s。这一绝对差主要属于所用离散设置，不能解释为端面影响，二维数值也没有替换主结果。", '',
              '两个分辨率的配对事件结果应结合各 JSON 中的事件括区读取。若括区重合，只表明当前离散问题没有分辨出相应尺度的时间变化；这不是连续 PDE 端面误差的严格上界，也不消除剩余网格、时间步、外部边界与端面参数的不确定性。', '',
              '**在本例规定长度、均匀径向形变和相同端面 Robin 参数下，端面对全域最大含水率达标时刻的影响很小；但对平均含水率和端部局部温湿场有可见影响。** 因此本验证支持针对中心阈值时间使用 1D 近似，不能支持“整个温湿场的端面误差均可忽略”。', '',
              '![配对历史与轴向剖面](../results/endface_comparison.png)', '']
    document = ROOT/'validation/端面验证.md'
    prose = document.read_text(encoding='utf-8').split('\n## 实际结果与解释')[0]
    document.write_text(prose+'\n'+'\n'.join(lines), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--nr', type=int, default=41)
    parser.add_argument('--nz', type=int, default=25)
    parser.add_argument('--dt', type=float, default=30.)
    parser.add_argument('--label', default='coarse')
    parser.add_argument('--closed-ends', action='store_true')
    parser.add_argument('--paired-1d', action='store_true')
    parser.add_argument('--summarize', action='store_true')
    args = parser.parse_args()
    if args.summarize:
        summarize()
    else:
        run(args.nr, args.nz, args.dt, not args.closed_ends, args.label)
        if args.paired_1d:
            paired_1d(args.nr, args.dt, args.label)
