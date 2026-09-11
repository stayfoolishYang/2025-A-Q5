# NCCP 审计备注：已修问题、证据版本与完成门禁

本备注对应修订核心 `57331d2c73f5f408014723f70cea9a466c1644de`。原两方案性能数据仍冻结在 `eb24b8c607878ddfacf0f7798807d92409bd3534`；新版本没有覆盖原 scene、row、trace 或原始 acceptance。已生成的 `LOCAL_ACCEPTANCE.json` 状态为 **`LOCAL_R_AND_D_ACCEPT`**；仅认可有效硬域上的可选清除落点及本地证据，默认仍为 `mec_center`。本文通过只读核对更新状态，不新增求解器运行。

## 1. 现实计时污染确定性日志：已解决

首次安全护栏修订曾把 `selection_runtime_s` 写入清除事件。该字段来自现实墙钟，同一 seed、同一虚拟动作的重复执行也会有不同值，导致确定性 trace 比较失败。问题是日志字段污染，不是虚拟移动或得分应当波动。

修正从核心移除了该字段及对应计时，保留确定性的清除证书、提交坐标和验证状态。现实计算费用现在只由独立 `experiments/clearance_snapshot_audit.py` 在固定快照上测量，输出 `nccp_compute_ms`、`segment_compute_ms`，不进入核心动作日志，也不进入虚拟得分。不能通过忽略所有日志差异来掩盖问题。

最新 `J:/2026B_experiments/nccp_20260911/UNIT_TESTS.txt` 记载 **95 tests、7.780 s、OK**。这是已保存测试结果，本备注没有再执行测试。完整历史动作回放也已独立通过：1424 条轨迹、476867 个动作精确一致，失败 0，源码指纹不变；其证据来自 `amendment_replay/AUDIT.json`，不由单元测试结果推断。

## 2. eb24b8c 中已有的两处兼容修正

这两处与后来新增的 wrapper 失败护栏分开记录：

| 原问题 | eb24b8c 已有修正 | 对原冻结配置的范围 |
|---|---|---|
| `diagnostic_recovery.recover` 在 `for` 循环内导入 `mec`；`max_steps=0` 时循环不执行，后面的收尾检查可能出现 `UnboundLocalError` | 把 `mec` 导入放在函数顶部 | 原 diagnostic 配置是 `max_steps=3`；不是改诊断评分、步数或候选集。 |
| `phase_audit` 导入后全局包装 `recover`，普通 `LocalSimulator` 没有 `stage` 属性时也访问该字段 | 用 `hasattr(solver.api,'stage')` 判断；无标签适配器时透明调用原 `recover` | 原实验使用带 `stage` 的 TaggedAdapter；没有修改其阶段划分或算法行为。 |

开发集 100 seeds × Q3/Q4 的 **200 条旧基线**已与 `3c4e844` 原历史动作和物理指标精确比对，差异为 0。这支持冻结配置实际轨迹未变；不扩大为所有可能配置、所有模拟器都已穷尽验证。

## 3. 后续 wrapper 和 segment 扩展的边界

后续修订共享清除入口：无法验证原 MEC 证书时记录 `certificate_failures` 并返回 False，不清除；`localize` 收到 False 后继续既有定位/兜底逻辑。原 MEC 合法、选择器输出非法或数值失败时先严格验证 MEC 回退。选择器的异常捕获范围结束于 `/clear` 发出之前，不吞掉执行网络/协议错误，也不自动重试已发出的清除。

实际提交坐标经过 JSON 往返再做 FP64 与精确有理数平方距离复核，半径仍为 19.999 m，未加 epsilon 放宽。上游空硬域、非有限模型状态等完整性矛盾仍安全终止；护栏不假装修复已经不可信的目标外包。详见 `NCCP_IMPLEMENTATION.md` 第 7 节。

segment 只改变已成立证书的落点，保留原 MEC 与 NCCP。精确线段上的提前清除对固定下一站有两段不劣性质；FP64 插值仍需数值核对。NCCP 当前段更短不保证两段或整局更短；两种策略都不修改发现覆盖骨架和 v1 主评分。

## 4. 不同证据不能混计

