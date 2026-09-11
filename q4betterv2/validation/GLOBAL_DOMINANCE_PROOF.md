# 桥接合流模型的全局非劣性证明

## 1. 被证明的对象

对同一场景、同一原 R12/P4、同一 noise field 和初态，比较原固定 MEC 清除点的 A 与只在已认证 polygon clear 入口启用 C-TSPN 的 CT。定理针对当前冻结离线 engine 的整数微秒虚拟物理时间，并以正常执行未被真实计算预算中断为前提。

不声称 CPU wall-clock 不增加，不声称未知官方服务端内部实现相同，不把 LOCAL_DEV/FRAMEWORK_INTEGRATION 结果称作正式生产验证或 Model Freeze。若把状态定义为连审计日志和时间戳都相等，本任务不可能有正收益；这里采用 `COALESCENCE_PROOF.md` 定义的完整决策状态合流关系。

## 2. 与 engine 完全一致的移动计费

对实际提交并解析的 FP64 坐标 a、b，定义

\[
M(a,b)=\operatorname{go\_round}\!\left(
\frac{10^{12}\operatorname{hypot}(b_x-a_x,b_y-a_y)}{5{,}000{,}000}
\right)\in\mathbb Z_{\ge0}.
\]

浮点运算顺序保持上述真实源码顺序，不任意代数化简。`go_round` 使用 `math.modf` 分离整数/小数部分并执行 ties-away-from-zero。当前 CT 的 move_us 已复制这一规则；不得用 Python round 的 ties-to-even 或不经论证的 `floor(value+0.5)` 替代。

设当前 certified clear 前共同物理位置为 x，原 MEC 点 z，冻结的 baseline 下一请求为 a0。若 a0 是 measure/clear，其实际 destination 为 p，令

\[
J_0=M(x,z)+M(z,p),\qquad J_q=M(x,q)+M(q,p).
\]

若 a0 是 exit，则分别只保留第一项。选择新 q 的必要条件是整数比较 `J_q < J_0`。等于或更大都回退 z，因而每个实际采用事件至少节省1微秒，不由连续优化器的容差定义收益。

两处当前 clear 同为成功，均收取5,000,000μs。相同 bridge 的测量/切频或清除成功/失败服务费相同，因此严格抵消；当前 clear 不改变 receiver。不能仅以距离除以5替代逐动作整数 ledger。

## 3. 可行性与额外距离门禁

当前 source 真位置属于 H=conv(V)。候选必须在 JSON 往返后的解析坐标上通过：

\[
q\in\bigcap_{v\in V}\overline B(v,19.999).
\]

全顶点 FP64 范数与 exact-binary Fraction 平方距离均验证。凸性保证对 H 内任意点距离不超过顶点最大距离；原19.999m操作半径保留对真实20m清除阈值的余量。优化器状态和粒子样本不能放宽该条件。z 始终是保底候选。

整数 J 严格降低本身不逻辑蕴含连续距离降低，因为逐项舍入可能改变亚微秒级排序。实现额外要求

\[
|x-q|+|q-p|\le |x-z|+|z-p|,
\]

exit时同样删除第二项。连续门禁按实际 hypot 计算，solver/adapter的距离统计另作一致性核查。报告中1e-8m之类的距离累计表示容差不是虚拟时间允许退步容差；时间采用零整数微秒正退步容差。

## 4. 单个宏动作引理

假设从共同决策状态开始满足：

1. q 和 z 都通过当前 hard-safe 证书；
2. clear频道与触发时刻不变，成功结果相同；
3. a0 是 baseline 完整原逻辑的第一条实际请求，冻结全部请求语义；
4. CT真实执行 clear(q) 后立即执行a0，原栈只消费该响应一次；
5. bridge后完整决策状态按合流证明恢复一致；
6. J_q≤J_0，且绝对虚拟时间差不参与正常后续策略和反馈。

则从宏动作开始到合流边界，CT耗时比A少

\[
g=J_0-J_q\ge0.
\]

两条轨迹执行相同数量和语义的服务动作，服务费相同，只有上述两腿移动 ledger不同。采用事件g≥1μs；fallback事件g=0。这是engine整数ledger上的等式，不只是连续长度上界。

## 5. 对整局不重叠宏动作归纳

从共同初态开始，将基线动作序列分成普通动作与不重叠的“当前certified clear+下一bridge”块。某条certified clear若已被前块作为bridge冻结，CT禁止再次优化它，保证分块有效。

在第i个块起点，设双方决策状态相同，CT累计时间比A少d_i≥0。普通动作有相同request/feedback/service/movement，故优势不变。CT块由第4节有相同末端决策状态并新增g_i≥0，故

\[
d_{i+1}=d_i+g_i\ge0.
\]

因此在正常共同完成时：

\[
T_A-T_{CT}=\sum_{i\in\mathrm{adopted}}g_i\ge0.
\]

并且两方案以下序列一致：任务频道及动作类型顺序、所有测量位置、语义反馈、未被CT修改的clear请求、failed clear、optical、diagnostic和Hypotheses RNG推进。允许不同的只有被明确记录的CT clear坐标以及物理成本/时间日志。它不是“总体平均可能更好”的经验主张：任何实际case出现正整数微秒退步即为 IMPLEMENTATION_OR_PROOF_BUG / REJECT_PROOF_VIOLATION。

运行审计须核对上式整局精确恒等式，而不只检验总时间非增。event savings总和与整局节省不一致，即使CT更快，也可能有未记录行为分叉。

## 6. 虚拟上限与真实计算上限

engine在完整动作执行后检查 `virtual_us >= 360_000_000_000`，达到阈值即结束。对于基线能够完整执行的宏动作，CT任意前缀成本非负且不超过CT宏总成本，CT宏总成本不超过基线宏总成本；因此CT不会因为更大的累计虚拟时间新增timeout。并不需要额外强制第一腿x→q单独短于x→z。

实现还作保守在线上界检查：当前CT整数时间 + J_q + 当前成功clear的5,000,000μs + bridge最大服务费 < MAX。measure服务费是5,000,000μs及确定的切频费；clear用成功的5,000,000μs上界；exit为0。不满足就fallback z。这一保护不读取未来bridge反馈。

如果基线自身在一个块中已timeout，就不能无条件声称双方之后仍有完全相同的完整动作序列。上面的完整执行/相同序列定理以基线可行完成为前提。CT可能因节省避免某个基线timeout，但这需要另行报告，不能篡改已终止基线的轨迹。

oracle与验证会增加真实计算耗时，adapter有实际1200s/run限制。此成本没有物理非劣定理；所有实际验证必须检查真实运行时间和termination。平均每certified clear<10ms是用户的计算目标，约30ms的pilot不满足该目标。是否实际预算可接受由完整运行数据说明，不能因虚拟成绩有利把未达目标标PASS。

## 7. 与优化最优性、有限验证的区别

连续EXACT邻域优化可用SLSQP、线段可行解及MEC fallback。上述全局非劣定理不需要证明求得全局最优q：任何通过hard-safe、连续距离与整数ledger门禁的可行q都成立。优化失败回z只影响可获收益，不损害非劣性。

定理是当前冻结实现满足所列条件时的结构结论；开发128和新独立128用于查实现、证书、oracle和状态投影错误，不能逻辑替代源码/数学证明。`DEVELOPMENT_GATE.json`与`ADOPTION.json`分别记录这些实际执行是否完成以及是否采用；本文件不预填任何尚未完成的成绩。
