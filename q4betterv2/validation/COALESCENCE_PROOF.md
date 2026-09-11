# 安全清除后桥接合流证明

## 1. 结论的精确定义

本证明的“合流”是：相同场景、相同已清集合、相同机器人位置与 receiver、相同后续决策状态及相同原策略 continuation，同时 CT 保留一个非负的累计虚拟时间优势。它不要求包含轨迹清除坐标、计时日志和成本累计量的全部 Python 对象逐字节相等。

若把“完整 solver state”理解为连审计历史中的 q/z 和时间戳也必须相等，则任何非零节省都不可能满足。当前实现明确比较完整的**决策语义状态**，其余不同项被逐一确认不进入原 R12 的决策。不能只凭位置相等称为决策状态合流。

适用源码为交付的隔离 CT 实现与原 R12/P4、同一离线 engine。控制流证明见 `BRIDGE_ACTION_AUDIT.md`，hard-safe 证明见 `EXACT_NEIGHBORHOOD_PROOF.md`。

## 2. 状态分解与摘要内容

设决策状态 D 包含：

- 当前位置、receiver、已清频道和已确认频道；
- 剩余 discovery nodes 及其顺序；
- 所有 track 的 hard polygon、观测计数、负观测计数、views；
- 各频道完整 observation history；
- Hypotheses 的 particles、history、Generator bit state 和配置；
- local-no-signal streak、measurement_purpose、public-max/known16 状态；
- 原配置、模式、调度开关和完成条件；
- 原 run/localize/diagnostic 的控制 continuation。

`decision()` 对 DECISION_KEYS、nodes、receiver、位置作确定性语义序列化；array 包含 dtype、shape 和原始内容 hash，Generator 包含 bit state，Hypotheses 递归包含对象字段。它还保留 observations/fallbacks/certified 等计数。已确认 known16 的 time_s 去掉，但 trigger 是否存在及其频道、清除/未决数量保留。

仅排除 trace 中的时间、清除落点和物理成本日志、API 的累计虚拟时间、实验名称及原 R12 不使用的 CT/TSPN 标志。`measurement_purpose` 不排除，因为它可能影响 failure-context 计数。`stage` 属于 adapter 审计标签，不控制原 policy；其真实性另由动作轨迹核查。

摘要并不序列化 Python 调用帧。因此 control continuation 等价还需要源码证明：oracle 运行原 AST 的准确后缀，而正式执行保留原栈，并以 baseline 的暂显位置和 receiver 运行到同一 API。不能用 hash 相等代替这个控制流证明。

## 3. 两种 clear 后的差异

在共同决策状态下，原 R12 已决定清除频道 c。原 z 与候选 q 都通过同一个当前 hard polygon 的19.999m提交证书。频道已确认且未清除，因此这两条 clear 的成功结果相同。

真实 engine 的 clear 分支仅增加移动与清除费用、更新机器人位置、把 c 加入 cleared；不更新 receiver、不更新场景、不消耗动作 RNG。Solver 的成功 clear 只更新 cleared/confirmed、删除 c 的 track、增加 certified 计数和纯日志。它没有往 observation history 添加以 q 或 z 为坐标的新观测，也不更新未清频道的 hard geometry 或 Hypotheses。

所以在原 success bookkeeping 完成后，两种方案的决策状态只可能在机器人位置上不同，另有虚拟时间和日志差异。若该 clear 首次触发 known16，触发的布尔存在性和频道内容相同，只有 time_s 不同。

## 4. 同一 bridge measure 的 engine 响应

对 a0=`/measure(p,k)`，两条轨迹在提交前有相同场景、相同 cleared set 和 receiver。engine 先把位置置为同一个 p，再按 k 与旧 receiver 确定同一切频费。可接收性由源是否可用、源类型/朝向、接收半径和 p 决定。

`bearing_error(seed,k,p_x,p_y)` 使用固定坐标噪声场。它不读取 arrival path、累计 virtual_us 或之前动作数量，也不推进可变随机流。因此 measure_result 和 svd_deg 相同；累计 virtual_time_s 可不同。

