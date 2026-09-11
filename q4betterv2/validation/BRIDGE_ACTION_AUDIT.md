# Bridge action oracle 与原子执行审计

审计对象：本轮隔离源目录 `experiments/ctspn_20260912_v1/` 中的 `ctspn.py`、原 `solver.py`、`phase_audit.py`、`directional/diagnostic_recovery.py`，以及交付的 `engine_source.zip/engine.py`。源码证明针对这些冻结版本，不自动扩张至未来改动或未审阅的官方服务端。默认 R12 不作修改。

审阅的 `ctspn.py` SHA-256：`d54673893b3710b52570a4eec08ecd5f8ffd96c1b642504bd7b002e32df3f4d8`。归档与实际执行的源码身份仍以对应 manifest/source archive 为准；本文件不是替代运行记录的哈希清单。

## 1. Oracle 的问题与能力边界

`peek_next_api_action_after_baseline_clear(s,c,z,rho)` 只回答：当前已确定的、具多边形证书的 R12 clear 若在原 MEC 点 z 成功，原 R12 随即提交的第一条 API 请求是什么。返回完整 `path / position / channel`、该请求的审计 stage、请求发出前的决策状态摘要和 Hypotheses RNG 摘要。

它不预测后续测量内容，不向 simulator 发请求，不使用真实源位置、类型、朝向或噪声种子。唯一合成的响应是原 z 已具 hard certificate 的这一次 clear success。成功清除的业务前提还包括目标频道已经确认、尚未清除和会话可用；证书不能证明任意频道存在。

实现创建 `Observed.__new__(Observed)`，深拷贝 `DECISION_KEYS` 和 `remaining_nodes`，新建独立 `trace={}`，使用只具有 `position/channel/virtual_time/stage` 的 `OracleAPI`。它没有 `_engine`、scene、sources、正式日志或正式 API 的引用。`Observed.check_set` 只记录当前 polygon，不带旧 benchmark 中捕获 hidden truth 的 evaluator 闭包。真实源包含性检查保留在独立 evaluator 层。

## 2. 为什么不直接 deepcopy 后重进 run

原 `Solver.run` 的剩余发现节点 `nodes` 在 Python 栈中。诊断循环、定位返回路径、发现频道循环也属于控制状态。只复制 `self.__dict__` 并重新调用 `run()` 会重新 `/enter`、重建 coverage，因而不等价。

当前 R12/P4 的适用证书 clear 有两条实际路径：

| 证书出现位置 | 成功后的原始控制流 |
| --- | --- |
| `Solver.localize` 的 MEC 证书入口 | `clear_certified_polygon` 返回 true，`localize` 立即 return |
| `diagnostic_recovery.recover` 的两个 MEC 证书入口 | recover 返回 true，调用它的 localize 立即 return |

这些成功路径没有尚待执行的测量、光学循环或其他决策更新。`TaggedSolver.localize` 和 diagnostic wrapper 的 `finally` 只恢复审计 stage。因此 oracle 可以从这次 localize 返回后的原始 run 尾部继续。

## 3. 原代码 continuation 的构造

模块读取 `inspect.getsource(Solver.run)` 并解析 AST。它保留原 while 中的全部语句，提取原 `self.localize(...)` 后直到 `continue` 的尾部，加入一次性的 `resume_pending` 分支；只去掉原 run 的初始化计时、`/enter` 和初始 route 构造。`RESUME` 接收已有 nodes 和刚清除的 channel。

尾部保留 public-max 判断、`release_discovery`、R12 实际启用的 `refresh_after_localize`、其他原 route 分支及 continue。下一轮使用完整原 local/explore 比较和原定位/诊断/发现逻辑。没有用“下一 mandatory node”替代请求，也没有只拷贝某个局部选点公式。

`Observed.release_discovery` 保存该次收到的真实 nodes 引用；原 run 每轮选择 localize 前都会调用它。refresh 重新赋值的 nodes 在下一轮被重新捕获。深拷贝时 values 与 nodes 一起复制，保留该快照内部对象关系。

该 AST 构造依赖冻结的 run 结构与上述两个证书调用位置。新增 caller、修改成功返回路径、重写 run 初始化或加入决策性 wrapper 时必须重新审计，不能沿用本证明。

