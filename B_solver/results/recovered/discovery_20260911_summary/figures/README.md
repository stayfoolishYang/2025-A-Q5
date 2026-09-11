# Q4 发现调度留出集配对图

来源目录：`J:\2026B_experiments\discovery_20260911\final_report`。读取 `CASES.csv`、`PAIRS.csv`，并要求最终 `AUDIT.json` 通过。

仅展示 holdout128：预先冻结的 128 个相同确定性种子 × 4 方案，共 512 条完整案例、384 组相对基线配对；不混入开发 32 例。原配置、仅刷新节点、仅未知频道优先、组合均保留 MEC 清除站位。

- `01_holdout_total_time`：整局虚拟时间除以真实源数，单位 s/源。
- `02_holdout_last_source_seen`：所有真实源首次 direction/near 返回时间的最大值，单位 s；不除以源数。真实源集合仅用于事后指标计算，不输入策略。

每张图的三列分别将一种候选与同种子基线配对；虚线是相等线，下方更快。均值差为候选减基线，胜/平/负按该图指标及 ±1e-6 的平局阈值计数。全部数据点与尾部保留；不提供 IID 置信区间，不声称普遍整局不劣或官方成绩。PNG 为 220 dpi，SVG 将文字转为路径以便跨机器分享。

生成命令：

```text
python -B B_solver/reporting/plot_discovery.py "J:\2026B_experiments\discovery_20260911\final_report"
```

脚本只读已有结果，不调用 Solver/Engine，不启动任何演练或正式测试。

输入 SHA256：

- `AUDIT.json`：`c13712e7c4fb15af2238b5bb33dd6fb8214b2f57d0df9e761405ebb54b5a0dd1`
- `CASES.csv`：`c0fc35165280b41b65f316c6733d049c55ad9a6a39dd0dba3f647c385fcf41c5`
- `PAIRS.csv`：`5dabb7206f1a40f7a0436b12f6f4862d3e32b3f93efd61c9c445b93b57045379`
