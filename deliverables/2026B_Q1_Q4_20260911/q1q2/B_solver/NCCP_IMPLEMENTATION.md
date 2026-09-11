# NCCP 实现与审计口径

本文区分 `eb24b8c` 原两方案冻结实验和之后的独立 segment/安全护栏修订。前六节中原始字段说明以旧冻结证据为准；新实现差别集中列于第 7 节。NCCP 只改变已有多边形清除证书成立后的落点。默认仍去 MEC 中心，Q3/Q4 的发现骨架、定位更新、候选生成与 diagnostic v1 主评分保持原有逻辑。

**当前状态为 `LOCAL_R_AND_D_ACCEPT`**，以 `J:/2026B_experiments/nccp_20260911/LOCAL_ACCEPTANCE.json` 为准。95 项离线测试、1424 条历史轨迹的 476867 个动作精确回放、712 次新 segment 全场景运行、42 例 shadow 一致性及 8984 个固定快照门禁均已完成。该验收限于有效硬域上的可选清除落点和已审计本地证据；默认仍为 MEC，不代表整局不劣、官方成绩或上游观测矛盾可自动恢复。旧冻结实现的 invalid 恢复缺口及修订范围见第 7 节。

## 1. 实际调用链

| 环节 | 实际代码与行为 |
|---|---|
| 硬可行域更新 | `solver.py: Solver.measure`；`direction` 后使用 `geometry.wedge` 和 `intersect_disk` 收紧 `track['poly']`。圆约束以外包多边形表示。`no_signal` 不据此裁去硬位置域；粒子仅用于启发式动作选择。 |
| 普通清除触发 | `Solver.localize` 计算 `geometry.mec(poly)`，仅在现有返回半径 `radius <= 19.999` 时调用 `clear_certified_polygon`。 |
| diagnostic 清除触发 | `directional/diagnostic_recovery.py: recover` 在每次诊断前、最大步数结束后检查同一 MEC 条件，然后调用相同入口。 |
| 清除落点 | `Solver.clear_certified_polygon` 保存当前位置及硬域。默认采用传入 MEC 中心；`clearance_point='nccp'` 时调用 `geometry.nearest_certified_clear_point`。 |
| 清除执行 | `Solver.clear(channel, point, certified=True)` 调用 `api.action('/clear', point, channel)`。移动、光学搜索、清除属于这一请求的模拟语义，代码没有额外的 `/move` 或 `/optical` 请求。 |
| 阶段标记 | `phase_audit.TaggedSolver.clear` 把该请求标为 `certified_clear`，普通光学兜底标为 `optical_fallback`。 |
| 本地评测 | `recovered_benchmark.run_single` → `AuditedSolver(TaggedSolver)` → `EngineAdapter` → 本地 `G:/QQ/jammers_linux/engine.py: Engine.apply`。真值只用于 evaluator 的包含性审计，不进入求解器选点输入。 |
| 证据复核 | `reporting/nccp_report.py` 读取冻结 scene、逐例 row 和 `.json.gz` trace；按 seed 配对，重新检验落点，匹配真实 `/clear` 动作与成功响应。 |

因此，“证书成立后默认固定移动到 MEC 中心”的假设对**多边形证书分支**成立。另有既有 `measure_result='near'` 分支：直接在该测点清除，不计算 NCCP、不经过上述多边形选点入口，也没有额外移动。

本地 `/clear` 成功时耗时为 `distance/5 + 3 + 2` 秒；其中 3 秒为光学搜索、2 秒为清除。当前清除请求不额外计入测量频道切换费用。失败光学尝试为 `distance/5 + 3` 秒。报告逐动作核对这本账。

## 2. 安全清除域及其证明

物理清除半径是 **20 m**，硬证书使用 **19.999 m**。二者相差 0.001 m；不能把数值容差加到 19.999 上扩大安全判定。

对非空有效硬域

\[
\Omega=\operatorname{conv}\{v_1,\ldots,v_m\},\qquad
C_r(\Omega)=\bigcap_{j=1}^m\overline B(v_j,r),\quad r=19.999,
\]

