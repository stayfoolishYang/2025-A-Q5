# Stage 06 Implementation

## 1. Implementation Scope

实施基线：A26-04-v2。已实现可移植Python求解包、单元/数值开发测试、运行与恢复、重建事件及条件导出。用户最新明确“交给服务器跑”，因此停止新增本地数值执行；交付源码和命令，由用户在服务器运行。历史本地试跑保留，不能改称服务器证据。

### Execution / Reasoning Metadata

- Operating Mode: PERFORMANCE；Budget Mode: PERFORMANCE。
- Primary Model: 当前父任务后端身份未独立核验；不宣称已切换父任务模型。
- Reasoning Level: 核心子任务显式请求gpt-6-astra/ultra，工具接受；实际后端身份未独立暴露。
- Reviewer Used: YES；Reviewer Role: 有界数值核心交叉审查及只读集成审查。
- Review Status: 已接收发现并修复；数值测试与独立Stage07分开。
- Task Type: COMPLEX_ENGINEERING；Task Complexity: HIGH；Decision Risk: HIGH。
- Routing Source: 本轮用户授权、现行AGENTS首部偏好及实际协作工具；未修改兼容框架、未做Best-of-N。
- 输入/输出工作代理继承父任务设置；未把未核实设置写为Sol/High。额外第三worker因线程上限未创建，后续复用现有worker独占文件。

## 2. Entry-Gate and Approved Routes

用户明确确认“以Stage05修订后的A26-04-v2作为Stage06实施基线”。Stage04 SHA-256为`29ea5f37f9e50dae9f5d7f7515276394d2215fdc8f0d0b79c6d0c91eccd437d4`；权威规格未改。Gate05为CONDITIONAL_PASS；人工确认独立记录在Stage05交接末尾。B_EMPIRICAL_RADIAL兼基准及主线；C_AXISYMMETRIC_REFERENCE保留；P为KEEP_IN_RESERVE，H不启用。

## 3. Code Architecture

`src/drying`包含config、inputs、physics、spatial、manufactured、integrator、trajectory、diagnostics、reconstruction、events、refinement、export、execution、resources、preflight、reporting、cli。`python -m drying`为统一入口。父代理独占集成、时间推进和官方状态；工作代理分别独占空间核心/制造解/加严模块，以及输入/输出/预检模块，详见协调合同。无额外调度平台。

## 4. Math-to-Code Traceability

| A26-04-v2对象 | 权威实现 | 实施要点 |
|---|---|---|
| 附录2/3/4物性及导数 | physics.properties | T使用K；a=rho cp；所有系数和导数单入口 |
| B材料径向方程 | spatial.DryingSystem | a(C)Tdot与Cdot，径向R^-2，Rdot不重复加平流 |
| C轴向项及端面 | spatial | 实际z坐标，轴向不乘R^-2，半域体积镜像 |
| 单元平均与共享通量 | Grid、spatial | 圆柱体积权重、调和系数、邻面相消 |
| Robin半单元串联阻力 | physics.surface | 求解边界与真实表面重建共用 |
| 变步BDF2/BE及Newton | integrator | 完整BE主状态；辅助两半步仅估误差；精确Jacobian与缩放 |
| O1/O2与全域G | reconstruction | 真实轴心/中截面、角点，禁止负值夹紧和域外外推 |
| 严格事件 | events、refinement | 区间交、真实检查点重积分、三级差证据及0.36s报告格点 |
| 水/有效热余额 | diagnostics | 接受段温度割线导数和独立求积，不用RHS制造恒零 |
| 模板合同 | export | Q23同源、Q4固定距离/域外空白/独立表面、临时写后回读 |

状态采用`(nr,nz,2)`按C序展平、末轴[T,C]，是规格列举顺序的置换，不改变数学模型。浮点端点修复在Newton试探前调整实际步长到目标端点，避免ULP尾巴误报STEP_UNDERFLOW；没有只修改时间标签。

## 5. Data and Schema Contract

