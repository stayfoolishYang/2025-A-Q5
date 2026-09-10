# 2026 国赛 A 题《药材的烘干问题》项目总结与服务器交接

文档版本：A26-SUMMARY-v2 ｜ 更新日期：2026-09-11

数学基线：**A26-04-v2** ｜ GPU 全量实现：**A26-06-FULL-v1 / 0.6.2**

历史 GPU 基线提交：[8b309d6c243f8e92d7ec612e95c601cd8dba9302](https://github.com/zhuoshou111/2025-A-Q5/commit/8b309d6c243f8e92d7ec612e95c601cd8dba9302)；当前全量入口见本版本源码及 PACKAGE_MANIFEST.json。

仓库目录：[2025-A-Q5 / CUMCM2026_A_DRYING](https://github.com/zhuoshou111/2025-A-Q5/tree/main/CUMCM2026_A_DRYING)。详细公式以 Stage04 为准，阶段状态以 `workspace/modeling_state.json` 为准；本轮增加服务器全量调度与必要的证据链工程修复，未改变数学模型或推进 Stage07/08。

**全量一条命令：** `python -u -m drying full-run --plan configs/server_full.json --out results/full/A26_FULL_001`。它自动衔接 CUDA 预检/测试、基础与二维参考、三级误差、8 个单因素变体、严格事件证据、条件导出和打包；默认预期67个去重主求解配置、14组比较。数量来自静态设计，服务器测试尚未执行。恢复在相同命令末尾加 `--resume`；每次调用计算预算48h、打包最多另300s，可能保留 PARTIAL/UNRESOLVED。详见 [全量运行指南](FULL_RUN.md)。以下首轮说明继续适用于旧 `pipeline`。

## 1. 当前已经做到哪里

项目已完成问题分析、模型路线筛选、数学规格、求解前 QA，以及 Stage06 代码实现和 GPU 改造。代码、真实输入、结果模板、测试、配置和运行说明已上传到上述仓库目录。

**当前交付的是需要 NVIDIA GPU 的服务器求解包。GPU 版还没有数值运行结果，最终烘干时间和可提交的 result1–result4 尚未取得。** 按用户要求，本地已停止新增数值求解和测试，实际计算交由用户的服务器执行。上传仓库不等于提交了服务器任务。

| 项目 | 当前状态 | 含义 |
| --- | --- | --- |
| Stage01–Stage05 | 各 Gate 为 `CONDITIONAL_PASS` | 当前阶段产物已形成，保留物理闭合、观测覆盖等条件与限制 |
| Stage06 — Code Engineer | `CONDITIONAL_PASS` | GPU 实现与静态审查完成，待服务器 GPU 预检、测试和短时运行验收 |
| 下一计算环节 | `SERVER_EXECUTION` | 用户在服务器执行，不新增第九个建模阶段 |
| Stage07 — Validation | `NOT_RUN` | 尚未开展独立结果验证 |
| Stage08 — Model Improvement | `NOT_RUN` | 尚未基于服务器结果进入模型改进 |
| 运行模式 | `PERFORMANCE` | 未退回 ECONOMY |
| 最佳已验证模型 / 冻结 | `null` / `false` | 尚未认定最终优胜模型，也未冻结 |

## 2. 研究对象、四问关系与真实输入

研究对象近似圆柱体，长度 0.25 m、初始半径 0.02 m，初温 28 ℃，初始干基含水率 2.55 kg/kg。内部求解温度使用 K，时间使用 s，长度使用 m，输出再转换到题目单位。

| 子问题 | 计算任务 | 与其他问题的关系 |
| --- | --- | --- |
| Q1 | 预热阶段 0–1800 s 的温度、含水率场 | 使用该问物性，检查初始表面层与指定点输出 |
| Q2 | 固定半径下整个烘干过程 | 从题给原始初值开始，不拼接 Q1 末态 |
| Q3 | 找到全域含水率满足严格条件的时刻 | 与 Q2 共用 `question=23` 的同一条正式轨迹 |
| Q4 | 在观测半径变化下计算场与达标时间 | 使用移动材料坐标、真实半径数据及移动域输出规则 |

输入已经便携化到 `data/raw/`，不依赖原始 Windows 桌面路径。

| 原始材料 | 已核验的数据范围 | 使用方式 |
| --- | --- | --- |
| A题.pdf | 4 页；用户提供版本 | 题目、公式、单位和输出要求的原始依据 |
| 附件1 | 241 个时刻，0–14400 s，每 60 s | 烘房温度及外部水分变量；观测内分段线性重建 |
| 附件2 | 145 个时刻，0–259200 s，每 1800 s | 半径 2.000–1.198 cm；主方案分段线性重建 |
| result1–result4 | 四个原始模板 | 保持工作表、列结构及显示要求，合格后填入候选数据 |

7 个原件的哈希已核对。附件1的水分列是题面给定的 kg/kg 变量，不能当作相对湿度百分数。题目版本在本项目内按所提供原件使用，未做外网版本鉴定。

4 h 后环境缺少实测：主情景 S0 保持 3–4 h 共 61 点的样本均值；S1 保持末次观测值。它们属于明确的条件假设。Q4 默认不越过 72 h 的半径观测终点，只有显式选择 `R_EXT_HOLD` 并设置有限上限才允许末值延拓。给定数据的离线区间重建可以使用相邻两侧观测；若将来改为在线预测，必须另外限制可用数据的时间前缀。

## 3. 当前模型与求解方法

**B_EMPIRICAL_RADIAL** 同时作为基准和实施主线；**C_AXISYMMETRIC_REFERENCE** 是带真实轴向算子和端面交换的二维参考。P 保留但不启用，H 不启用。没有为凑路线数量复制同一个 B 模型。

一维径向近似仍是待检验的结构假设。二维 C0 用于固定/移动几何的退化检查，C1 用于端面影响检查；短时 C0/C1 测试不能证明一维全程近似合理。最终需在两条路线分别控制数值误差后比较场、全域最大含水率和事件时间。

主模型的物理坐标形式为：

$$
\begin{aligned}
C_t+u_r C_r &= \frac{1}{r}\frac{\partial}{\partial r}\left(rD_q(C,T)C_r\right),\\
a_q(C)(T_t+u_r T_r) &= \frac{1}{r}\frac{\partial}{\partial r}\left(rk_q(C)T_r\right),
\qquad a_q(C)=\rho_q(C)c_{p,q}(C).
\end{aligned}
$$

其中 q=1、23、4 对应题目的三组物性；具体函数、导数和温标见 [Stage04 §5](workspace/04_model_specification.md)。温度通过扩散系数影响水分迁移，水分通过热储存和传输系数影响温度演化，两场在同一非线性系统中同步求解。温度储存项是 `a(C) × 温度物质导数`，不能换成对 `a(C)T` 求导。

初值为 T=301.15 K、C=2.55 kg/kg；轴心为对称无通量条件。表面采用 Robin 边界：

$$
-k_q T_r=h(T_s-T_\infty),\qquad
-D_q C_r=h_m(C_s-C_{\mathrm{eq,eff}}).
$$

这里的外部水分到有效交换势映射是已声明的工程闭合，尚无独立吸附等温线验证。热方程属于有效显热近似；题给经验密度不能用来宣称已建立真实绝对干质量或完整多相能量守恒模型。原始均匀含水率与 t=0 表面交换条件不完全相容，初始边界层必须保留并做空间收敛检查。

Q4 取自相似径向材料运动 `u_r=r Ṙ/R`，令 `ξ=r/R(t)`。一般变换后的相对输运项系数为 `(u_r−ξṘ)/R`，在这一材料运动假设下抵消，得到：

$$
\widehat C_t=\frac{1}{R(t)^2\xi}\frac{\partial}{\partial\xi}
\left(\xi D_q\widehat C_\xi\right),\qquad
a_q(\widehat C)\widehat T_t=\frac{1}{R(t)^2\xi}\frac{\partial}{\partial\xi}
\left(\xi k_q\widehat T_\xi\right).
$$

因此内部径向算子带 `R⁻²`，表面导数带 `R⁻¹`。C 路线另外加入实际 z 坐标的轴向扩散，轴向算子不能误乘 `R⁻²`。此处只是摘要，完整推导、轴心极限和初边值条件见 [Stage04 §6–§8](workspace/04_model_specification.md)。

数值方法采用圆柱体积加权 FVM、共享面通量、距离加权调和面系数与 Robin 半单元串联阻力；时间上采用自定义变步 BDF2，启动、输入分段重启及受控回退使用 BE，非线性系统用精确 Jacobian 和阻尼 Newton 求解。BE 的两半步仅作误差比较，接受的仍是完整 BE 主步；拒步及辅助解不写入正式历史。

## 4. GPU 改造的范围和验收条件

| 计算部分 | 执行位置 | 当前实现 |
| --- | --- | --- |
| 原始输入、物性、FVM/Jacobian 组装 | CPU | 保留经批准的模型定义与离散 |
| 每次 Newton 的缩放稀疏线性系统 | NVIDIA GPU | CuPy CSR + cuSOLVER，求解 `Aσ d = −rσ` |
| 线性后向误差与范数 | NVIDIA GPU | 与原验收定义一致，返回后按当前 `linear_tol` 判断 |
| 时间控制、轨迹、诊断、事件和 Excel | CPU | 保留正式接受历史及导出合同 |

使用 float64；没有改成 float32，也没有改变物性、时间方法或容差来换取速度。全部随附运行配置显式使用：

```json
{"linear_backend": "CUDA", "cuda_device": 0, "gpu_memory_mb": 2048}
```

正式 `PRODUCTION` 配置禁止 `CPU_REFERENCE`，GPU 故障不会自动退回 CPU。设备、驱动、CUDA/CuPy 版本、成功 GPU 求解次数、传输字节、同步计时等会写入真实运行记录。设备能力探测本身不等于线性方程求解通过，正式证书还要求实际 CUDA 求解遥测及误差类别后端/设备一致。

这次改造由有界子代理参与开发和交叉静态审查，已经修正：后缀重积分丢失 GPU 硬失败状态、测试没有绑定配置中的设备和显存预算、CPU 参考证据可能混入正式 CUDA 证书，以及必跑测试失败后预检总状态仍显示 PASS 的问题。相关回归测试已编写，尚未执行。

**性能尚未实测。** 20/40 层径向网格的矩阵较小，传输和调度开销可能抵消 GPU 收益。2048 MiB 是 CuPy 私有池预算，不能硬限制 cuSOLVER 内部工作区瞬时峰值；内存不足明确退出。当前方案不承诺 GPU 更快，也未实现多卡分布式计算。

## 5. 已有证据与仍未取得的结果

下表中的计算记录全部来自**先前 CPU 修订的历史本地开发运行**，不能用于声称当前 GPU 修订已经通过验证。旧数值核心和当前版本存在差异，旧记录保留原始身份和源码快照。

| 历史运行 | 实际物理时间覆盖 | 结论与限制 |
| --- | --- | --- |
| Q1，20/40 径向网格 | 两者均完成 1800 s | 完成窗口不等于通过空间误差验收；早期真实表面含水率的网格差仍明显 |
| Q2/Q3，S0 | 72826.1782 s，约 20.23 h | 墙钟预算耗尽；已覆盖范围的全域扫描未发现达标事件 |
| Q4，S0 | 92111.1682 s，约 25.59 h | 墙钟预算耗尽；已覆盖范围的全域扫描未发现达标事件 |
| 固定 C0、移动 C0、短时 C1 | 各 60 s | 仅短时开发检查，不能替代全程 B/C 结构比较 |

Q1 的 20/40 网格早期表面含水率采样差最大约 **0.09001846 kg/kg**，未通过开发验收，因此没有批准生成候选 result1。Q2/Q3 和 Q4 尚无合格严格报告时刻，因此没有完整候选 result2–result4。仓库 `data/raw/templates/` 下同名文件是原始空模板。

历史测试记录包括核心 76 项、打包/恢复/预检 9 项、核心回归 24 项等批次；这些批次有重叠，不能相加称为独立测试总数。原 Stage05 的 48 项孤立断言也在先前 CPU 实施轮重跑过。这些均是历史证据。

GPU 修订实际完成的是源码静态语法解析、JSON/TOML 检查、7 原件哈希核对、规格哈希核对、子代理静态审查及 Git 暂存字节一致性检查。**GPU 探测、依赖安装、pytest、GPU 数值求解、服务器任务提交均为 `NOT_RUN`；加速效果为 `NOT_MEASURED`。**

证据入口：[历史开发摘要](workspace/evidence/stage06_development_summary.json)、[GPU 静态审查记录](workspace/evidence/stage06_gpu_static_review.json)。

## 6. 服务器如何执行

需要 NVIDIA GPU、兼容 CUDA 12 的驱动、CUDA 12.x 运行库及 Python 3.11 或更新版本。运行库须包含 cuSOLVER、cuSPARSE、cuBLAS 和 NVRTC；`pip install` 不负责安装显卡驱动。

首次获取仓库：

```bash
git clone https://github.com/zhuoshou111/2025-A-Q5.git
cd 2025-A-Q5/CUMCM2026_A_DRYING
```

已有仓库时，在仓库根目录使用下面两条命令替代上述克隆步骤；有未提交修改时先自行处理，避免覆盖自己的配置：

```bash
git pull --ff-only origin main
cd CUMCM2026_A_DRYING
```

进入项目子目录后，在服务器安装依赖并执行：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .

python -u -m drying pipeline --plan configs/server_first_round.json > server_pipeline.log 2>&1
```

流水线包含预检和必跑测试，无须先重复执行同一套测试。测试按实际计划的可见 GPU 编号和显存预算逐组执行；没有 GPU 或测试失败时阻止正式求解。`cuda_device` 使用 `CUDA_VISIBLE_DEVICES` 映射后的可见编号。

| 首轮顺序 | 输出运行 ID | 网格 | 最大物理时间 | 单次墙钟预算 |
| --- | --- | --- | --- | --- |
| 1 | `EXP101_B_Q1__cuda001` | Nr=20 | 1800 s | 3600 s |
| 2 | `EXP104_B_Q1_nr40__cuda001` | Nr=40 | 1800 s | 3600 s |
| 3 | `EXP102_B_Q23_S0__cuda001` | Nr=20 | 259200 s | 14400 s |
| 4 | `EXP103_B_Q4_S0__cuda001` | Nr=20 | 259200 s | 14400 s |

最大物理时间是计算覆盖上限，墙钟预算是服务器运行时间上限，都不是预计烘干时长。首轮不自动启动全程二维 C1 或全部敏感性组合。

默认相对容差为 1e−6，温度绝对容差 1e−6 K，含水率绝对容差 1e−9 kg/kg；初始步长 0.1 s、最大步长 60 s、接受步数预算 500000，每 500 个接受步保存检查点。这些是数值控制设置，不能直接当作实际全局精度。

在另一终端查看进度：

```bash
tail -f server_pipeline.log
watch -n 1 nvidia-smi
```

从同一版本、同一配置的已保存运行恢复，例如：

```bash
python -m drying run --config results/runs/EXP102_B_Q23_S0__cuda001/config.json --out results/runs/EXP102_B_Q23_S0__cuda001 --resume
```

不得直接续接旧 CPU 检查点。重新从初值计算时使用新的运行 ID，如 `__cuda002`，不能覆盖已有轨迹。普通运行退出码 0 表示请求窗口完成，2 表示预算终止或证据未解决，1 表示数值、配置或工程错误；独立 `preflight --tests` 还保留 pytest 的失败退出码，任何非零值均不能作为验收成功。`TIME_LIMIT_REACHED`、`INPUT_HORIZON_REACHED` 不代表烘干达标。

## 7. 何时才能生成结果文件

Q3/Q4 的判据针对全域最大含水率 `G(t)=max C`，不是均值、最小值或默认只看中心。严格报告要求当前轨迹、误差估计和覆盖范围一致，并实际满足：

$$
\widehat G(t_{\mathrm{report}})+\eta_{\mathrm{strict}}<0.15.
$$

`η_strict` 必须由实际网格、时间、Newton、时间重建及事件加严证据形成，不能填一个人为小常数。事件括区间、较早区间解析和连续保持条件须检查；0.01 s 的定位分辨率不等于真实时间精度。报告时刻向上对齐 0.36 s 格点后，需要同一轨迹覆盖并重新检查。加严差是经验误差估计，不是已经证明的 PDE 误差上界。

Q2/Q3 的 result2、result3 使用同一正式解源。Q4 的 result4 保持固定实际距离列，收缩域外单元格留空，并独立输出真实表面及域掩码。工作簿临时写入后回读，合格才发布为候选文件；候选身份不等于比赛提交批准。

## 8. 回传材料与下一步检查

服务器先生成最小回传包：

```bash
python -m drying pack-return --runs results/runs --out results/stage06_return_minimum.zip
```

请一并保留并回传 `results/preflight.json`、`results/server_tests.xml`、`results/pipeline_summary.json` 和 `server_pipeline.log`。各次运行应包含 config、manifest、environment 及各执行尝试的环境文件、metrics、diagnostics、事件/误差记录、实际候选结果及回读记录。失败或预算终止的记录同样需要回传。

需要复查轨迹和检查点时再生成完整包：

```bash
python -m drying pack-return --runs results/runs --out results/stage06_return_full.zip --full
```

全量入口会自动尝试最小回传 ZIP，准确路径见其 `campaign_summary.json`。上述手动回传命令适用于旧首轮输出；全量任务请将 `--runs` 指向 `results/full/A26_FULL_001`，并使用新的 ZIP 文件名。收到结果后优先独立审查 GPU 一致性、Q1 早期层、严格事件与余额、Q23 同源输出和 Q4 域掩码，再解释自动产生的 B/C 差与敏感性。计算得到差值不代表一维假设已经验证。

Stage07 仍须人工授权后执行；不能因服务器进程退出成功就自动标记验证通过或冻结模型。

## 9. 项目文件导航

| 文件/目录 | 用途 |
| --- | --- |
| [README_RUN.md](README_RUN.md) | 完整运行、恢复、后处理、导出及回传命令 |
| [workspace/04_model_specification.md](workspace/04_model_specification.md) | A26-04-v2 权威数学规格及推导 |
| [workspace/05_presolve_qa.md](workspace/05_presolve_qa.md) | 求解前 QA、修订与人工交接记录 |
| [workspace/06_implementation.md](workspace/06_implementation.md) | 当前实施范围、实现映射、限制及 Gate06 |
| [workspace/06_validation_return_requirements.md](workspace/06_validation_return_requirements.md) | 服务器证据回传合同 |
| [workspace/modeling_state.json](workspace/modeling_state.json) | 阶段 Gate、活动产物、未解决事项 |
| [workspace/data_inventory.md](workspace/data_inventory.md) | 原始附件结构、单位、覆盖与假设来源 |
| [configs/server_first_round.json](configs/server_first_round.json) | 首轮四任务计划 |
| [FULL_RUN.md](FULL_RUN.md)、[configs/server_full.json](configs/server_full.json) | 全量自动入口、预算、恢复与完整任务范围 |
| [src/drying/cuda_backend.py](src/drying/cuda_backend.py) | CUDA 稀疏求解、后向误差及设备遥测 |
| `src/drying/`、`tests/` | 求解与后处理源码，以及供服务器运行的测试 |
| `data/raw/`、`workspace/evidence/` | 便携原件与带证据范围的历史/静态记录 |
| `workspace/stale/` | 历史版本存档，不作为当前权威规格 |

**停止位置：Stage06 交接；GPU 数值验收待服务器执行。**
