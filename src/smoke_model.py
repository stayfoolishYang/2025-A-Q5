"""
2025 数模国赛 A 题（烟幕干扰弹投放策略）Q5 的核心几何-运动学模型。

坐标系: 原点=假目标(诱饵)。xy=水平面, z 向上, 单位 m。
真目标: 圆柱, 轴竖直过 (0,200,0), 半径 7 m, 高 10 m。
目标代表点 T = (0,200,0)  (题目给出的真目标下底面圆心)。

约定:
  - 所有位置为 3 维向量 [x,y,z]。
  - g = 9.8 m/s^2。
  - 云团半径 10 m; 起爆后 20 s 内有效; 云团中心以 3 m/s 匀速下沉。
  - 导弹 300 m/s 直线飞向假目标(原点)。

本模块只做几何/运动学/遮蔽判据, 不含搜索算法。
"""

import numpy as np

# ---- 常量 ----
G = 9.8                      # 重力加速度 m/s^2
SINK = 3.0                   # 云团下沉速度 m/s
CLOUD_R = 10.0               # 云团有效遮蔽半径 m
CLOUD_LIFE = 20.0            # 起爆后有效时长 s
CLOUD_MIN_CLEAR = 10.0       # 云心到视线段允许最大距离 = 遮蔽半径
VMIN, VMAX = 70.0, 140.0     # 无人机速度范围 m/s
VMISS = 300.0                # 导弹速度 m/s

# 真目标代表点 (题目给定: 下底面圆心)
TARGET = np.array([0.0, 200.0, 0.0])

# 导弹初值 (题目给定)
MISSILE0 = {
    "M1": np.array([20000.0, 0.0, 2000.0]),
    "M2": np.array([19000.0, 600.0, 2100.0]),
    "M3": np.array([18000.0, -600.0, 1900.0]),
}
MISSILE_KEYS = ["M1", "M2", "M3"]

# 无人机初值
UAV0 = {
    "FY1": np.array([17800.0, 0.0, 1800.0]),
    "FY2": np.array([12000.0, 1400.0, 1400.0]),
    "FY3": np.array([6000.0, -3000.0, 700.0]),
    "FY4": np.array([11000.0, 2000.0, 1800.0]),
    "FY5": np.array([13000.0, -2000.0, 1300.0]),
}
UAV_KEYS = ["FY1", "FY2", "FY3", "FY4", "FY5"]


def missile_heading(key):
    """导弹飞行方向单位向量 (指向假目标=原点)。"""
    m0 = MISSILE0[key]
    v = -m0
    return v / np.linalg.norm(v)


def missile_time_to_decoy(key):
    """导弹到假目标(原点)的飞行时间 s。"""
    return np.linalg.norm(MISSILE0[key]) / VMISS


def missile_pos(key, t):
    """t 时刻导弹位置 (沿朝向原点的直线匀速飞行)。t 可为标量或数组。"""
    m0 = MISSILE0[key]
    h = missile_heading(key)
    t = np.asarray(t, dtype=float)
    if t.ndim == 0:
        return m0 + VMISS * h * t
    return m0[None, :] + VMISS * h[None, :] * t[:, None]


def uav_pos(idx, phi_deg, v, t):
    """t 时刻无人机位置。phi 为从 +x 逆时针角度(度), 在 xy 平面, 高度不变。t 可为标量或数组。"""
    phi = np.deg2rad(phi_deg)
    p0 = UAV0[idx]
    hv = v * np.array([np.cos(phi), np.sin(phi), 0.0])
    t = np.asarray(t, dtype=float)
    if t.ndim == 0:
        return p0 + hv * t
    return p0[None, :] + hv[None, :] * t[:, None]


def _h(v):
    """把标量/数组转成 (...,3) 以便向量化。"""
    return np.asarray(v, dtype=float)


def seg_dist(P, A, B):
    """点集 P 到线段 [A,B] 的距离。P、A、B 均可为 (3,) 或 (...,3), 会广播到同一形状。"""
    P = np.asarray(P, dtype=float)
    A = np.asarray(A, dtype=float)  # (3,)
    B = np.asarray(B, dtype=float)  # (3,)
    AB = B - A
    L2 = np.sum(AB * AB, axis=-1)
    L2 = np.where(L2 < 1e-12, 1e-12, L2)   # 防零除
    PA = P - A                      # (...,3)
    t = np.sum(PA * AB, axis=-1) / L2
    t = np.clip(t, 0.0, 1.0)
    Q = A + t[..., None] * AB
    return np.linalg.norm(P - Q, axis=-1)


