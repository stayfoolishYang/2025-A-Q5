# 基础方法文献核验记录

核验日期：2026-09-11。范围：只读模型与结果，仅写本 research 目录。主文推荐四项，额外两项只在确有对应讨论时引用。不用外部文献为本项目的 51.09 h、耗能、设备选择或工程性能结果背书。

## 双引擎执行与限制

已读取用户指定克隆中的 `downloads/math-modeling-skill-paper/tools/paper_search/SKILL.md`，实际运行 `scripts/hybrid_scholar.py`，每次均为默认 OpenAlex + AnySearch 双引擎；没有使用 `--openalex-only` 或 `--anysearch-only`。

首次系统 Python (`D:/Anaconda3/python.exe`) 在导入阶段因 `tuple[str, str]` 类型注解不兼容而失败；改用 Codex 随附新版 Python 后成功执行两个引擎。无需安装依赖或请求鉴权。OpenAlex 多个查询间歇返回 HTTP 429，另一些查询可正常返回；AnySearch 实际返回记录，但存在作者字段误解析、题名截断、缺少卷期页等问题，必须以出版机构或作者来源核验。

原始输出保留在 `hybrid_*.json` / `hybrid_*.raw.txt` 及 `hybrid_*.stderr.txt`。注意检索器可能把 HTTP 429 警告输出到 stdout，原始 `.json` 因而可能含 JSON 前缀警告；`*.normalized.json` 是不改变字段语义的可解析副本，原始文件未覆盖。`hybrid_run_manifest.json` 汇总执行状态与来源数量。

`cross_validated` 严格保留脚本定义，即 OpenAlex + AnySearch 的匹配标记；出版页人工核验是另一种状态，不冒充双引擎匹配。书目元数据来自出版页、作者机构或 Crossref 时，单独列入 `verification_sources`。

## 主文推荐四项

| 引用键 | 确认的书目信息 | 脚本 sources / cross_validated | 正文可引用范围 |
|---|---|---|---|
| `fritsch1984` | F. N. Fritsch; J. Butland. A Method for Constructing Local Monotone Piecewise Cubic Interpolants. SIAM Journal on Scientific and Statistical Computing, 1984, 5(2):300–304. DOI 10.1137/0905021. | anysearch / false | 分段三次 Hermite 保形插值、内部节点导数的单调性约束与加权调和平均构造。 |
| `eymard2000` | Robert Eymard; Thierry Gallouët; Raphaèle Herbin. Finite Volume Methods. Handbook of Numerical Analysis, 7, 2000:713–1018. DOI 10.1016/S1570-8659(00)07005-8. | openalex + anysearch / true | 逐控制体积分与局部守恒、共享界面通量收支、有限体积用于扩散/抛物问题的通用依据。 |
| `donea2004` | Jean Donea; Antonio Huerta; Jean-Philippe Ponthot; Antonio Rodríguez-Ferran. Arbitrary Lagrangian–Eulerian Methods. Encyclopedia of Computational Mechanics, Vol. 1, Ch. 14, 2004:413–437. DOI 10.1002/0470091355.ecm009. | 未进入已保存候选清单 / false | 材料坐标、空间坐标和网格坐标之间的区别；材料速度与网格速度之差形成相对对流；ALE 守恒方程的通用描述。 |
| `mayor2004` | L. Mayor; A. M. Sereno. Modelling Shrinkage during Convective Drying of Food Materials: A Review. Journal of Food Engineering, 2004, 61(3):373–386. DOI 10.1016/S0260-8774(03)00144-4. | openalex / false | 脱水引起体积变化、收缩可影响水分/温度分布预测、经验收缩模型与结构机理模型的区别及材料适用范围。 |

### fritsch1984 核验细节