只需检查全部顶点。若 `max_j ||v_j-c|| <= r`，对任何 `x=Σ α_j v_j`、`α_j>=0`、`Σα_j=1`，

\[
\|x-c\|\leq\sum_j\alpha_j\|v_j-c\|\leq r.
\]

于是整个硬可行域都被清除圆覆盖。这个推论以真实目标仍在硬域中为前提；NCCP 不负责修复错误观测或已经丢失真值的硬域。

对**精确数学 MEC**，`R_MEC <= r` 与 `C_r` 非空等价：前者的 MEC 中心是交集中的可行点，后者给出一个半径不超过 r 的包围圆。代码 `mec` 的半径为所有顶点到返回中心的最大 FP64 范数再加 `1e-8`，是保守触发量；不能把它与理想最小半径逐位等同，也不能据此宣称所有精确可清除边界状态必被当前触发器接受。

理想 NCCP 定义为唯一的欧氏投影：

\[
c^*=\arg\min_{c\in C_r(\Omega)}\|c-x_{\rm dog}\|.
\]

非空 `C_r` 是闭有界凸集，因此投影存在且唯一。MEC 中心是可行备选，但一般不是离机器狗最近的可行点。

## 3. 二维候选枚举与保守实现

`geometry.nearest_certified_clear_point` 无额外数值优化依赖。几何构造用 NumPy FP64；最终安全比较另用标准库 `Fraction` 对保存的二进制浮点坐标做精确有理数平方距离复核。

1. 检查 polygon、当前位置、MEC 中心、半径是否非空、有限且维数正确；顶点使用 `np.unique` 去重。调用链保证输入为硬凸域，独立函数并不额外证明顶点顺序、凸性或观测一致性。
2. 用每个顶点核验提供的 MEC 中心及声明半径。中心不合法时不能把它当作回退证书。
3. 若当前位置已经满足所有圆约束，直接返回当前位置，模式 `already_certified`，移动为 0。
4. 枚举当前位置对每个顶点圆的径向边界投影。当前位置等于圆心时跳过该径向构造，避免除以 0。
5. 枚举两顶点等半径圆的 0、1、2 个交点；重合圆心已去重或跳过，相切时只加入一个点。交点高度用 `sqrt(max(0,(r-d/2)(r+d/2)))` 计算。
6. 候选按移动距离、模式与坐标稳定排序，全部检验所有顶点约束。最佳解初始化为合法 MEC 中心，因此保留旧落点作为移动上界和安全备选。
7. 边界构造可能向外舍入。仅用于保留可修复候选的 `construction_guard=128*eps*scale` 不进入最终安全半径。略向外的候选沿其到合法 MEC 中心的线段向内修复，插值比例按 `2^-48, 2^-44, …, 1` 增大；仍以严格条件复核。
8. 仅接受 FP64 移动距离比当前最佳值更短、且精确平方距离不大于前往原 MEC 中心的候选；无可采用候选时返回原 MEC 中心，模式 `mec_fallback`。

理想二维投影若不在当前位置，落于单个光滑圆弧时是该圆的径向投影，落于两个及以上圆弧交会处时属于圆圆交点，因此精确候选枚举覆盖最优点。**实现因保守向内修复或回退可能偏离精确投影**；实际保证是返回点安全且同状态移动不大于 MEC 中心，不能宣称每个浮点输出都精确达到全局最短距离。

候选数为 `O(m²)`，逐候选检查 m 个圆的直接实现为 `O(m³)`；本轮不更改硬域顶点数或规划器来追求额外性能收益。

## 4. 最终安全检查与局部保证

最终清除半径条件是 `rho_check <= 19.999`，不存在 `rho_check <= 19.999 + epsilon` 的放宽。NCCP 选择器同时要求：

- FP64 范数逐顶点通过；
- 在**坐标相减以前**把原浮点数转为 `Fraction(float)`，精确检验距离平方不超过安全半径平方；
- 同样用精确平方距离检验从当前机器狗位置到返回点不远于到传入 MEC 中心。

