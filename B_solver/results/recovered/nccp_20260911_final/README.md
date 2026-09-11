# NCCP / segment / MEC 最终证据

结论见 [主结果报告](../../../NCCP_RESULTS.md)。此目录保留三方案只读报告、逐例/配对CSV、验收、Shadow汇总与阶段案例说明；原两方案图表另见 ../nccp_20260911_summary，不能把该两方案图表当成三方案图。

- LOCAL_ACCEPTANCE.json：最终本地研发验收；不等于默认采用或官方成绩。
- AUDIT.json：2136次完整运行、逐证书结果、回放/快照/shadow前置门禁。
- THREEWAY_CASES.csv、THREEWAY_PAIRS.csv：全部行、三组同种子配对与五阶段差。
- EVIDENCE_MANIFEST.json、ARTIFACT_MANIFEST.json：报告器原始输入与输出哈希。
- COPY_MANIFEST.json：本目录副本及新增验收证据的哈希。

全部场景、原始row、gzip动作轨迹、运行环境、源码快照、几何反例、完整shadow输入和逐候选指标保存在 J:/2026B_experiments/nccp_20260911，并收入仓库交付包/2026B_NCCP_三方案与Shadow审计_57331d2.zip。包内提供核验脚本与路径映射。256集合对segment是复用评测集，不是新独立留出。

原始1424次来自eb24b8c；新增712次来自57331d2。兼容回放1424条、shadow42条、几何快照8984个分别单列，不扩充场景样本量。全部统计为本地恢复演练引擎结果，正式测试0次。
