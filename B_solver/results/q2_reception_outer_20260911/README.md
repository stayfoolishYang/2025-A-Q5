# Q2 本轮证据包

先读 `../../Q2_OUTER_REFINEMENT_REPORT.md` 和 `acceptance.json`。
主结论：基线复现，接收域安全；J改善约0.71755%，未达到预设1%采用门槛。
不自动替换主配置、不更新正文、不推送、不运行任何官方测试。

文件口径：

* `FROZEN.json`、`plan.json`：运行前已提交的代码与参数，commit=fdbf106。
* `M*_level_*.csv`：原始每层实际评分候选，.01m内层数值间隔；同一站位跨层可重复引用。
* `convergence.csv/refinement.csv`：原始空间细化轨迹，不是最终.001m复核的数值。
* `M*_half_step.csv`：预设.5m错位/边界局部复查。原表赢家仍独立保留。
* `FINAL_REVIEW.json/finalists.csv`：完整精度站位及新的.001m内层审核。
* `candidates.csv`：统一索引，包含主搜索、半步与最终审核；不同精度不得混为同一批分数。
* `inner_scores.json.gz`：2164个完整站位缓存与角度叶区间；另8次细角复核在FINAL_REVIEW。
* `RECEPTION_DISKS.json`：向外取整的圆心有理区间。p的特殊证书还需源码内的首测已接收规则。
* `INDEPENDENT_FINALIST_RECEPTION.json`：80位数交叉检查和最坏有界位置见证，非场景真值。
* `PROTECTED_FILES_SHA256.json`：受保护代码及历史结果前后指纹，Q1函数用AST指纹。
* `TESTS_BEFORE.txt`：25项回归通过；报告生成器另对全部候选、叶区间、J/T及赢家作断言复核。
* 两张PNG：解析圆弧的显示采样与真实已评分候选；没有给未评分区域编造连续热力图。

分数的上下值是原外包后验的数值包络，不是带浮点误差证明的严格区间。
安全性来自独立解析证明与有理区间验证，不能把两种“认证”混用。

复跑需要完整Git仓库和已有NumPy/SciPy环境；压缩包不包含环境二进制或整个Git历史。
在仓库根目录执行：

```powershell
& 'D:\Anaconda3\envs\torchgpu\python.exe' B_solver/tests/test_q2_continuous_search.py
& 'D:\Anaconda3\envs\torchgpu\python.exe' B_solver/q2_continuous_search.py --output 'J:\2026B_experiments\q2_reception_repeat'
```

输出路径必须不存在。没有联网/模拟器调用。不要运行旧questions.py总入口覆盖历史结果。
报告重建使用q2_outer_report.py的--report和--output选项；--report指含run子目录及
START_STATE等辅助文件的实验根目录，原始路径为J:/2026B_experiments/q2_continuous_20260911。
原始运行20.874秒；本轮结束后不安排后台继续优化。
