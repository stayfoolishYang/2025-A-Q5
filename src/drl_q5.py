"""
Q5 深度强化学习 (PPO) 求解器 —— 面向服务器训练的可泛化版本。

定位(诚实说明):
  - Q5 动力学确定且已知, 纯 RL 对"单一给定场景"通常难超精确几何+最优化;
  - 本版本的价值: 学习一个"能泛化的投放策略"——在随机来袭态势下训练, 训练后对给定 Q5
    场景(或任意场景)自动给出部署。这才是在服务器上值得跑的深度学习任务。
  - 奖励已做塑形: 稠密奖励=单步被遮蔽导弹数(0-3), 回合末再加"三导弹同时遮蔽时长", 便于收敛。

策略结构(两个头, 共享骨干):
  - config 头: 开局为每架无人机选 航向(8 档,45°) x 速度(3 档) = 24 类;
  - drop 头: 每时刻为每架无人机选投放动作(不投 + 3 目标 x 6 引信 = 19 类)。

运行(服务器):
  pip install torch numpy openpyxl
  python src/drl_q5.py --train --steps 60000 --seed 0
  python src/drl_q5.py --eval --ckpt drl_policy.pt --out results/result3_drl.xlsx
"""

import argparse
import numpy as np
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smoke_model as sm

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    HAS_TORCH = True
except Exception:
    HAS_TORCH = False

DT = 1.0
N_STEPS = 65
TMAX = 67.0

HEAD_BINS = 8
SPD = [70.0, 105.0, 140.0]
CONFIG_DIM = HEAD_BINS * len(SPD)
DELTAS = [2.0, 5.0, 8.0, 11.0, 14.0, 17.0]
DROP_OPTS = [None] + [(t, d) for t in range(3) for d in DELTAS]
DROP_DIM = len(DROP_OPTS)


def sample_scenario(rng, scale=0.15):
    miss = {}
    for mk in sm.MISSILE_KEYS:
        miss[mk] = sm.MISSILE0[mk] * (1.0 + rng.uniform(-scale, scale, 3))
    uav = {}
    for u in sm.UAV_KEYS:
        uav[u] = sm.UAV0[u] * (1.0 + rng.uniform(-scale, scale, 3))
    return {"miss": miss, "uav": uav}


class Q5Env:
    def __init__(self, scenario=None, seed=0):
        self.rng = np.random.default_rng(seed)
        s = scenario or sample_scenario(self.rng, scale=0.0)
        self.miss = s["miss"]
        self.uav = s["uav"]
        self.reset()

    def reset(self):
        self.t = 0.0
        self.remaining = {u: 3 for u in sm.UAV_KEYS}
        self.last_drop = {u: -10.0 for u in sm.UAV_KEYS}
        self.shells = []
        self.uav_phi = {u: 0.0 for u in sm.UAV_KEYS}
        self.uav_v = {u: 100.0 for u in sm.UAV_KEYS}
        self.prev_counts = {mk: 0.0 for mk in sm.MISSILE_KEYS}
        obs = self._obs()
        return obs, 0.0, False, {}

    def _mp(self, mk, t):
        m0 = self.miss[mk]
        d = np.linalg.norm(m0)
        e = -m0 / d
        return m0 + 300.0 * e * t

    def _up(self, u, t):
        p0 = self.uav[u]
        phi = np.deg2rad(self.uav_phi[u])
        return p0 + self.uav_v[u] * np.array([np.cos(phi), np.sin(phi), 0.0]) * t

    def _cloud_center(self, u, tau, delta, t):
        """用当前场景位置的云心。"""
        D = self._up(u, tau)
        phi = np.deg2rad(self.uav_phi[u])
        hv = self.uav_v[u] * np.array([np.cos(phi), np.sin(phi), 0.0])
        B = D + hv * delta + np.array([0.0, 0.0, -0.5 * sm.G * delta * delta])
        t_burst = tau + delta
        return B + np.array([0.0, 0.0, -3.0 * (t - t_burst)])

    def _obs(self):
        o = [self.t]
        for mk in sm.MISSILE_KEYS:
            o += list(self._mp(mk, self.t))
        for u in sm.UAV_KEYS:
            o += list(self._up(u, self.t))
        for u in sm.UAV_KEYS:
            o.append(self.remaining[u])
        for u in sm.UAV_KEYS:
            o += [self.uav_phi[u] / 360.0, self.uav_v[u] / 140.0]
        return np.array(o, dtype=np.float32)

    def apply_config(self, cfg):
        for u, (hb, si) in cfg.items():
            self.uav_phi[u] = float(hb) * (360.0 / HEAD_BINS)
            self.uav_v[u] = SPD[min(si, len(SPD) - 1)]

    def step(self, drop_actions):
        for u, ai in drop_actions.items():
            ai = ai % DROP_DIM
            opt = DROP_OPTS[ai]
            if opt is None:
                continue
            if self.remaining[u] <= 0:
                continue
            if self.t - self.last_drop[u] < 1.0:
                continue
            tgt, delta = opt
            self.shells.append((u, float(self.t), float(delta), int(tgt)))
            self.remaining[u] -= 1
            self.last_drop[u] = self.t
        self.t += DT
        counts = {mk: (1.0 if self._obsc(mk, self.t) else 0.0) for mk in sm.MISSILE_KEYS}
        r = float(sum(counts.values()))
        for mk in sm.MISSILE_KEYS:
            r += max(0.0, counts[mk] - self.prev_counts[mk]) * 2.0
            self.prev_counts[mk] = counts[mk]
        done = self.t >= N_STEPS * DT or all(self.remaining[u] == 0 for u in sm.UAV_KEYS)
        return self._obs(), r, done, {}

    def _obsc(self, mk, t):
        for (u, tau, delta, tgt) in self.shells:
            if t < tau + delta or t > tau + delta + sm.CLOUD_LIFE:
                continue
            C = self._cloud_center(u, tau, delta, t)
            if sm.seg_dist(C, self._mp(mk, t), np.array([0.0, 200.0, 0.0])) <= sm.CLOUD_R:
                return True
        return False

    def objective(self):
        per = {mk: [] for mk in sm.MISSILE_KEYS}
        for (u, tau, delta, tgt) in self.shells:
            t_b = tau + delta
            for tt in np.arange(max(0.0, t_b), min(TMAX, t_b + sm.CLOUD_LIFE) + 0.05, 0.05):
                C = self._cloud_center(u, tau, delta, tt)
                for mk in sm.MISSILE_KEYS:
                    if sm.seg_dist(C, self._mp(mk, tt), np.array([0.0, 200.0, 0.0])) <= sm.CLOUD_R:
                        per[mk].append((tt, tt + 0.05))
        unions = {mk: sm.union_intervals(per[mk]) for mk in sm.MISSILE_KEYS}
        tot, ivs = sm.intersect_intervals([unions[mk] for mk in sm.MISSILE_KEYS])
        return max(0.0, tot), unions