七个便携原件共620233字节，原题PDF、附件1/2和四个模板按源哈希核对；清单仅用相对路径。预检会拒绝哈希、单位、模式、时间节点或半径约束不一致。历史Stage05脚本原字节在临时副本中运行，并保留原文件名别名，确保48项断言完整重跑；历史脚本及证据未覆盖。

## 6. Configuration System

RunConfig为严格冻结数据类，未知字段拒绝；配置控制路线、分问、网格、输入情景、半径插值及尾部、时间/Newton容差、有限物理/墙钟/步数/内存/输出预算、检查点频率和证据用途。正式移动几何使用question=4；TEST_CASE只在TEST_ONLY配置中允许。JSON无需修改源码即可切换。服务器first_round计划及全部引用先验证。

## 7. Shared Mathematical Components

所有路线共用输入、物性、面通量、误差标度、事件与输出规则。a(C)只乘Tdot，不错误地离散d(aT)/dt。固定/移动都使用归一化干质量权重；不从经验rho推断真实绝对Md。表面查询和最后控制体边界使用同一Robin函数。输出重建非守恒，不代替求解状态和余额。

## 8. Route B Implementation

径向单元平均FVM，结构化交错[T,C]带状系统；Q1、Q23固定与Q4移动均有真实开发轨迹。Q2原始初值独立于Q1，Q3读取同一Q23轨迹。主线不是将另一题结果复制进来。

## 9. Route P Implementation

KEEP_IN_RESERVE。没有启用P，也没有伪造第三个求解器。严格湿密度路线不相容问题保持上游结论。

## 10. Route C Implementation

真正二维径向/轴向算子、侧面和端面通量、二维稀疏Jacobian。固定/移动C0退化测试以及C1轴向非均匀与端面交换测试已执行；另有三个60s短时开发运行。完整Q23/Q4 C1配置可交服务器运行。短时成功不构成一维近似已验证。

## 11. Other Route Implementation

NONE

## 12. Solver / Numerical Backend

float64；自定义变步BDF2/BE；稀疏解析Jacobian；B使用solve_banded，C使用splu。未采用solve_ivp BDF替代。执行环境记录Python3.11.9、NumPy2.4.4、SciPy1.17.1、openpyxl3.1.5及实际BLAS信息；服务器重新记录自己的环境。不要求GPU。

## 13. Leakage and Information-Timing Guards

本题采用已批准的区间内离线观测重建；没有使用未定义未来半径。14400s的观测点值、左右极限和BE重启明确处理。默认Q4不超72h；HOLD仅用于另标识的明确有限外延配置。拟合输入不称独立物理验证。

## 14. Uncertainty and Scenario Implementation

S0/S1、S0平台窗口2.5/3/3.5h、线性/PCHIP和显式HOLD均为实际开关。未自动跑完整敏感性矩阵。未杜撰测量误差分布、独立内部场观测或统计置信区间。

## 15. Fixed-Policy and Recourse Implementation

本题为给定环境前向PDE，调度/追索合同不适用。严格事件和物理上限是结果语义，不被当作控制优化变量。

## 16. Multi-Objective Implementation

不适用。没有引入任意权重多目标；t*是给定工况下全域严格含水率首次进入时刻，临界估计、误差余量、报告时间分别保存。

## 17. Diagnostics and Runtime Checks

接受状态正值/温度/有限系数；输入节点与BE比例；Newton/线性残差、拒步、余额；流式轨迹哈希及原子检查点；恢复时配置/输入/源码身份核对；后处理核对数值核心和系统构造，另记后处理源码版本。中断恢复保留旧索引、不可变块和日志。每次恢复保留独立环境记录。预算退出为PARTIAL/2，数值失败为1。误差不完整时导出拒绝。

## 18. Test Suite and Smoke-Test Results

已完成且有记录的父任务批次：核心76项通过（79.31s）；打包/恢复/预检9项通过（12.03s）；端点修复后的时间/PDE/执行回归24项通过（65.66s）。批次有重叠，不相加冒充独立测试总数。工作代理另报告事件/误差模块13项通过（40.45s），包括真实短系统三级重积分和小型MMS后缀余额；它不代表真实问题严格证书已生成。原Stage05的48项孤立断言本轮实际重跑通过。