这些精确检查针对程序保存的二进制浮点坐标，避免减法或平方根向下舍入造成假通过；它们不代表对未知连续观测误差进行额外建模。原 `eb24b8c` 默认 MEC 执行入口保留 FP64 复核，报告对两方案再统一执行 FP64 与精确距离审计；修订后的实际 JSON 提交双重复核见第 7 节。

只要参考 MEC 中心合法，则同一当前状态下：

\[
\Delta_{\rm move}=\|x_{\rm dog}-c_{\rm MEC}\|-\|x_{\rm dog}-c_{\rm returned}\|\geq0.
\]

位置与硬域固定、两方案随后成功光学+清除费用相同，直接节省的虚拟时间为 `Delta_move/5`。报告任何顶点越界或同状态负节省都停止性能结论；只有冗余账本值的比较允许 `1e-9 m`，序列化动作时间账本允许 `1.1e-6 s`，安全不等式没有这类容差。

更具体的理论界使用**精确 MEC 中心 M**：M 位于顶点凸包内。任意 `c∈C_r` 到每个顶点距离不超过 r，因此由凸组合也有 `||c-M||<=r`。再由反三角不等式，

\[
0\leq\|x-M\|-\|x-c^*\|\leq\|M-c^*\|\leq r.
\]

所以同状态每次成功多边形清除直接节省时间最多 `19.999/5 = 3.9998 s`。这是速度为 5 m/s、比较对象为精确 MEC 中心、其余清除费用相同的理论界。返回中心有浮点构造误差时，逐例数值比较必须另计该误差。已完成的固定快照审计独立重建精确 MEC 支持圆并记录旧圆心误差，平方根上界仍注明为数值显示；不把带 `1e-8` 裕量的代码半径代入更强的 `sqrt(r²−R²)` 界。

更紧的界也有严格的**精确 MEC 最优性前提**。令精确半径为 R，取 MEC 圆周上至多三个支持点，使 `M=Σα_i v_i`、`Σα_i=1`、`α_i>=0`，且支持点均满足 `||v_i-M||=R`。对任何保证站位 c，

\[
\sum_i\alpha_i\|v_i-c\|^2
=R^2+\|c-M\|^2\leq r^2.
\]

故 `C_r ⊆ B(M,sqrt(r²-R²))`，单段节时不超过 `sqrt(r²-R²)/5`。当 R 趋近 r，可利用的站位空间缩小；R=r 时交集只有 M。这个界不能对任意未证明最优的包围圆中心/半径直接套用，也不能把 `mec` 返回的最大距离加裕量当作精确 R。固定快照的 R 分布与上界若使用数值 MEC，必须区分“带误差证明的可验收界”和“数值参考估计”，不能把后者升级为新安全门禁。

落点改变后，后续测点、发现路线重排和位置/频道调度可能发生变化。NCCP **不保证每局总时间不增加，也不保证平均收益显著**。整局秒/源改善超过 3.9998 并不与上述单状态界冲突；此时还包含后续路径变化。开发集已出现回退案例，必须保留。

### 沿原路提前清除：独立第三对照的数学范围

新要求增加 `segment_entry` 对照，定义在线段 `q(t)=x+t(M-x), 0<=t<=1` 上第一个进入 `C_r` 的站位。它与 NCCP 是两种不同的站位选择；原 `eb24b8c` 两方案实验没有该策略，其实现/新实验必须单列，不能回填原配对结果。

令 `d=M-x`，每个顶点给出一元二次不等式

\[
\|d\|^2t^2+2d\cdot(x-v_j)t+\|x-v_j\|^2-r^2\leq0.
\]

逐顶点求线段上的可行区间并相交，最左端是最早安全参数；当前位置已可行时取 t=0，M 合法则 t=1 始终有证书。精确二次区间构造为 `O(m)`；若实现使用固定迭代次数 k 的二分及逐顶点复核，实际为 `O(km)`，不能把两者的实现复杂度混写。最终坐标仍必须做严格覆盖复核，数值未解时回退**已验证**的 MEC 中心。没有新候选不意味着原证书失效，不应因此强迫更多定位。