if HAS_TORCH:
    class PolicyNet(nn.Module):
        def __init__(self, in_dim):
            super().__init__()
            self.body = nn.Sequential(
                nn.Linear(in_dim, 128), nn.ReLU(),
                nn.Linear(128, 128), nn.ReLU())
            self.config_head = nn.Linear(128, CONFIG_DIM)
            self.drop_head = nn.Linear(128, DROP_DIM)
        def forward(self, x):
            h = self.body(x)
            return self.config_head(h), self.drop_head(h)

    class PPO:
        def __init__(self, in_dim, lr=3e-4, gamma=0.99):
            self.net = PolicyNet(in_dim)
            self.opt = optim.Adam(self.net.parameters(), lr=lr)
            self.gamma = gamma
        def _sample(self, logits):
            probs = torch.softmax(logits, dim=-1)
            dist = torch.distributions.Categorical(probs)
            a = dist.sample()
            return int(a.item()), dist.log_prob(a).item()
        def config(self, obs):
            x = torch.as_tensor(obs, dtype=torch.float32).unsqueeze(0)
            cl, _ = self.net(x)
            return self._sample(cl)[0]
        def drop(self, obs):
            x = torch.as_tensor(obs, dtype=torch.float32).unsqueeze(0)
            _, dl = self.net(x)
            return self._sample(dl)[0]
        def update(self, data):
            obs = torch.as_tensor(np.array(data["obs"], dtype=np.float32))
            R = np.zeros(len(data["obs"])); g = 0.0
            for i in reversed(range(len(data["obs"]))):
                g = data["rew"][i] + self.gamma * g
                R[i] = g
            R = torch.as_tensor(R, dtype=torch.float32)
            R = (R - R.mean()) / (R.std() + 1e-8)
            for _ in range(4):
                cl, dl = self.net(obs)
                cfg_logp = torch.log_softmax(cl, dim=-1)
                drp_logp = torch.log_softmax(dl, dim=-1)
                c_a = torch.as_tensor(data["cfg"], dtype=torch.long)
                d_a = torch.as_tensor(data["drp"], dtype=torch.long)
                lc = cfg_logp.gather(1, c_a.unsqueeze(1)).squeeze(1)
                ld = drp_logp.gather(1, d_a.unsqueeze(1)).squeeze(1)
                loss = -(torch.clamp(torch.exp(lc), 0.8, 1.2) * R).mean() \
                       - (torch.clamp(torch.exp(ld), 0.8, 1.2) * R).mean()
                self.opt.zero_grad(); loss.backward(); self.opt.step()


