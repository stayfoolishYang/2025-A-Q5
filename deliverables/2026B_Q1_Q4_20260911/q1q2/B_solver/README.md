# 2026 B题：集合定位、覆盖搜索与CUDA假设计算

## 当前状态与阅读入口（2026-09-11）

Q2新增离线外层站位审计：[接收域与细化完整报告](Q2_OUTER_REFINEMENT_REPORT.md)、
[独立数学证明](Q2_RECEPTION_DOMAIN_PROOF.md)、[原始证据](results/q2_reception_outer_20260911/acceptance.json)。
旧213复现；原域加密与direction接收域扩大合计降低J约0.71755%，低于预设1%采用门槛。
保留旧默认和正文，Q1/Q3/Q4不变；当前分支只提交本轮证据，不自动推送。

当前状态以[STATUS.md](STATUS.md)为准。Q2已完成固定213候选的评分与near分支审计，原选点保留；Q4主候选为MEC + diagnostic v1 + D1，D2停止。最新求解代码与审计结果位于本目录，下面较早的实验介绍作为历史记录保留。

- [Q2最新评分结论与卡尺反例](Q2_SCORE_RESULTS.md)、[全部213候选证据](results/q2_score_20260911/RESULTS.md)。
- [Q4发现调度结果](Q4_DISCOVERY_RESULTS.md)、[D2完整对照与停止决定](Q4_WORKLOAD_RESULTS.md)。
- [Q1/Q2十二页文稿](paper/q1_q2_model_v2.pdf)、[LaTeX与比较脚本说明](paper/README.md)。本次将既有文稿原样入库；最新Q2评分审计尚未并入正文。
- [文稿交接包使用说明](../交付包/2026B_Q1Q2_怎么用.md)、[含字体与证据的文稿交接包](../交付包/2026B_Q1Q2_正文比较版_代码LaTeX图片CSV_20260911_132505_含使用说明.zip)。该包为生成时刻的存档，最新代码和状态以仓库文件为准；LaTeX引用的原模板字体可从包内取得。

此前7c90ba1归档已有B题成果和更新入口，没有运行求解器、模拟器或正式测试。A题并行成果不在该次上传范围。

项目入口：[题目分析报告](题目分析报告.md)。本目录独立于原2025 A题程序。

## 运行环境

推荐使用本机已有环境：`D:\Anaconda3\envs\torchgpu\python.exe`（PyTorch 2.7.1+cu118，RTX 4060 Laptop）。
默认`D:\Anaconda3\python.exe`是CPU版Torch且SciPy太旧，不适用于Q1的HiGHS线性规划入口。CPU策略、批量实验仍可运行。

在仓库根目录执行：

```powershell
& 'D:\Anaconda3\envs\torchgpu\python.exe' B_solver/questions.py
& 'D:\Anaconda3\envs\torchgpu\python.exe' B_solver/solver.py --problem 3 --seed 0
& 'D:\Anaconda3\envs\torchgpu\python.exe' B_solver/solver.py --problem 4 --seed 0 --device cuda
& 'D:\Anaconda3\envs\torchgpu\python.exe' B_solver/experiments.py batch --count 100 --workers 4
& 'D:\Anaconda3\envs\torchgpu\python.exe' B_solver/ablations.py
```

Q1自定义观测JSON格式：`[{"position":[0,0],"bearing_deg":30}, ...]`。

```powershell
& 'D:\Anaconda3\envs\torchgpu\python.exe' B_solver/questions.py --observations measurements.json
```

默认求纯测向半平面交集，可返回有界、无界、空。添加`--arena-radius 1800`才引入已知圆域的保守外切多边形近似。Q2数值示例不是题目未提供的实测数据。

## 官方演练

已通过computer-use操作已登录模拟器的“演练测试”页，并通过四个正式公布的HTTP接口完整运行。没有启动正式测试。界面先选择**开始问题3演练测试**或**开始问题4演练测试**，等待“等待机器狗进入”再执行：