| 证据 | 数量与来源 | 能说明什么 |
|---|---|---|
| 原完整场景性能 | 开发 400 + 原留出 1024 = **1424 次**，MEC/NCCP 两方案 | 已完成且通过原配对证据审计；保留全部回退与尾部。 |
| 修订兼容回放 | **1424/1424 条**已保存动作轨迹，**476867 个动作** | 已精确复现旧动作、失败 0；不生成新场景，不算新性能测试，不要求新增审计字段与旧 trace 相同。 |
| segment 完整场景扩展 | 开发 200 + 复用 256 集 512 = **712/712 次** | 全部全清除，异常/协议失败/超时 0；只新增第三方案，旧两方案仍引用原 1424 次。 |
| 固定证书快照 | **8984 个**原 MEC 证书，Q3 4466、Q4 4518 | 相同硬域、当前位置、参考中心及原下一动作下的几何、局部路程、CPU 费用。不是 8984 个场景。 |
| shadow 开关回放 | **42/42 例、772 个状态、14607 个动作** | 开关前后动作、完整 trace、策略 RNG 和虚拟时间一致；全部 trace 字段参与比较，不是新的独立性能评测。 |
| 用户外部几何原型 | 120 合成状态 + 6 退化样例 + 3 非法输入 | 独立几何交叉检查，不是 B 题种子，不并入清除率或场景耗时统计。 |

原 256 集是在 NCCP 结果前冻结的新种子，但 segment 是在看过 NCCP 结果后加入的。因此它对 segment 是**复用的固定评测集**，不是第三方案的新独立留出。全部种子属于本地确定性设计，不作 IID 推断或官方正式成绩。

## 5. 已完成快照的只读复核

`snapshot_audit/SUMMARY.json` 为 `passed=true`。逐项重算 CSV 的分题 n、均值、P50、P95、最大值及回退/两段退化数量，与 SUMMARY 一致；PLAN 和 CSV 的 SHA256 一致，712 条原 MEC trace 输入路径完整，几何核心指纹匹配当前冻结修订。

执行 harness 初版对部分前置数据只检查审计布尔值，不能单靠 `passed` 建立 manifest、任务身份和输入 trace 的完整绑定。本次未发现实际输入错误：计划中 1424 个唯一回放任务、712 条原基线 trace 与预定清单一致。最终三方案报告在只读复核阶段补齐：旧 audit 的 manifest SHA、回放 PLAN 配置和唯一任务/路径、每条回放结果的 trace SHA、全部快照输入，以及 CSV 的频道/ordinal/action_index/原证书关键字段/下一动作绑定。此项属于门禁补强，不冒称发现了本轮结果失真，也不改冻结执行脚本或重跑快照数值。

上述新增绑定已对现有真实文件做只读复核：1424 个回放计划配置/路径无差异；8984 条快照与原证书事件集合完全一致，关键字段和下一动作差异 0。segment 两个 manifest 的父清单 SHA 和核心指纹均匹配当前回放计划。回放最终 AUDIT 及 segment 四份分题 acceptance 也均已通过；完成性由这些最终结果独立确认，不由输入检查替代。

| 项目 | Q4 | Q3 |
|---|---:|---:|
| 快照数 | 4518 | 4466 |
| NCCP 固定下一站两段变长数 | 321 | 472 |
| segment 固定下一站两段变长数 | 0 | 0 |
| NCCP / segment 回退 MEC 数 | 0 / 0 | 0 / 0 |

两段比较采用原审计的 `1e-9 m` 数值门槛，不能把该门槛加到安全清除半径。固定下一站的几何现象不能替代自由重调度后的完整案例结果。精细上界基于给定二进制浮点顶点的精确 MEC 支持圆，平方根是数值显示，并单列旧浮点圆心误差；不是把 `mec()` 的带裕量半径直接当作精确最小半径。

上表列的是变长次数。回退率必须以 `next_action` 非空的快照数为分母，不能直接除以 4518 或 4466；最终三方案报告从原 CSV 重算这个有效分母。

现有原 trace 与 CSV 共同核对的有效分母为 **Q4 4510、Q3 4267**；没有下一动作的证书快照保留在其他几何统计中，但不进入两段回退率分母。

## 6. 用户外部原型的本地复现

`external_geometry/local_reproduction.json` 记录：120/120 状态通过给定浮点输入的精确可行性与同状态不劣检查，120/120 通过带显示误差门槛的精细上界核对；6 个退化样例通过、3 个非法输入拒绝。30 组 SLSQP 数值对照中 29 组有效，最大距离差为 **1.5361933947133366e-11 m**；另 1 组未正常收敛，原失败记录保留，没有计作成功。

构造反例中，NCCP 当前段变短，但接同一个下一站后两段比 MEC 路径多 **1.398192956513 m = 0.279638591303 s**。这是几何反例，不是官方或本地场景运行成绩。原型的精确距离检查只认证给定顶点和输出点，不能证明上游外包必含真值、程序所有异常均恢复，或整局性能一定提升。