def cloud_center(drone_idx, phi_deg, v, tau, delta, t):
    """
    云团中心在绝对时刻 t 的位置。
    无人机在 tau 时刻于其航线上投放; 弹继承无人机水平速度, 经 delta 秒后起爆于 B;
    之后云心以 3 m/s 下沉。
    返回: 云心坐标 (3,), 以及起爆绝对时间 t_burst。
    """
    tau = float(tau)
    D = uav_pos(drone_idx, phi_deg, v, tau)          # 投放点 (3,)
    phi = np.deg2rad(phi_deg)
    hv = v * np.array([np.cos(phi), np.sin(phi), 0.0])
    B = D + hv * delta + np.array([0.0, 0.0, -0.5 * G * delta * delta])  # 起爆点 (3,)
    t_burst = tau + delta
    t = np.asarray(t, dtype=float)
    dz = -SINK * (t - t_burst)
    if t.ndim == 0:
        return B + np.array([0.0, 0.0, dz]), t_burst
    return B[None, :] + np.stack([np.zeros_like(t), np.zeros_like(t), dz], axis=-1), t_burst


def obscuring_duration(drone_idx, phi_deg, v, tau, delta, miss_key,
                       window=None, resolution=0.05):
    """
    单枚弹(由 drone_idx 用 phi/v/tau/delta 定义) 对 miss_key 导弹的
    [起爆, 起爆+20] 时段内, 云团遮蔽"目标代表点->导弹"视线段的累计时长 s。
    返回 (duration, intervals)。intervals 为 [(t0,t1), ...]。
    """
    _, t_burst = cloud_center(drone_idx, phi_deg, v, tau, delta, 0.0)
    if window is None:
        t0 = t_burst
        t1 = t_burst + CLOUD_LIFE
    else:
        t0, t1 = window
    n = int(np.ceil((t1 - t0) / resolution)) + 1
    ts = np.linspace(t0, t1, n)
    Cs, _ = cloud_center(drone_idx, phi_deg, v, tau, delta, ts)
    Ms = missile_pos(miss_key, ts)                      # (n,3)
    d = seg_dist(Cs, Ms, TARGET)                        # (n,)
    mask = d <= CLOUD_MIN_CLEAR
    # 找连续 True 区间
    intervals = []
    if np.any(mask):
        idx = np.flatnonzero(mask)
        # 分组连续
        splits = np.where(np.diff(idx) > 1)[0]
        starts = np.concatenate(([0], splits + 1))
        ends = np.concatenate((splits, [len(idx) - 1]))
        for s, e in zip(starts, ends):
            a, b = ts[idx[s]], ts[idx[e]]
            intervals.append((float(a), float(b)))
    duration = sum(b - a for a, b in intervals)
    return duration, intervals


def union_intervals(intervals):
    """合并区间 (支持从多个弹得到)。"""
    if not intervals:
        return []
    iv = sorted((max(a, 0.0), b) for a, b in intervals)
    out = []
    a, b = iv[0]
    for x, y in iv[1:]:
        if x <= b:
            b = max(b, y)
        else:
            out.append((a, b))
            a, b = x, y
    out.append((a, b))
    return out


def intersect_intervals(list_of_interval_lists):
    """求多组区间 (每组是一个已合并的区间列表) 的交集长度与区间。"""
    if not list_of_interval_lists:
        return 0.0, []
    # 从第一组开始, 依次与后续相交
    cur = list_of_interval_lists[0]
    for iv in list_of_interval_lists[1:]:
        if not cur or not iv:
            return 0.0, []
        nxt = []
        for a1, b1 in cur:
            for a2, b2 in iv:
                x, y = max(a1, a2), min(b1, b2)
                if x < y:
                    nxt.append((x, y))
        cur = nxt
    total = sum(b - a for a, b in cur)
    return total, cur


def interval_length(iv):
    return sum(b - a for a, b in iv)
