"""构造式候选弹生成器。

给定无人机、导弹、起爆时刻 S、视线上的比例 f, 反解出 (phi,v,tau,delta) 使弹在
时刻 S 于视线上指定点 Y 起爆, 从而"把云放在视线上", 而非依赖随机搜索碰运气。

注意: 弹只向下(重力), 因此起爆点高度必须低于无人机高度 (Y_z < P0_z)。
"""

import numpy as np
import smoke_model as sm


def los_point(miss_key, S, f):
    """时刻 S 导弹到目标视线上比例 f 处的点 (f=0 导弹侧, f=1 目标侧)。"""
    M = sm.missile_pos(miss_key, S)
    return M + f * (sm.TARGET - M)


def construct_shell(drone_key, miss_key, S, f):
    """
    反解一枚弹: 起爆时刻 S, 视线比例 f。
    返回 (phi, v, tau, delta) 或 None (不可行)。
    """
    P0 = sm.UAV0[drone_key]
    Y = los_point(miss_key, S, f)
    Yz = Y[2]
    if Yz >= P0[2]:          # 弹只能向下
        return None
    dx = Y[0] - P0[0]
    dy = Y[1] - P0[1]
    horiz = np.sqrt(dx * dx + dy * dy)
    if S <= 1e-6:
        return None
    v = horiz / S
    if not (sm.VMIN - 1e-6 <= v <= sm.VMAX + 1e-6):
        return None
    phi = np.degrees(np.arctan2(dy, dx)) % 360.0
    d2 = 2.0 * (P0[2] - Yz) / sm.G
    delta = np.sqrt(max(d2, 1e-9))
    tau = S - delta
    if tau < 0:
        return None
    return float(phi), float(v), float(tau), float(delta)


def build_library(drone_key, miss_key, S_range=(2.0, 62.0), f_grid=25,
                  S_step=1.0, min_dur=0.0, res=0.05):
    """为 (drone,missile) 构造候选弹库, 每个候选含 (phi,v,tau,delta,start,end,dur,S,f)。"""
    cands = []
    for S in np.arange(S_range[0], S_range[1] + 1e-9, S_step):
        for f in np.linspace(0.05, 0.98, f_grid):
            c = construct_shell(drone_key, miss_key, float(S), float(f))
            if c is None:
                continue
            phi, v, tau, delta = c
            dur, iv = sm.obscuring_duration(drone_key, phi, v, tau, delta,
                                            miss_key, resolution=res)
            if dur >= min_dur and iv:
                start = min(a for a, b in iv)
                end = max(b for a, b in iv)
                cands.append({
                    "drone": drone_key, "missile": miss_key,
                    "phi": phi, "v": v, "tau": tau, "delta": delta,
                    "start": start, "end": end, "dur": dur,
                    "S": float(S), "f": float(f),
                })
    return cands


def bucketed_library(cands, bucket=2.0):
    """按遮蔽区间中点分桶, 每桶保留时长最长的候选 (用于跨时间窗覆盖)。"""
    byb = {}
    for c in cands:
        mid = (c["start"] + c["end"]) / 2.0
        b = int(mid // bucket) * bucket
        cur = byb.get(b)
        if cur is None or c["dur"] > cur["dur"]:
            byb[b] = c
    return byb


def shells_fixed_drone(drone_key, miss_key, phi, v,
                       S_grid=None, delta_grid=None, min_dur=0.0, res=0.05):
    """
    给定无人机与固定 (phi, v), 扫起爆时刻 S 与引信 delta, 生成共用该 (phi,v) 的候选弹。
    返回候选列表 (每个含 missile, S, delta, tau, start, end, dur)。
    """
    if S_grid is None:
        S_grid = np.arange(3.0, 62.0, 1.5)
    if delta_grid is None:
        delta_grid = np.arange(1.0, 16.0, 1.0)
    cands = []
    for S in S_grid:
        for delta in delta_grid:
            tau = S - delta
            if tau < 0:
                continue
            dur, iv = sm.obscuring_duration(drone_key, phi, v, float(tau), float(delta),
                                            miss_key, resolution=res)
            if dur >= min_dur and iv:
                start = min(a for a, b in iv)
                end = max(b for a, b in iv)
                cands.append({
                    "drone": drone_key, "missile": miss_key,
                    "phi": phi, "v": v, "tau": float(tau), "delta": float(delta),
                    "S": float(S), "start": start, "end": end, "dur": dur,
                })
    return cands


def best_mission(drone_key, miss_key, phi_grid=None, v_grid=None, res=0.05,
                 S_grid=None, delta_grid=None):
    """
    对 (无人机, 导弹), 在不同 (phi,v) 网格下找能遮蔽的弹, 返回 (phi,v) 与该 (phi,v) 下的候选弹列表。
    用于在一架无人机固定 (phi,v) 的前提下选弹。
    """
    if phi_grid is None:
        phi_grid = np.arange(0.0, 360.0, 7.5)
    if v_grid is None:
        v_grid = np.array([70.0, 90.0, 110.0, 140.0])
    best = None
    for phi in phi_grid:
        for v in v_grid:
            cands = shells_fixed_drone(drone_key, miss_key, phi, v,
                                       S_grid=S_grid, delta_grid=delta_grid, res=res)
            if not cands:
                continue
            total = sum(c["dur"] for c in cands)
            if best is None or total > best[0]:
                best = (total, float(phi), float(v), cands)
    if best is None:
        return None
    return {"phi": best[1], "v": best[2], "cands": best[3], "total_dur": best[0]}