```powershell
& 'D:\Anaconda3\envs\torchgpu\python.exe' B_solver/solver.py --mode practice --problem 3 --robot-id YOUR_TEAM_ID --output B_solver/results/official_practice/new_q3.json
& 'D:\Anaconda3\envs\torchgpu\python.exe' B_solver/solver.py --mode practice --problem 4 --device cuda --robot-id YOUR_TEAM_ID --output B_solver/results/official_practice/new_q4.json
```

**HTTP协议不返回演练/正式模式。** `--mode practice`是明确的客户端入口标签，不能替代对模拟器当前界面的核对。程序不具备启动模拟器测试或选择正式测试的功能。本次操作均在已核实的演练会话中执行。

原始请求和响应保存在同名`.jsonl`，汇总保存在`.json`。总源数由演练结束后的UI读取，`/exit`不会返回源数。必须用UI数量核对清除率，不能以已发现数量代替分母。加密`.jlog`由模拟器保存，JSONL是本程序的可读行为记录。

## 文件

当前交付报告为`解题报告.md`和`解题报告.docx`，含Q1至Q4模型、证明、八幅图、配对实验与六个官方演练结果。600个本地主对照案例全部清除，官方Q3三例与Q4三例也全部清除；Q4最新案例因两次网格兜底耗时4955.39秒/源，须保留这一效率不足。正式测试次数为零。

逐条计时核验见`audit_logs.py`及`results/official_practice/summary.csv`。报告构建脚本依赖当前已安装的数学建模skill文档格式模块；求解器不依赖该模块。

| 文件 | 用途 |
|---|---|
| geometry.py | 外包半平面裁剪、旋转卡壳、MEC、覆盖、NBV |
| questions.py | Q1任意观测求解和Q2候选区域/权重算例 |
| solver.py | P0至P4策略及官方演练入口 |
| simulator.py | 精确协议计时的自建环境、幂等HTTP客户端 |
| particles.py | 混合源类型假设、历史约束重放、双分块CUDA计数 |
| experiments.py | 完整案例、几何核验、100万粒子CUDA实算 |
| ablations.py | 第二测点、点估计、覆盖、调度、停止条件对照 |
| results/batch | 第一版600个本地完整案例 |
| results/batch_v2 | 当前版600个本地完整案例，写报告用这一版 |
| results/official_practice | 官方演练HTTP记录及结果 |
| results/geometry_checks.json | 真实目标包含关系与连续覆盖补充验证 |

P0：发现后光学网格；P1：几何侧向测点、立即定位；P2：NBV、立即定位；P3：NBV与事件调度；P4：混合类型粒子主动观测、半平面覆盖和调度。P0只作可运行兜底，未混入P1至P4的主对比表。主表P2/P3包含扫描方式与重规划的联合差异，单独的调度开关实验见`ablations.py`。

## 结论边界

有数学保证的是发现覆盖、外包位置集合与MEC/光学网格清除。有限粒子、离散NBV和近邻/2-opt调度均为启发式，不宣称全局最短耗时。源类型包含全向和定向，粒子耗尽不会判定源不存在。CUDA只参与启发式计数；FP64几何做清除证书。

600个合成案例采用100个配对种子，每种随机/边界向外/固定±1°偏差/聚簇场景25个，乘六个策略配置。它们不是600个独立官方案例，也不是官方随机分布。第一版和第二版使用同样种子，不能把两版相加宣称1200个独立样本。官方演练单列；正式测试结果为空。

## 多卡服务器

`multi_gpu.py`在每张GPU运行独立合成案例worker，统一通过`CUDA_VISIBLE_DEVICES`选择设备；只使用PyTorch FP32，兼容V100和4090的算法路径，不依赖BF16/FP8。服务器未提供，本次验证硬件仅本机4060，不声称已在8卡服务器部署成功。

```bash
python multi_gpu.py --gpus 0,1,2,3,4,5,6,7 --cases 1000 --output results/server
```

远程服务器不能直接连接模拟器的127.0.0.1接口。服务器承担自建实验和参数研究，官方演练客户端仍在模拟器所在电脑运行。