保留探索期失败：粗容差单一末时刻误差因BE启动/BDF积累抵消不单调；以固定足够小启动步隔离时间误差，并保留原始观测。刚性衰减默认启动在12次重试内未通过，保留预期失败测试，不放宽控制器。事件细化发现浮点微尾步，按实际Newton端点修复并回归。数值和集成审查发现的历史浅拷贝、差分消减、失败Newton计时、检查点落盘窗口、输出分问与环境覆盖问题已修复。

用户最新停止指示后未启动新的数值运行/测试；最后检查仅做文本/JSON/AST/哈希和Git发布核对。未执行服务器任务、Stage07或模型冻结。

## 19. Planned Experiment Packages

历史本地EXP001–008保留原manifest/配置/轨迹；使用LOCAL_DEV和开发用途。EXP002/003完整覆盖Q1的1800s；EXP004 Q23覆盖72826.17820743435s；EXP005 Q4覆盖92111.16816711426s，后两者各约240s墙钟预算耗尽，全域扫描均NO_EVENT。EXP006–008为固定/移动C0、C1各60s。紧凑汇总见`evidence/stage06_development_summary.json`。

服务器预留EXP100 smoke、EXP101 Q1、EXP102 Q23、EXP103 Q4、EXP104 Q1nr40、EXP105 Q1nr80、EXP106/107/108短C0/C1、EXP109/110长C1Q23/Q4；均为计划，未提交、未列为已完成。新配置必须使用新run_id。自动首轮只含101、104、102、103。

## 20. Server Execution Guide

完整可复制命令见项目根`README_RUN.md`。在服务器Python3.11虚拟环境安装requirements及editable包，执行`python -u -m drying pipeline --plan configs/server_first_round.json`。先前置检查，再顺序计算；不能覆盖已有运行目录。恢复用原run下config.json和`--resume`。默认CPU，2GiB预算，各任务有限上限；不虚构远程连接/队列提交。

## 21. Validation Return Package

见`06_validation_return_requirements.md`。minimum包含各运行的身份、配置、实际环境、指标、余额、事件与误差、候选和回读；full增加接受轨迹、合法检查点、逐步日志和源码快照。失败、未达标及预算耗尽也必须回传。

## 22. Known Implementation Limitations

Q1早期真实表面在20/40网格比较中dC最大约0.09001846kg/kg（t=.001s）；即使只查t≥1s，仍约0.08804140，未达到开发验收。温度样本最大差约0.00339653K；这是采样比较，不是全域误差界。因此没有候选result1。Q23/Q4尚无临界/严格报告时刻，全部严格误差类别未齐，因此没有候选result2–4。

原始物理闭合和缺少独立实测场的局限不因测试通过而消失。全程C1及情景比较留服务器；细化模块尚无真实问题DRYING_COMPLETE证书。局部事件步长不冒充全程dense-output对照；新轨迹余额必须独立重算。

旧本地首轮轨迹使用端点修复前源码版本；完整历史快照保留。当前版本会拒绝直接续接或重新解释不同数值核心的旧轨迹；需用原快照复现或新run_id重跑。本轮没有为消除此版本差异再次在本地求解。

## 23. Implementation Issues

BLOCKING实现缺陷：当前未发现。数值误差/最终输出状态：UNRESOLVED，留服务器实算后处理，不能称完整模型验证。最后新增CLI命令绑定已静态核对，用户停止本地执行后没有追加端到端数值试跑。

## 24. Handoff to Server Execution

服务器所需源码、测试、配置、原件、规格与轻量证据上传到指定仓库独立`CUMCM2026_A_DRYING/`，保持既有目录不变。当前停止在Stage06人工审核点；recommended_next_stage为SERVER_EXECUTION，但上传不等于已运行。Stage07/08维持NOT_RUN、current_best_verified=null、model_frozen=false、PERFORMANCE。

GATE 06: PASS

STATUS: READY_FOR_STAGE06_HUMAN_REVIEW
