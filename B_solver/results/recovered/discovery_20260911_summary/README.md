# Q4发现调度证据索引

执行核心1cf0b3d，MEC不变；160新种子×4=640完整Q4本地运行，全部清除；正式测试0。

- RESULTS.md：开发32和留出128分别统计的完整结果，含首次发现配对延迟。
- AUDIT.json：640条独立覆盖/频道/证书/账本复核。
- CASES.csv、PAIRS.csv、FACTORIAL.csv：逐案例、同种子差和2×2效应。
- CASE_AUDIT.json：只读拆解留出42、107、66三例，不计为新运行。
- figures/：留出128例两张配对图，全部点和尾部保留。
- evidence/：原冻结计划、执行边界与102项测试记录；BASELINE_AUDIT仅为旧519例只读分析。

ARTIFACT_MANIFEST来自自动报告生成时，覆盖当时6个报告文件；之后的图表和CASE_AUDIT由SUMMARY_MANIFEST另行覆盖。EVIDENCE_MANIFEST/CASES中J盘绝对路径是原始来源记录，不代表Git摘要包含640条完整轨迹。

完整原始证据在J:/2026B_experiments/discovery_20260911，以及仓库交付包/2026B_Q4发现调度_640次与恢复桥审计_1cf0b3d.zip。摘要、原始数据、代码都来自本地还原核心，不是官方成绩。采用结论见B_solver/Q4_DISCOVERY_RESULTS.md。