bridge 执行后位置和 receiver 都相同。两方案把相同语义响应交给原 measure handler：confirm_channel、local streak、history、polygon clipping、views、计数和 Hypotheses.update 全部按相同输入更新。Generator 初态相同、筛选和重采样条件相同，故消耗同样随机数并得到相同末态。

若结果是 near，原 handler 会在 p 触发相同原地 clear。这是双方相同的后续动作；它不是放宽 CT 入口，也不是另外添加的 bridge。

## 5. 同一 bridge clear 与 exit

对 a0=`/clear(p,k)`，双方有相同 cleared set、同一目标请求和同一场景，故 available 及 distance≤20 判定相同。结果可以同为成功，也可以同为原策略原有失败；失败服务3s、成功服务5s均匹配。执行后位置、receiver 和 cleared set 相同，原 clear handler 完成同样 bookkeeping。

如果这条 bridge 本身属于 polygon-certified clear，它的原点 p 已被上一宏动作冻结。`CTSolver.clear_certified_polygon` 在 pending 时直接走原方法，禁止再次选 q。这确保上一宏动作的终点没有被下一次优化挪走。

对 a0=`/exit`，没有后续 policy continuation，也不需要构造不存在的 p。总成本比较只有当前 clear 的移动和相同清除费用；exit 响应被原 run 尾部正常消费后返回结果。

其他动作不进入本定理；实现保持原 z，采用 fallback。

## 6. 原子执行与响应消费的两个时刻

真实 clear(q) 与真实 a0 紧邻提交。a0 backend 返回时，engine 物理状态已经满足前述同一位置/receiver/cleared 关系，但原 Solver 尚未消费缓存响应。该时刻不能单独称为完整决策状态合流。

pending facade 向原栈保留 baseline z 和 bridge 之前 receiver。原栈在相同环境中完成原 localize 返回尾部、route refresh 和下一决策。到第一 API 入口时，必须与 oracle 在异常展开前保存的完整 pre-API 状态摘要相等，且请求/RNG逐项匹配。

随后缓存响应只返回一次，facade 回到实际 p 和 receiver，原 handler 执行第4或第5节的相同更新。至响应处理完成，完整决策状态合流。下一 API 边界的 A/CT状态摘要和请求序列提供运行级检查；最终 exit 则由终态/账本检查覆盖。

fallback-z 事件未发生位置扰动，其等价性是恒等关系。事件中为 fallback 设置的 pass 标志不等于“实际执行了一次非平凡 bridge”；统计 active/coalesced 时须按 adopted=true 区分。

## 7. absolute virtual time 不进入原正常策略

源码检查覆盖 Solver 的 clear、measure、confirm_channel、release_discovery、localize、run，以及 discovery、diagnostic、Hypotheses。累计 virtual_time 用于日志、known16时间和最终输出；原 action selection 不读取其数值。

known16 决策看 trigger 是否存在，不看其 time_s。diagnostic 的 estimated_cost 是当前几何/动作服务的局部预测费用，不是已经消耗的绝对时间。随机数来自各频道 Hypotheses Generator，与 engine 时间无关。

engine 的 virtual timeout 和 adapter 的真实1200s上限有终止语义，不能从状态中装作不存在。虚拟上限的单调性和真实上限的条件见 `GLOBAL_DOMINANCE_PROOF.md`。

## 8. 证明边界

本定理依赖当前 hard polygon 确实保守包含真实源；这一前提由既有几何构造证明和 evaluator 包含性审计共同支持，不靠 oracle 读取 truth。它还依赖完整 continuation、相同语义反馈、相邻宏动作不重叠和相同 compute 环境下原策略确定性。

任何 prestate/request/RNG mismatch、hard-certified clear failure、非支持动作强行桥接或 CT 获得额外观测都会破坏证明，应立即停止。全量开发与正式新128是否通过必须从对应 gates和完整 traces读取，不能只凭本文推断。