## 4. 第一 API 必须在栈展开之前截获

oracle 用原 `Solver.clear(clone,c,z,certified=True)` 完成原清除 bookkeeping。`OracleAPI` 只对这次清除合成 success，更新其独立位置和时间，不改变 receiver。随后 armed=true，运行 RESUME。

第一次 `OracleAPI.action` 被调用时，在抛出 `FirstAction` **之前**保存请求、stage、`decision(owner)`、逐字段摘要及 RNG。因为异常展开会触发 `measure_discovery` 等 wrapper 的 `finally`，在 catch 以后读取 `measurement_purpose` 或 stage 会得到恢复后的值，不能代表 API 提交前状态。当前实现已在 API 入口内部取快照。

正式 solver 的决策摘要在 peek 前后必须相等；clone 的 arrays、history、Hypotheses 与 Generator 深拷贝，trace 与 API stub 新建。补充动态测试比较原对象完整 pickle，包括 trace 和 API 日志，而不只检查一个 RNG hash。

## 5. clear + bridge 的真实原子次序

采用新 q 后，`BridgeFacade.action` 先向真实 adapter 提交 clear(c,q)。只有 accepted 且 clear_result=success 才直接提交冻结的 a0。两条真实请求之间不调用 R12 顶层 planner。第二条真实响应被缓存。

真实 engine 与真实 adapter 一直保留实际 q→p 位置与真实整数时间；没有把 engine 位置伪装回 z。原调用栈继续时，facade 暂时暴露基线 clear 后的 z、清除前 receiver 和 CT clear 实际完成时间。特别是 receiver 也要暂存：真实 bridge measure 可能已经切频，若提前暴露新 receiver，原 R12 发现频道循环就会改变。

原栈运行到它本来将发出的第一 API 时，必须满足：请求三元组完全相等、完整决策摘要相等、Hypotheses RNG 摘要相等。否则立即 HARD FAIL。匹配后只消费缓存响应一次，清空 pending，恢复实际 bridge 后位置、receiver 和时间，不再提交第二遍请求。原 `Solver.measure/clear` 对响应的正常 bookkeeping 继续执行一次。

日志中的桥接移动要特别处理：原 Solver 在 API 前看到 z，先记了 z→p；facade 在缓存消费时把该日志增量校正为真实 q→p。权威物理 ledger 来自真实 adapter。外层证书事件 `time_after` 是 clear 完成时间，不包含已经预提交但尚未被原栈消费的 bridge。

## 6. 支持动作与特殊分支

| a0 | 冻结语义与处理 |
| --- | --- |
| `/measure(p,k)` | 冻结真实 p 和 k；物理执行后缓存反馈，原 handler 更新观测、polygon、Hypotheses。near 引出的原地 clear 是正常后续动作 |
| `/clear(p,k)` | 冻结真实 p 和 k，包括其可能失败的结果；pending 存在时禁止把这条已冻结 clear 再次 CT 优化 |
| `/exit` | 不构造虚假 destination，不增加第二腿；真实 exit 后原尾部消费同一缓存响应，正常结束 |
| 其他 path | 不改变当前 clear 点，返回原 MEC clear 分支；不发未证明 bridge |

已经作为 bridge 冻结的 certified clear 不再启动新宏动作，保证优化块不重叠。near、uncertified、optical fallback clear 不作为 CT 入口。a0 恰为这些类型时，它只是原 R12 本来要执行的下一条请求，内容仍保持原样。

## 7. 运行证据与停止条件

本文件给出源码层 continuation 与能力边界审计。完整开发/新验证的数量与结论应查 `DEVELOPMENT_GATE.json`、`ADOPTION.json`、`bridge_actions.csv`、`coalescence_audit.csv` 及 trajectories，不能由本文推定128例已经完成。

实际检查包括 oracle on/off 原状态不变、原始 A canonical replay、请求匹配、请求边界完整决策摘要匹配、语义反馈一致、所有非 CT 请求一致及整局整数收益恒等式。任何 request/prestate/RNG mismatch、意外 certified-clear 失败或 bridge rejection 都是实现/证明问题，必须停止；不能以平均收益掩盖。
