"""
Q5 求解器 v3 (修正版)。

修正要点:
  * 每枚弹生成时就计算它对 M1/M2/M3 三枚导弹各自的遮蔽区间, 并在目标函数里把
    每个区间计入对应的导弹。这样"靠近目标、能同时遮蔽多枚导弹"的云团不会被低估。
  * 目标函数(选项A): 最大化三导弹"同时被遮蔽"的交集时长 T_protect。
  * 尊重每架无人机固定 (phi, v): 候选按 (phi,v) 聚类, 一架机只从一个聚类里选 <=3 枚弹。

命令行:  python solver3.py --restarts 120 --sw 60 --seed 0 [--res 0.05]
"""

import argparse
import numpy as np
import sys, os, time, itertools
import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smoke_model as sm
import library as lib

TMAX = 67.0


def gen_cands_fixed(drone, phi, v, S_grid=None, delta_grid=None, res=0.05, min_sum=0.15):
    """
    在固定 (phi,v) 下生成候选弹: 扫起爆时刻 S 与引信 delta,
    每个候选含其对 M1/M2/M3 的遮蔽区间与时长。这些弹共享同一 (phi,v)。
    """
    if S_grid is None:
        S_grid = np.arange(3.0, 62.0, 3.0)
    if delta_grid is None:
        delta_grid = np.arange(2.0, 19.0, 3.0)
    cands = []
    for S in S_grid:
        for delta in delta_grid:
            tau = S - delta
            if tau < 0:
                continue
            per = {}
            tot = 0.0
            for mk in sm.MISSILE_KEYS:
                d, iv = sm.obscuring_duration(drone, phi, v, float(tau), float(delta),
                                              mk, resolution=res)
                if iv:
                    per[mk] = {"iv": [(a, b) for a, b in iv], "dur": d}
                    tot += d
                else:
                    per[mk] = {"iv": [], "dur": 0.0}
            if tot >= min_sum:
                cands.append({
                    "phi": phi, "v": v, "tau": float(tau), "delta": float(delta),
                    "S": float(S), "per": per, "total": tot,
                })
    return cands


def pick_3(cands):
    """在同一 (phi,v) 聚类内选 <=3 枚弹 (tau 间隔>=1s), 使该机对三导弹的总遮蔽并集最大。"""
    best, best_score = [], -1.0
    cands = list(cands)
    for size in range(1, min(3, len(cands)) + 1):
        for combo in itertools.combinations(cands, size):
            taus = [c["tau"] for c in combo]
            if any(abs(taus[i] - taus[j]) < 1.0
                   for i in range(len(taus)) for j in range(i + 1, len(taus))):
                continue
            # 机对三导弹遮蔽并集总长(作为该机独立覆盖强度)
            union_per = {mk: len(sm.union_intervals([it for c in combo for it in c["per"][mk]["iv"]]))
                         for mk in sm.MISSILE_KEYS}
            score = sum(union_per.values()) + 3.0 * min(union_per.values())
            if score > best_score:
                best_score = score
                best = list(combo)
    best.sort(key=lambda c: c["tau"])
    return best


def _seeds(drone, res=0.05, S_step=1.0, f_grid=12, top=60):
    """用 construct_shell 找好弹, 取其精确 (phi,v) 作为候选种子。"""
    from collections import Counter
    cands = lib.build_library(drone, "M1", S_step=S_step, f_grid=f_grid,
                              min_dur=0.2, res=res)
    # 统计 (phi,v) 中遮蔽较好的
    scored = {}
    for c in cands:
        key = (round(c["phi"], 0), round(c["v"], 0))
        cur = scored.get(key, 0.0)
        scored[key] = max(cur, c["dur"])
    items = sorted(scored.items(), key=lambda kv: -kv[1])[:top]
    return [(float(k[0]), float(k[1])) for k, _ in items]