相对任意**同一个固定下一站 y**，线段点 q 满足

\[
\|x-q\|+\|q-y\|
\leq\|x-q\|+\|q-M\|+\|M-y\|
=\|x-M\|+\|M-y\|.
\]

因此精确在线段上的提前清除既有当前段不劣，也有固定下一站的两段路径不劣。普通 NCCP 只保证当前段最短；其返程/下一转场可能抵消局部节省。两段不劣仍不等于自由重调度后的整局不劣。若程序坐标因逐分量舍入不严格在线段上，需另行控制误差或复核两段账本，不能只凭变量名 `segment_entry` 宣称数值上无误差地继承证明。

| 站位 | 理想优化对象 | 保证范围 | 朴素构造成本 |
|---|---|---|---|
| MEC 中心 | 最小覆盖半径 | 原清除证书 | 沿用既有 MEC 计算 |
| segment_entry | 原线段上最早进入保证站位区域 | 当前段不劣；固定下一站两段不劣 | 二次区间法 O(m)，二分实现 O(km) |
| NCCP | 全部保证站位中的最近点 | 当前段最短；任意下一转场不作保证 | 候选加全约束复核 O(m³) |

固定快照应共享同一 polygon、当前位置、参考 MEC，并记录三种输出的实际覆盖余量、单段距离、CPU 现实计算时间及回退原因。下一动作 y 应保留其动作类型、位置、频道；“同一 y 的反事实两段距离”与“两条真实轨迹各自选择的下一站”是不同指标。CPU 测时不混入虚拟得分，不从计时噪声推断策略收益。保证站位区域需内保，不能复用目标可能位置的外切多边形近似去产生可执行点。

## 5. 配置与原始字段映射

沿用工程 JSON 配置，不增加平行命名系统：

```json
{"clearance_point": "mec_center"}
```

字段省略时同样为 `mec_center`。启用 NCCP 使用 `{"clearance_point":"nccp"}`；非法枚举值抛 `ValueError`。Q3 和 Q4 各有独立配置对象，可分别开启。冻结实验基线名保持 `P3_current_grid_v1`、`P4_diagnostic_v1_grid_v1`；候选只追加名称后缀 `_nccp` 与 `clearance_point='nccp'`，其他配置逐字段相等。

| 请求中的语义 | 原 eb24b8c trace / row 字段或只读派生方式 |
|---|---|
| certificate_method | 多边形事件位于 `targets[].certified_clearance_events[]`，隐含现有 MEC 触发；选择器的精确检查说明在 `selection.certification`。当前没有独立同名字段，不能声称已原名输出。 |
| clearance_point_policy | 事件 `selector`；row 的 `clearance_point`。 |
| mec_radius / mec_center | 事件同名字段。 |
| nccp_point | 事件 `point`；基线时同字段保存 MEC 中心。 |
| dog_position_before_clearance_move | 事件 `start`。 |
| distance_to_mec_center / distance_to_nccp | 事件 `mec_travel_m` / `travel_m`；后一字段基线时同样是其实际移动。 |
| rho_check_nccp | 事件 `max_vertex_distance`。 |
| direct_clear_from_current_position | 事件 `zero_move`；选择器模式 `selection.mode='already_certified'`。near 原地分支另计。 |
| fallback_to_mec_reason | `selection.fallback` 和 `selection.mode='mec_fallback'` 表示未采用更短合法候选；并记录 `candidate_count`、`adjusted_candidate_count`、`numerical_adjustment_m`。原冻结事件没有细分失败原因码，不能把聚合模式解释成某个具体数值病因。 |
| 同状态节省 | 事件 `same_state_saving_m`；row 合计 `same_state_clear_saving_m`。 |
| 实际证书段移动 | row `polygon_clear_travel_m`，按本方案实际轨迹加总；不是同状态反事实移动。 |
| near 原地清除 | row `near_certified_count`，报告匹配紧邻的同位置同频道 near 观测和成功 clear。 |

