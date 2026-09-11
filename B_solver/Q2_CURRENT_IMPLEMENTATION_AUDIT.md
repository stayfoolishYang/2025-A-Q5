# Q2 当前实现审计（实现前）

起点：`q4-diagnostic-recovery@7c90ba18c863d7bb99266ad992dbe5d648a46426`。
工作分支：`q2-continuous-safe-region`。完整初始 dirty 清单保存在
`J:/2026B_experiments/q2_continuous_20260911/START_STATE.json`；其中没有 B_solver 改动。

真实调用链：`questions.q2_example` → `disk/wedge/intersect_disk` → 旋转网格
→ `geometry.next_view(safe_only=True)` → `wedge` → `diameter` → 最大情景直径
→ 加 `.2*(移动距离/5+5)` → 枚举取最小值。

* 固定首测 p=(0,0)，theta=30°，工程半角 `ERROR_DEG=1.00500001°`。
* 首测域是 1800 m 目标圆的 128 边外切多边形，与首测 wedge 及 1500 m
  接收上限的 64 半平面外包相交；结果四顶点。它不是精确弧边扇形。
* 已使用首次收到信号的 `r<=1500` 信息，未使用 `R>=max(1000,r)` 扩大站位域。
  direction 蕴含的 `r>5` 没有从评分外包域中扣除。
* 首测局部 x=0:50:1500，y=-600:40:600，旋转 30°，961 点。
  所有外包顶点距站位 <=1000 m 筛出 213 点；此处顶点充分性来自距离凸性。
* 五个代表位置（四顶点加算术均值），各报告角取 -ERROR、0、+ERROR，共15情景。
  只裁剪第二 wedge；未显式评价 near，也未移除不可能报告或 near 的方向情景。
* T 只含从首测点移动（5 m/s）和第二次检测5秒；不含首测、清除、切换频道。
  J=D+lambda*T 的量纲为 m，lambda=.2 m/s。
* 共享 `geometry.diameter` 仍为旧旋转卡尺。已保存的近重复点反例会低估直径，
  但此前对3195情景复核显示旧213点各自最大值不变，不能把修复当优化收益。
* `experiments/q2_score_audit.py` 的 `pair_diameter` 与 `continuous_envelope`
  已提供 FP64 最远顶点对和连续报告角自适应包络。中心角作数值下值，扩大 wedge
  覆盖角区间作数值上值，72初始区间，gap=.01 m；这不是带浮点误差证明的严格 supremum。
* 实际 near 半径5 m，保证收到有效响应不保证 direction。首次 near 已满足20 m
  清除距离，不需要第二测点；这里只返回处置说明，不发动作。

隔离决定：Q2 新模块复用已有 all-pairs 和连续包络；仅 Q2 旧入口切换到稳定15情景
实现。共享 geometry、solve_q1、Q3/Q4、CUDA、客户端不改。旧结果不覆盖。
评分保持原外包后验，方向代理允许保守的不可实现报告；near 单独记录安全直径上界。