def drone_options(drone, res=0.05, S_grid=None, delta_grid=None):
    """
    对一架无人机: 先用 construct_shell 找好的 (phi,v) 种子, 再在固定 (phi,v) 下生成
    共享该 (phi,v) 的候选弹, 每 (phi,v) 选 <=3 枚。返回选项列表 [{phi,v,shells}]。
    """
    if S_grid is None:
        S_grid = np.arange(3.0, 62.0, 1.5)
    if delta_grid is None:
        delta_grid = np.arange(2.0, 19.0, 1.5)
    opts = []
    seen = set()
    for phi, v in _seeds(drone, res=res):
        key = (round(phi / 2.0) * 2.0, round(v / 4.0) * 4.0)
        if key in seen:
            continue
        seen.add(key)
        cands = gen_cands_fixed(drone, phi, v, S_grid=S_grid, delta_grid=delta_grid, res=res)
        if not cands:
            continue
        ch = pick_3(cands)
        if ch:
            opts.append({"phi": phi, "v": v, "shells": ch})
    # 追加 construct_shell 的精确单弹选项（每机只用一枚弹, phi,v 即该弹自己的）
    exact = lib.build_library(drone, "M1", S_step=1.0, f_grid=15, min_dur=0.5, res=res)
    exact_seen = set()
    for c in exact:
        key = (round(c["phi"] / 2.0) * 2.0, round(c["v"] / 4.0) * 4.0)
        if key in exact_seen:
            continue
        exact_seen.add(key)
        # 计算该弹对三导弹的遮蔽
        per = {}
        for mk in sm.MISSILE_KEYS:
            d, iv = sm.obscuring_duration(drone, c["phi"], c["v"], c["tau"], c["delta"],
                                          mk, resolution=res)
            per[mk] = {"iv": [(a, b) for a, b in iv], "dur": (d if iv else 0.0)}
        shell = {"phi": c["phi"], "v": c["v"], "tau": c["tau"], "delta": c["delta"],
                 "S": c["S"], "per": per, "total": sum(per[m]["dur"] for m in sm.MISSILE_KEYS)}
        opts.append({"phi": c["phi"], "v": c["v"], "shells": [shell]})
    opts.sort(key=lambda o: -len(o["shells"]))
    return opts


def objective(assignment):
    """
    assignment: {drone: {phi,v,shells}}。把每枚弹对每枚导弹的遮蔽区间计入对应导弹,
    求并集后取三导弹交集时长。
    """
    per_missile = {k: [] for k in sm.MISSILE_KEYS}
    for drone, opt in assignment.items():
        for c in opt["shells"]:
            for mk in sm.MISSILE_KEYS:
                per_missile[mk].extend(c["per"][mk]["iv"])
    unions = {mk: sm.union_intervals(per_missile[mk]) for mk in sm.MISSILE_KEYS}
    inter = [[iv for iv in unions[mk] if iv[0] < TMAX] for mk in sm.MISSILE_KEYS]
    total, ivs = sm.intersect_intervals(inter)
    return max(0.0, total), unions, ivs


def random_init(options, rng):
    a = {}
    for u in sm.UAV_KEYS:
        if options[u] and rng.random() < 0.9:
            a[u] = options[u][rng.integers(len(options[u]))]
    return a


def coordinate_ascent(assignment, options, iters=60):
    drones = list(sm.UAV_KEYS)
    best_total, _, _ = objective(assignment)
    rounds = 0
    improved = True
    while improved and rounds < iters:
        improved = False
        rounds += 1
        for u in drones:
            trial = dict(assignment)
            cur = assignment.get(u)
            best_here = (best_total, cur)
            for opt in options[u]:
                trial[u] = opt
                t2, _, _ = objective(trial)
                if t2 > best_here[0] + 1e-6:
                    best_here = (t2, opt)
            if best_here[1] != cur:
                assignment[u] = best_here[1]
                best_total = best_here[0]
                improved = True
    return assignment, best_total


def primary_missile(c):
    """用于模板"干扰的导弹编号": 该弹遮蔽时长最长的导弹。"""
    best_mk, best_d = "M1", -1.0
    for mk in sm.MISSILE_KEYS:
        if c["per"][mk]["dur"] > best_d:
            best_d, best_mk = c["per"][mk]["dur"], mk
    return best_mk