报告增加的“当前位置已有多边形证书”从保存的 polygon 与 start 按 FP64+精确平方距离复算，不修改原 row。它可在基线中为真，即使基线仍移动到 MEC 中心。分别记录事件数与至少出现一次的案例数；near 不计入这个多边形状态数。全部零移动 clear 为 near 与多边形零移动事件之和，案例数按案例去重。

## 6. 实验账本和报告边界

开发集 100 seeds 为旧 519 regression/stress suite 的预先冻结子集，另有预先冻结、与旧 519 验重的新 256 seeds 留出集；两批各做 Q3/Q4 两方案，分别 400/1024 次。它们是本地恢复演练引擎上的确定性设计种子，不是官方正式测试，也不声称 IID 随机样本。查看候选结果后不能继续调参再把同一留出集称作独立验证。

`nccp_report.py` 的 `NCCP_AUDIT.json` 和扩展 `NCCP_PAIRS.csv` 保留计划分母、全清除率、EXCEPTION/PROTOCOL_ERROR/TIMEOUT 等互斥状态、P50/P95/P99/max、总时间/总路程、证书段米数及平均米/源、当前站位已具证书数、零移动数、NCCP 回退数、局部最小节省，以及配对胜/平/负和最大回退。异常证据计数可与上述状态重叠，单独注明。时间分位数只计合法全清除案例；`total_observed_*` 保留含失败的全部观察总量。

报告独立复核每次证书并逐事件匹配 clear。开发集 200 条旧基线须与历史 `3c4e844` 的每个动作及物理指标精确相等；新留出没有历史轨迹，该项明确不适用，以开发审计通过为前置。冻结输入、配置、scene、源码指纹及 CSV/trace 互相核对，已有 acceptance 只读。

`nccp_summary.py` 在两批完成且 `performance_conclusion_allowed=true` 后才能生成合并呈现，Q4 在前、Q3 为对照，新增 P50 与完整计数也从配对 CSV 核对。报告将**实际独立轨迹的证书段路程差**、**候选自身状态内的局部反事实节省**、**全程实际路程差**分开，不把三者互换。小证据副本与生成文件均登记来源路径和 SHA256，完整 trace 留在 J 盘。

## 7. 独立修订：segment、JSON 后复核与失败护栏

用户新要求：“polygon 为空/非有限、MEC 数值失败、没有硬复核通过的站位，应返回明确失败状态并继续旧流程/更多定位，不得 clear。”

`eb24b8c` 的行为是：`nearest_certified_clear_point` 对非法输入/非法 MEC 证书抛 `ValueError`；`clear_certified_polygon` 对不合法触发或落点抛 `RuntimeError`；`measure` 对空硬域也抛 `RuntimeError`。本地 runner 记录为 EXCEPTION。这些旧行为不会发出错误清除指令，但并不恢复继续定位，旧报告不能虚称已满足新要求。

独立修订 `57331d2c73f5f408014723f70cea9a466c1644de` 已在共享清除入口实现以下行为，原 `mec` 和 NCCP 算法输出保持原有构造：

| 条件 | 新版行为 |
|---|---|
| wrapper 收到空/非有限 hard polygon、非法当前位置/半径、MEC 中心无法证明覆盖 | 记录 `targets[].certificate_failures[]`，含 `reason, selector, time`，返回 `False`，不发 `/clear`。 |
| `localize` 的原 MEC 触发后 wrapper 返回 False | 不执行原来的立即 return，继续既有定位/兜底分支；未增加新的规划评分或候选。 |
| 原 MEC 合法，但 NCCP/segment 选择器抛数值异常、输出格式无效、落点硬复核失败 | 对原 MEC 中心走相同严格提交复核；通过才作 `mec_fallback` 清除，同时记录原因。没有新候选不会触发不必要的重新定位。 |
| 连 MEC 中心也没有合法可提交坐标 | 记录 `no_verified_submission_point` 并返回 False。 |
| `/clear` 已发出后出现网络/协议错误或 certified clear 失败 | 向外传播原执行异常，不被选择器异常捕获，不自动重发清除操作。 |
| 上游观测更新得到空硬域，或在进入 wrapper 前旧 `mec` 已因非法 hard set 失败 | 保持完整性拒绝和安全终止；不能把不可信硬域伪造为可继续使用的外包。新护栏不承诺自动修复这种建模/观测矛盾。 |

