# Q4 21＋R12＋F＋CT 模拟数据与复现说明

## 版本与用途

本包汇总最终几何修订版的1000场本地模拟结果、完整场景与动作、历史A/B对照，以及可移植源码和本地引擎。用于论文统计、案例路径图、CT机制分析和离线复现。没有纳入官方演练或正式测试；本次打包没有运行任何测试。

最终模型为 B / 21＋R12＋F＋CT（geometry revision）。21点连续覆盖＋R12调度/诊断＋F失败计数修复＋CT状态桥接。不要将历史25点7228633标为本包最终模型。配置中的 certified25 是旧枚举名，入口实际加载 points21.json 中21个节点。

## 包内导航

| 位置 | 内容 | 如何使用 |
|---|---|---|
| support/expanded_regression/ | 最终1000场的 cases.csv、pairs.csv、summary.json、verification.json | 主结果表、分布图、长尾统计、与历史B的回归比较 |
| archives/q4_revised_1000_full_evidence.zip | 最终1000场完整场景、逐动作记录、CT事件、冻结代码与驱动 | 解压到本包根目录 full_run/，用于路径、阶段耗时、CT事件可视化 |
| support/evidence/q4_local.zip | 历史同1000场景的A/B配对结果，共2000条统计记录 | 作为历史算法对照；含CT事件，但只有少量代表完整轨迹 |
| support/code/q4betterv3/ | 可移植最终策略源码及配置、21点坐标 | run.py 为离线单场入口；保留整个目录 |
| support/runtime/q4/ | 本地模拟引擎与审核依赖 | 与 code/ 保持当前相对位置 |
| support/coverage21/ | 21点连续覆盖证书与验证程序 | 证明、节点图及数值边界说明 |
| MANIFEST_SHA256.json | 原始来源、本包相对路径、字节数与SHA256 | 防止取错文件或传输损坏 |

完整轨迹包解压到 full_run 后，full_run 下应直接出现 driver.py、verify_and_package.py、frozen/、results/，不要多套一层同名目录。

- full_run/results/scenes/：真实源布局。
- full_run/results/core/traces/：1000场完整动作与响应。
- full_run/results/core/rows/：逐场摘要。
- full_run/results/events/：CT事件。
- full_run/frozen/：对应本次1000场实际冻结实现；严格回放优先用它。

## 已有结果与统计口径

最终修订版：1000/1000场全清并通过审计；平均520.3934166104秒/源，P95为678.44208101，P99为736.899291087，最大782.0298454。191次清除失败发生于17场，但最终全部成功；兜底18次。完整动作共286341条。

分层分析：931场混合源为主分析，均值516.8436113587秒/源；69场全定向为压力分析，均值568.2900642813秒/源。不要将压力组当作随机自然场景比例。

历史A/B在同1000场景上的均值分别为549.4548274861和520.3841455822秒/源。几何修订版对历史B均值差仅+0.0092710282秒/源。历史A/B改进与几何修订回归是两种不同对照，必须分开命名。

每场指标 t_i=T_i/N_i；报告的平均值为 mean(t_i)，不是 sum(T_i)/sum(N_i)。后者可以另算，但要单独标注。分位数使用线性插值。若画归一化方差，使用 z_i=t_i/mean(t)，再算 var(z,ddof=1)，并明确按哪一组均值归一化。不能直接把 var(T/N) 当作无量纲方差。

这两套1000场是同批场景；2000次A/B运行不等于2000个独立场景，最终重放也不是新增独立1000场。所有数据均为本地模拟，不能写成官方正式测试结果。

## 作图建议

1. 主性能图：读取 cases.csv，按混合/全定向分组画经验分布、箱线图、P95/P99；兼顾中心与尾部。
2. 历史改进图：解压 q4_local.zip，用 pairs.csv 按场景配对比较A/B；不要把两组独立排序后再配对。
3. 几何修订稳定性：用 expanded_regression/pairs.csv 展示历史B与最终修订版差值，作为回归审计。
4. 路径案例：按主指标选择中位、P95附近、最慢案例，关联同编号 scenes、traces 和 events；绘制圆域、源、检测点、移动路径与清除事件。
5. 阶段耗时：使用动作时间增量与日志阶段标签，分别统计移动、检测、切频和清除；避免把累计虚拟时间相加或与实际计算耗时混用。
6. CT机制：将事件与动作对应，展示采用/拒绝、移动节省与桥接状态；不能将局部距离节省写成每局必然更快。

具体CSV字段以文件表头为准；case/场景编号与manifest是关联依据，不按文件遍历顺序拼接。

## 离线复现入口

在整个包的工作副本中操作，保留原始包。

单场：在本包根目录运行

```text
python -B support/code/q4betterv3/run.py --scene <场景JSON> --output <不存在的新输出目录>
```

此入口仅使用本地引擎，检查源码哈希并拒绝覆盖已有输出。依赖以 requirements.txt 为准。不要启动 official.py 或驻留程序来生成论文的本地结果。

完整1000场数据统计复算：解压 archives/q4_revised_1000_full_evidence.zip 到 full_run，在 full_run 中执行：

```text
python driver.py --summarize
```

独立动作账本核验可执行 python verify_and_package.py，但会写输出，因此只在工作副本使用。全量重跑需先备份并移走副本 full_run/results，再按该包README执行 driver.py --prepare 和 driver.py --workers 6；support/evidence/q4_local.zip 已位于所需相对位置。不需要为作图重新运行1000场。

## 边界

本包默认不包含未采用的NCCP、跳过已发现频道、四项长尾试验或新rollout策略。CT不替代硬可行域或MEC证书。历史轨迹缺失部分不能用修订版轨迹冒充。若论文比较版本，须同时注明场景集、策略、几何实现与评价指标。