def write_result3(assignment, out_path, res=0.05):
    templ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "problem", "result3_template.xlsx")
    wb = openpyxl.load_workbook(templ)
    ws = wb.worksheets[0]
    rows = {}
    r = 2
    for u in sm.UAV_KEYS:
        for k in range(1, 4):
            rows[(u, k)] = r
            r += 1
    for u, opt in assignment.items():
        phi, v = opt["phi"], opt["v"]
        used = 0
        for k, c in enumerate(opt["shells"], start=1):
            D = sm.uav_pos(u, phi, v, c["tau"])
            phi_r = np.deg2rad(phi)
            hv = v * np.array([np.cos(phi_r), np.sin(phi_r), 0.0])
            B = D + hv * c["delta"] + np.array([0.0, 0.0, -0.5 * sm.G * c["delta"] ** 2])
            durs = {}
            for m in sm.MISSILE_KEYS:
                durs[m] = sm.obscuring_duration(u, phi, v, c["tau"], c["delta"], m, resolution=res)[0]
            mk = max(durs, key=lambda m: durs[m])
            dur = durs[mk]
            if dur <= 0.05:
                continue
            used += 1
            row = rows[(u, used)]
            ws.cell(row=row, column=2, value=round(phi, 2))
            ws.cell(row=row, column=3, value=round(v, 2))
            ws.cell(row=row, column=4, value=k)
            ws.cell(row=row, column=5, value=round(float(D[0]), 2))
            ws.cell(row=row, column=6, value=round(float(D[1]), 2))
            ws.cell(row=row, column=7, value=round(float(D[2]), 2))
            ws.cell(row=row, column=8, value=round(float(B[0]), 2))
            ws.cell(row=row, column=9, value=round(float(B[1]), 2))
            ws.cell(row=row, column=10, value=round(float(B[2]), 2))
            ws.cell(row=row, column=11, value=round(dur, 3))
            ws.cell(row=row, column=12, value=mk)
    wb.save(out_path)


def solve(restarts=120, sw=60, seed=0, res=0.05):
    t0 = time.time()
    print("[A] 生成候选弹(含对三导弹的遮蔽)...")
    options = {}
    for u in sm.UAV_KEYS:
        options[u] = drone_options(u, res=res,
                                   S_grid=np.arange(3.0, 62.0, 1.5),
                                   delta_grid=np.arange(2.0, 19.0, 1.5))
        print("  %-3s: %d 个选项" % (u, len(options[u])))
    print("  耗时 %.1fs" % (time.time() - t0))

    rng = np.random.default_rng(seed)
    best_assign, best_total = None, -1.0
    best_unions = None
    for r in range(restarts):
        a0 = random_init(options, rng)
        a1, t1 = coordinate_ascent(a0, options, iters=sw)
        if t1 > best_total + 1e-6:
            best_total = t1
            best_assign = a1
        if r % 20 == 0:
            print("  restart %d: best=%.3f s" % (r, best_total))
    if best_assign is None:
        best_assign, best_total, best_unions = random_init(options, rng), 0.0, None
    best_total, best_unions, ivs = objective(best_assign)

    print("\n=== 结果 ===")
    print("选项A: 三导弹同时遮蔽时长 = %.2f s" % best_total)
    for mk in sm.MISSILE_KEYS:
        U = best_unions[mk]
        print("  %s 并集: %s  (%.2f s)"
              % (mk, [(round(a, 1), round(b, 1)) for a, b in U], sm.interval_length(U)))
    print("  同时遮蔽窗口: %s" % [(round(a, 1), round(b, 1)) for a, b in ivs])
    print("  部署:")
    for u, opt in best_assign.items():
        pm = [primary_missile(c) for c in opt["shells"]]
        print("    %-3s phi=%.1f v=%.1f 弹=%s" % (u, opt["phi"], opt["v"], pm))

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results", "result3_filled.xlsx")
    write_result3(best_assign, out)
    print("[D] 已写入 %s, 总耗时 %.1fs" % (out, time.time() - t0))
    return best_assign, best_total


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--restarts", type=int, default=120)
    ap.add_argument("--sw", type=int, default=60)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--res", type=float, default=0.05)
    args = ap.parse_args()
    solve(restarts=args.restarts, sw=args.sw, seed=args.seed, res=args.res)