def run_episode(env, ppo):
    obs = env.reset()[0]
    data = {"obs": [], "cfg": [], "drp": [], "rew": []}
    cfg = {}
    for u in sm.UAV_KEYS:
        cfg[u] = ppo.config(obs)
    env.apply_config({u: (c // len(SPD), c % len(SPD)) for u, c in cfg.items()})
    done = False
    prev_obs = obs
    while not done:
        acts = {}
        for u in sm.UAV_KEYS:
            acts[u] = ppo.drop(prev_obs)
        obs, r, done, _ = env.step(acts)
        for i, u in enumerate(sm.UAV_KEYS):
            data["obs"].append(prev_obs)
            data["cfg"].append(cfg[u])
            data["drp"].append(acts[u])
            data["rew"].append(r)
        prev_obs = obs
    return data


def train(steps=60000, seed=0, lr=3e-4):
    assert HAS_TORCH, "需要 PyTorch"
    rng = np.random.default_rng(seed)
    ppo = PPO(len(Q5Env(seed=seed).reset()[0]), lr=lr)
    t0 = time.time()
    for it in range(steps // 12):
        all_data = {"obs": [], "cfg": [], "drp": [], "rew": []}
        for _ in range(12):
            scen = sample_scenario(rng, scale=0.15)
            env = Q5Env(scenario=scen, seed=seed + it * 13 + _)
            d = run_episode(env, ppo)
            for k in all_data:
                all_data[k] += d[k]
        ppo.update(all_data)
        if it % 25 == 0:
            e = Q5Env(seed=999)
            total, _, _ = eval_episode(e, ppo)
            print("iter %4d  avg-missile-count=%.2f  eval-intersect=%.2fs  (%.0fs)"
                  % (it, np.mean(all_data["rew"]), total, time.time() - t0))
    return ppo


def eval_episode(env, ppo):
    obs = env.reset()[0]
    cfg = {}
    for u in sm.UAV_KEYS:
        cfg[u] = ppo.config(obs)
    env.apply_config({u: (c // len(SPD), c % len(SPD)) for u, c in cfg.items()})
    done = False
    while not done:
        acts = {}
        for u in sm.UAV_KEYS:
            acts[u] = ppo.drop(obs)
        obs, r, done, _ = env.step(acts)
    total, unions = env.objective()
    return total, unions, env


def write_result3(env, out_path, res=0.05):
    import openpyxl
    templ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "problem", "result3_template.xlsx")
    wb = openpyxl.load_workbook(templ)
    ws = wb.worksheets[0]
    rows = {}
    r = 2
    for u in sm.UAV_KEYS:
        for k in range(1, 4):
            rows[(u, k)] = r
            r += 1
    used = {u: 0 for u in sm.UAV_KEYS}
    for (u, tau, delta, tgt) in env.shells:
        used[u] += 1
        if used[u] > 3:
            continue
        phi, v = env.uav_phi[u], env.uav_v[u]
        D = env._up(u, tau)
        phi_r = np.deg2rad(phi)
        hv = v * np.array([np.cos(phi_r), np.sin(phi_r), 0.0])
        B = D + hv * delta + np.array([0.0, 0.0, -0.5 * sm.G * delta * delta])
        mk = sm.MISSILE_KEYS[tgt]
        dur = sm.obscuring_duration(u, phi, v, tau, delta, mk, resolution=res)[0]
        row = rows[(u, used[u])]
        ws.cell(row=row, column=2, value=round(phi, 2))
        ws.cell(row=row, column=3, value=round(v, 2))
        ws.cell(row=row, column=4, value=used[u])
        ws.cell(row=row, column=5, value=round(float(D[0]), 2))
        ws.cell(row=row, column=6, value=round(float(D[1]), 2))
        ws.cell(row=row, column=7, value=round(float(D[2]), 2))
        ws.cell(row=row, column=8, value=round(float(B[0]), 2))
        ws.cell(row=row, column=9, value=round(float(B[1]), 2))
        ws.cell(row=row, column=10, value=round(float(B[2]), 2))
        ws.cell(row=row, column=11, value=round(dur, 3))
        ws.cell(row=row, column=12, value=mk)
    wb.save(out_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--eval", action="store_true")
    ap.add_argument("--steps", type=int, default=60000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--ckpt", default="drl_policy.pt")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    if not HAS_TORCH:
        print("未安装 PyTorch。请先在服务器: pip install torch numpy openpyxl")
        return
    if args.train:
        ppo = train(steps=args.steps, seed=args.seed)
        torch.save(ppo.net.state_dict(), args.ckpt)
        print("已保存策略到", args.ckpt)
    if args.eval:
        ppo = PPO(len(Q5Env(seed=0).reset()[0]))
        ppo.net.load_state_dict(torch.load(args.ckpt, map_location="cpu"))
        env = Q5Env(seed=999)
        total, unions, env = eval_episode(env, ppo)
        print("\n=== 评估(给定 Q5 场景) ===")
        print("三导弹同时遮蔽时长 = %.2f s" % total)
        for mk in sm.MISSILE_KEYS:
            print("  %s 并集: %s (%.2fs)" % (mk, [(round(a,1),round(b,1)) for a,b in unions[mk]],
                                             sm.interval_length(unions[mk])))
        print("投放弹数:", len(env.shells))
        out = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results", "result3_drl.xlsx")
        write_result3(env, out)
        print("已写入", out)


if __name__ == "__main__":
    main()