新增共享函数 `geometry.exact_squared_distance` 与 `geometry.is_certified_clear_point`：后者对无效输入返回 False，正常输入仍须 FP64 与精确有理数双检。wrapper 把待提交点按 Client 的 `float → JSON {x,y} → parsed coordinate` 路径往返后，再严格检查覆盖和相对 MEC 移动；验证的是实际提交坐标，不只检查内部构造值。

正常事件新增 `verification_status`，取 `MEC_CENTER_VERIFIED`、`NCCP_CANDIDATE_VERIFIED`、`SEGMENT_ENTRY_VERIFIED` 或 `MEC_FALLBACK`；另有 `submitted_position={x,y}`、`json_roundtrip_verified=true`。选择器回退使用 `selection.fallback_reason`。`certificate_failures` 表示没有证书的失败返回，不伪记成成功事件。现实计算时间不写入核心事件，避免污染确定性回放；独立 `clearance_snapshot_audit.py` 记录单次 `*_compute_ms`。

`geometry.segment_certified_clear_point` 已实现反向参数化 `q(s)=M+s(x−M)`，从已认证 M 向当前位置求最大可行 s；各圆约束用稳定二次上根求解，逐顶点取最小根，复杂度 O(m)。根附近失败时以固定数量的内缩比例修复，再经 JSON 往返、FP64 与 Fraction 复核。最终模式为 `already_certified / segment_entry / mec_fallback`，记录 `segment_parameter_from_current=1−s`、`fallback_reason` 和需要修复时的 `inward_repair_fraction`。数值结果仍称“保守验证的线段点”，不宣称浮点计算获得精确最早交点。

新版配置支持 `clearance_point='segment_entry'`，Q3/Q4 可分别使用独立配置；旧两模式及默认值仍保留。该扩展和恢复修改使用独立 manifest。完整 95 项离线测试已通过并保存 `UNIT_TESTS.txt`；`amendment_replay/AUDIT.json` 独立确认历史 1424 条轨迹、476867 个动作精确一致，失败 0、执行期间源码指纹不变。该回放使用保存的响应，证明这些已保存执行在修订核心上的动作兼容性，不是重新生成的场景性能数据，也不要求新增审计字段与旧 trace 相同。

三方案报告 `reporting/clearance_threeway_report.py` 的修订回放、固定快照、新 segment 两批 acceptance 和 shadow 门禁现均通过。它引用 `eb24b8c` 原 1424 次运行，单列 `57331d2` 新 segment 712 次；总计 2136/2136 全清除，异常、协议失败、超时均为 0，26948 次多边形证书严格复核无违规、无同状态负节省。具体性能和回退案例见 `NCCP_RESULTS.md`。后加第三方案使用已经看过 NCCP 结果的原 256 集，不再声称它对第三方案是新独立留出。原始 scene/row/trace 未覆盖。

## 8. 保持冻结的边界

- Q3 覆盖仍为原点加半径 1130 m 的六点环；Q4 仍为既有 700 m 方格及冻结筛选节点。
- 名义有界测向误差为 ±1.005°；源码常量已有 `1.00500001` 的保守裕量，本轮不改变。
- `no_signal` 语义、硬域更新、MEC 触发、CPU FP64 保证层、粒子数、候选集、发现路径算法、光学兜底排序、随机种子、CUDA kernel 和 diagnostic v1 参数不在 NCCP 落点优化范围内。
- Gap、直径与 Jung 判据只用于解释/独立审计，未接管 MEC 或 planner。shadow 开关已在 42 例、772 个捕获状态中独立验证：动作、完整 trace、策略 RNG 和虚拟时间一致，trace 字段豁免为空。该证据覆盖预定且含极端案例的审计子集，不扩张为所有可能状态的证明。
- 本轮不启动正式测试，不使用官方 App，也不修改 A 题文件。