- SIAM DOI/出版页已直接打开，题名、两位作者、纸刊年 1984、原期刊全名、5(2)、300–304 均可见：[SIAM 出版页](https://epubs.siam.org/doi/10.1137/0905021)。不要把数字化上网日期 2006 当作原出版年。
- [SciPy 官方 PchipInterpolator 文档](https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.PchipInterpolator.html)已直接打开。文档 Notes/References 明确引用 Fritsch–Butland (1984) 作为内部斜率构造依据，端点用单侧方案并另引 Moler (2004)。因此调用 SciPy PchipInterpolator 时优先引用 `fritsch1984`。
- Fritsch–Carlson (1980), Monotone Piecewise Cubic Interpolation, SIAM Journal on Numerical Analysis 17(2):238–246, DOI 10.1137/0717021 也已在 [SIAM 出版页](https://epubs.siam.org/doi/abs/10.1137/0717021?download=true&journalCode=sjnaam)核实。它是相关奠基论文，不能把 SciPy 的 Fritsch–Butland 内部导数公式直接称为 Fritsch–Carlson 算法。
- 不能据此称任意噪声数据会被自动单调化，也不能保证插值区间外的外推物理合理；PCHIP 只保留输入数据本身的局部形状约束。

### eymard2000 核验细节

- [Elsevier 官方章节页](https://www.sciencedirect.com/science/chapter/handbook/abs/pii/S1570865900070058)的搜索索引返回完整题名、卷年、713–1018、DOI 及 Publisher Summary。直接打开该页返回 HTTP 403；此限制明确保留。
- [作者公开更新稿](https://raphaeleh.github.io/PUBLI/bookevol.pdf)已直接打开，首页核实三位作者、原书名、编辑名、卷号，并写有原版页码 713–1020。PDF 是 2019 更新稿，不伪称为原版全文。第 1 章开头明确说明控制体局部平衡、相邻控制体之间数值通量守恒；目录含 Parabolic equations 与 nonlinear case。
- 页码存在来源差异：当前所引 DOI 的 Elsevier 页面与双引擎 OpenAlex 记录为 713–1018；作者更新稿回溯书目为 713–1020。BibTeX 采用 DOI 出版页的 713–1018，差异在这里保留。
- Crossref 本次查询此 DOI 返回 429，未作为确认依据。
- 仅为离散框架提供来源。项目的球对称几何因子、边界传质、时间积分、非线性迭代容差及收敛误差仍须来自本项目推导和验证，不能直接宣称已由该文献证明。

### donea2004 核验细节

- [Wiley 出版页](https://onlinelibrary.wiley.com/doi/abs/10.1002/0470091355.ecm009)已直接打开，核实四位作者、题名、2004、DOI 和 ALE 方法综述范围。Crossref 记录另确认书名、作者及 2004 出版日期。
- [作者团队 LaCàN 书目页](https://www.lacan.upc.edu/abstract/?id=429)的搜索索引给出作者、Vol. 1、Ch. 14、413–437、编辑与完整 BibTeX；直接打开超时。
- [作者团队公开章节](https://www.lacan.upc.edu/?serve_pdf=2004-TECM-DHPR-blanc.pdf)的搜索索引显示章节首页、413–437、章节目录：Descriptions of Motion / The Fundamental ALE Equation / ALE Form of Conservation Equations。
- 只能支持运动描述和变换形式；不能用 ALE 名称证明本项目选取的收缩闭合或材料速度场已被药材试验证实。若模型并不求解完整任意网格运动，应准确表述为材料坐标映射/随体描述，避免过度命名。

### mayor2004 核验细节

- [Elsevier 出版页](https://www.sciencedirect.com/science/article/pii/S0260877403001444)的搜索索引给出完整题名、两位作者、February 2004、61(3):373–386、DOI、摘要与结论片段。直接打开 DOI 与出版社页面多次失败/403，未声称读到全文。
- Crossref DOI 元数据请求成功，`published-print` 为 2004-02，作者 L. Mayor / A. M. Sereno，卷 61、期 3、页 373–386，与出版社索引一致。原始记录保存在 `crossref_metadata.json`。
- OpenAlex 返回 2003，而 AnySearch 的两个标题截断/异拼记录给 2004，脚本未合并。必须保留 `cross_validated=false`，书目采用纸刊年 2004。
- 仅能说明收缩通常不能忽略、经验关系需要数据、孔隙结构会影响模型。不能证明本药材的各向同性、球形保持、特定 shrinkage(U) 函数、扩散参数或“收缩必定使干燥更快”。

## 可选补充两项

1. `rahman2001`：M. Shafiur Rahman. Toward Prediction of Porosity in Foods during Drying: A Brief Review. Drying Technology, 2001, 19(1):1–13. DOI 10.1081/DRT-100001349。双引擎 `sources=[openalex, anysearch]`, `cross_validated=true`。可引“孔隙率和结构演化不能只凭一个普适机制或未经校准的经验函数确定”；不能替本项目确定孔隙率或收缩参数。[T&F 期目录](https://www.tandfonline.com/toc/ldrt20/19/1)搜索索引核实卷年作者页；直接打开返回403。[作者机构记录](https://squ.elsevierpure.com/en/publications/toward-prediction-of-porosity-in-foods-during-drying-a-brief-revi/)已直接打开并核实完整书目和摘要；Crossref 成功。
2. `eymard2002`：Robert Eymard; Thierry Gallouët; Raphaèle Herbin; Anthony Michel. Convergence of a Finite Volume Scheme for Nonlinear Degenerate Parabolic Equations. Numerische Mathematik, 2002, 92(1):41–82. DOI 10.1007/s002110100342。双引擎 `sources=[anysearch]`, `cross_validated=false`。[Springer 出版页](https://link.springer.com/article/10.1007/s002110100342)已直接打开，Crossref 亦核实卷期页年。可说明特定非线性退化抛物模型存在有限体积收敛分析；不应套用其定理证明本项目的移动边界、边界条件或耦合系统。Springer/Crossref 显示作者 Gallouït 的元数据拼写错误，按作者 [Herbin 公开书目](https://www.i2m.univ-amu.fr/perso/raphaele.herbin/publications.html)与作者本人著作使用 Gallouët。

## 引用落点建议

- PCHIP 定义或数据预处理方法首次出现后引用 `fritsch1984`。
- 控制体水分收支离散介绍后引用 `eymard2000`。
- 介绍空间/材料/网格速度区别和相对对流时引用 `donea2004`。
- 问题背景、收缩建模选择或模型局限中引用 `mayor2004`。
- 不在结果数值后堆积这四篇引文。不要声称双引擎都收录全部四项。
