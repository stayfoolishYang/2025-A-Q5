# 修订 Q4 全量历史场景回放

本实验固定使用修订后的 21 点覆盖、R12 诊断、F 失败计数修正和 CT 桥，读取历史配对集中的全部 1000 个场景，每场仅运行一次。它检验修订代码在既有场景上的回归表现，属于修订版新回放，既不是新的独立样本，也不是遗失的历史 A/B 轨迹原件。实验只调用本地引擎。

运行前已将代码、引擎、21 点坐标和配置复制至 frozen，并在 results/manifest.json 冻结哈希。计算使用 6 个进程，每进程限制 BLAS 为单线程。driver.py 逐场核查源文件和场景哈希，保留全部成功或失败记录。算法执行与逐动作审核来自冻结实现；verify_and_package.py 再独立复算整数微秒账本、清除次数和失败阶段。

results/core/traces 保存 1000 份完整动作与响应；results/events 保存 CT 事件；results/core/rows 保存逐场结果；results/scenes 保存场景。统计中的样本单位是一场，主要指标是每场总虚拟时间除以该场真实源数，再在场间取算术均值；P95 与 P99 使用线性插值分位数。墙钟时间是并行整批运行耗时，不能与虚拟时间或各进程耗时之和混用。

支撑材料中的 expanded_regression 目录提供统计、逐场比较、验证摘要及冻结源码。完整轨迹另置 q4_revised_1000_full_evidence.zip，摘要文件记录其字节数和 SHA-256。historical_search.json 记录原历史轨迹的有限检索范围；发现的其他版本和 519 场轨迹不能替代目标 1000 场旧 A/B 原件。

在完整工作目录中，可执行 `python driver.py --summarize` 复算已保存逐场记录的统计，执行 `python verify_and_package.py` 独立核对动作账本并重新打包。若需要重新运行，先另存原 results 目录；保证相邻 support/evidence/q4_local.zip 可用，然后依次执行 `python driver.py --prepare` 和 `python driver.py --workers 6`。不得覆盖或把重跑结果写回历史证据。

完整证据包解压后的目录记为 R，R 下直接应有 driver.py、verify_and_package.py、frozen 和 results。若只复算统计，在 R 运行 `python driver.py --summarize`；独立核验在 R 运行 `python verify_and_package.py`。核验脚本将紧凑摘要输出到 R 的上一级目录下 support/expanded_regression。若要从头重跑，在 R 的上一级放置 support/evidence/q4_local.zip（来自主支撑包），将 R/results 改名备份后再执行 prepare 与运行命令。frozen 中的源码、driver.py 和已保存结果哈希保持原样。主支撑包 expanded_regression 根目录另列出的两个脚本供论文附录引用；直接执行前应按上述完整包 R 目录结构装配。