## 7. 已完成门禁与验收范围

修订回放 `amendment_replay/AUDIT.json`、固定快照 `snapshot_audit/SUMMARY.json`、segment 开发/复用集 Q3/Q4 四份 `acceptance.json`、shadow `SUMMARY.json` 及其独立审计均已通过。只读核对确认 shadow 的 42 份案例记录全部 `replay_integrity.passed=true`，且 `solver_trace_excluded_fields=[]`；共捕获 772 个状态。该子集包含预定常规和极端案例，状态比例只描述该子集，不作总体频率估计。

最终 `LOCAL_ACCEPTANCE.json` 已统一确认 **95 项测试、2136/2136 全清除、26948 次多边形证书严格复核无违规及无同状态负节省、1424 条旧轨迹兼容回放、42 例 shadow、8984 个快照**；执行核心指纹仍一致。其 11 项引用证据的文件 SHA256 已逐一只读核对。本地研发验收不等于默认采用 NCCP/segment，不承诺整局不劣，也不承诺恢复上游不一致观测；默认 MEC 不变。各方案具体性能留在 `NCCP_RESULTS.md`，本备注不替换该统计口径。

本轮正式测试启动数为 **0**：没有调用正式测试入口、没有操作官方 App。只读报告处理不增加模拟器测试次数。

## 8. 本备注引用的证据 SHA256

以下路径均相对于 `J:/2026B_experiments/nccp_20260911`。这是完成门禁后的证据快照；原冻结证据与新增修订证据分别保留。

| 相对路径 | SHA256 |
|---|---|
| `UNIT_TESTS.txt` | `29fba8585062b5d0a315e866bfdcefd243937f1c9b1fc362bbb67be1b219d4f3` |
| `snapshot_audit/SUMMARY.json` | `0a79f15626e4edd8a8ce65b443b86c5727718e25a1c159a7e3b99cfbe013ca42` |
| `snapshot_audit/PLAN.json` | `5eb50ec6c84e32812b0d9d50c7d411506e4c39fc40bf6ce45fbf5752411b81aa` |
| `snapshot_audit/cases.csv` | `cb40af5874d22514ce0f239b3526d16af4389a0f4f3f69cc0776bd0216977b4c` |
| `external_geometry/local_reproduction.json` | `d6bd392811bcd66b1047437a12d721171f3f33c30d5ac918ed65636bb6e4b0fd` |
| `development100/NCCP_AUDIT.json` | `0e869e6aedc68361aac0de2a68464f034a5c560ed14471c6299c329733aa9490` |
| `holdout256/NCCP_AUDIT.json` | `8ee431ead4f658f07207c3177cc9510cf3844198f2de7c3760c5c370ba07a9ec` |
| `amendment_replay/PLAN.json` | `b97e6c4083796750aa84b0cdad79bfb1be48958e474c11d462ea9b3f4b28a37e` |
| `amendment_replay/AUDIT.json` | `135916c273053378653a8857ba90ce2ebd5fce258a6877f9de28f5dbac23fc32` |
| `amendment_replay/cases.jsonl` | `d0ae7dfcfb64055b7adb31ea22e5c1a4a5fd622c3ec7b1d9904b57b722071157` |
| `segment_extension/development100/q3/acceptance.json` | `e50919f6072777460d23ad6dac5deabba6e96c3b6f97f110000007fae5a02f38` |
| `segment_extension/development100/q4/acceptance.json` | `d2d0bc061e3f22b2036e6531aec74e1b58234d669c73537120811ac4ba55f891` |
| `segment_extension/holdout256/q3/acceptance.json` | `65aa40a6e35de6fee331cc70dc7ad572777a697fbc8346dbc5ba0b3d3d5b1a8d` |
| `segment_extension/holdout256/q4/acceptance.json` | `99b2c10549716e79b137832fe76907f374363186dacda8e633f51f19212706bf` |
| `shadow/SUMMARY.json` | `e47632f6488e1f5404aaba3209fc6e32c043598cb16f4f06873590bfcd968a5f` |
| `shadow/CLEARANCE_SHADOW_AUDIT.json` | `561482dcdecf48e4460d7d25c5afaf574f410b9468649f2907175f87b84a94b4` |
| `LOCAL_ACCEPTANCE.json` | `39e2f5359674166e455053b8a65eb8f39a49de19634f8fe22c67b365f9aeb900` |
