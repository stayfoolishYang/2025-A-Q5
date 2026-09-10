# CUMCM2026 A 药材烘干：服务器运行说明

这是 **A26-04-v2 / Stage06** 的实际求解代码。B 为径向主线兼基准，C 为真正的轴对称二维参考；P 保留，H 未启用。Stage07、Stage08 尚未执行，所有本地计算均为开发证据。代码的可运行性、开发测试通过、某个物理时间窗口完成、严格达标以及模型独立验证是不同状态。

用户最新指示：**数值运行交给服务器，本地不再启动求解或数值测试。** 以下命令供用户在服务器执行；上传本代码不代表任务已远程提交。之前产生的本地记录保留为历史开发记录。

## 1. Linux 服务器首次运行

需要 **Python 3.11 或更新版本、CPU、建议至少 2 GiB 可用内存**；不需要 GPU。使用独立虚拟环境。下面的目录是仓库中新增加的文件夹。

```bash
git clone https://github.com/zhuoshou111/2025-A-Q5.git
cd 2025-A-Q5/CUMCM2026_A_DRYING
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
python -m drying preflight --tests
```

已有该仓库时，在确认本机没有待处理修改后更新自己的 checkout，再进入上述子目录；不必再次克隆。Python 的等价模块入口是 `PYTHONPATH=src python -m drying`。本项目没有调用 SciPy BDF 或其他黑盒时间积分器；SciPy 只提供带状/稀疏线性代数等基础数值工具。

一条命令执行首轮流水线：

```bash
python -u -m drying pipeline --plan configs/server_first_round.json > server_pipeline.log 2>&1
```

流水线先运行原件/规格/配置预检、原 Stage05 的48项孤立检查和本项目测试，任何前置失败都阻止求解；随后顺序运行 Q1 的20/40网格、Q2/Q3、Q4。默认生产运行使用 `REMOTE_SERVER + PRODUCTION + production_eligible=true`，但**生产用途不等于 Stage07 PASS**。该命令不自动执行 Stage07，也不自动宣称 result 工作簿合格。

```bash
tail -f server_pipeline.log
ps -ef | grep '[p]ython.*drying'
```

退出码0表示所请求的有限时间窗口已计算完成；2表示预算耗尽或误差/事件证据未解决；1表示数值、配置或工程错误。`TIME_LIMIT_REACHED`/`INPUT_HORIZON_REACHED`不等于烘干达标。独立任务遇到预算耗尽时流水线可继续其余任务，但总状态和退出码保留 PARTIAL/2；数值失败停止后续求解。

## 2. 分别运行、短时检查与恢复

```bash
python -m drying run --config configs/smoke.json --out results/runs/EXP100_smoke__srv001
python -m drying run --config configs/B_Q1.json --out results/runs/EXP101_B_Q1__srv001
python -m drying run --config configs/B_Q23_S0.json --out results/runs/EXP102_B_Q23_S0__srv001
python -m drying run --config configs/B_Q4_S0.json --out results/runs/EXP103_B_Q4_S0__srv001
python -m drying run --config configs/C0_fixed_short.json --out results/runs/EXP106_C0_fixed__srv001
python -m drying run --config configs/C0_moving_short.json --out results/runs/EXP107_C0_moving__srv001
python -m drying run --config configs/C1_short.json --out results/runs/EXP108_C1_short__srv001
```

`smoke`和 C 短时配置保留开发用途，不能因为在服务器运行就升级证据。完整 C1 的 Q23/Q4 配置也已提供：`configs/C1_Q23.json`、`configs/C1_Q4.json`；本轮不要求自动运行这两项长算。

若已经执行流水线，不能再用上面相同输出路径从头运行。每次新运行使用新的 `__srv002` 等后缀。恢复原运行必须使用原配置、原源码和原始输入：

```bash
python -m drying run --config results/runs/EXP102_B_Q23_S0__srv001/config.json --out results/runs/EXP102_B_Q23_S0__srv001 --resume
```

每次恢复有新的有限墙钟/步数预算，沿用合法 BDF 历史；已有数值配置不能修改后直接续接。初始检查点、每500接受步检查点以及最终检查点均保留。若异常退出造成已落盘轨迹领先检查点，恢复会保留旧索引/块和日志，再恢复到最后完整检查点；不会覆盖已存历史块。每次执行尝试保存独立环境记录。源码整体指纹变化会拒绝直接续接；旧版本可使用其 `source_snapshot/src` 重现原算法，或以新版本和新 run_id 从初值重跑。

默认 B 主线最大物理时间72 h，Q1为1800 s；Q23/Q4服务器墙钟预算各4 h，步数上限500000。所有配置都使用float64，h0≤0.1 s、hmax≤60 s，默认 rtol=1e-6、atolT=1e-6 K、atolC=1e-9 kg/kg。内存由运行前容量估计和每100步检查协作限制；Linux/macOS检查历史峰值RSS，Windows检查当前工作集，这不是操作系统硬隔离。配置中2048 MiB不表示一定会用满。Q1开发实测20/40层各约46 s，不能据此保证更细网格、二维或另一台服务器的耗时。

## 3. 输入和模型约束

`data/raw`中的题目PDF、环境数据、半径数据和四个模板均为原件的未修改复制品，`source_manifest.json`保存字节数、哈希和数据模式。预检固定核对权威哈希。运行时不依赖原来的 Windows 桌面路径。

Q2从原始初值开始，Q3使用同一 `question=23` 轨迹。环境在观测区间分段线性，S0/S1及14400 s左右极限由代码显式定义。半径主方法为分段线性，`radius_method="pchip"`实际选择另一条重建路径。Q4默认在72 h停止；没有偷偷延长半径。明确采用外延情景时，使用单独配置，将 `radius_tail`设为`HOLD`或`R_EXT_HOLD`并给出有限、超过259200 s的`tmax`，另用新的运行身份。

数学依据、初边值条件及输出合同见 `workspace/04_model_specification.md`。二维半域为0≤z≤0.125 m，轴向算子使用实际z尺度；材料径向坐标含R(t)^(-2)。温度方程为a(C)乘温度物质导数，不是对aT求导；经验密度不用于宣称真实绝对干质量或完整热力学守恒。

## 4. 观察结果和误差加严

```bash
python -m drying summarize results/runs/EXP102_B_Q23_S0__srv001
python -m drying compare-q1 results/runs/EXP101_B_Q1__srv001 results/runs/EXP104_B_Q1_nr40__srv001 --out results/q1_comparison.json
python -m drying plan-refinement --config configs/B_Q23_S0.json --out results/q23_refinement_plan.json
```

`summarize`生成全域事件扫描、轴心/真实表面时序和题面指定点CSV；CSV始终保留开发、尚未合格的身份。Q1快速比较覆盖早期、轴心和表面，但不是全域误差界。严格误差模块另在接受时刻并集及加密中点比较两空间重建的分段多项式极值，保存时间比较稳定性和容量/墙钟终止状态。

`plan-refinement`只生成实际 RunConfig 字典，不启动长算。B包含径向20/40/80、细网格上的时间/非线性/稠密输出各三级配置以及0.01/0.005/0.0025 s事件细化目标；C另包含轴向和联合加严。可将某一级字典保存为JSON，再用同一 `run --config`执行；`RunConfig.from_dict`直接接受这些字典。禁止将粗网格与细网格前后拼接为正式解。

严格处理接口均在 `drying.refinement`，CLI提供对应入口：

```text
refine-event RUN --out NEW_DIRECTORY --width 0.01 --wall-seconds 300
error-evidence REFERENCE_RUN --categories CATEGORIES_JSON --out EVIDENCE_JSON
prepare-report RUN --evidence EVIDENCE_JSON --out NEW_DIRECTORY
recompute-balances FINAL_RUN
certify FINAL_RUN --evidence REFRESHED_EVIDENCE_JSON --candidate CANDIDATE_JSON --out EVENT_JSON
```

这里的大写名称是接口参数说明，不是可以直接运行的虚构路径。`CATEGORIES_JSON`是`radial/time/newton/dense/event`（C另有`axial/joint`）到实际运行目录列表的映射，每类至少三级。证据取各类最近两项相邻差的`2 max`再累加，保留缺失或不收敛状态。局部事件必须从真正接受检查点重积分；仅插值细分不会被记作事件加严。细化轨迹需重新计算其余额，再刷新误差证据。`prepare-report`处理0.15±η阈值和0.36 s向上格点；它改变轨迹后，必须重新构建该最终轨迹的误差证据。余量变化、较早区间未解析、反弹、报告覆盖不足或预算不合格都会拒绝证书。误差加严差仍是经验估计，不能称为数学严格误差上界。

## 5. 候选导出及回读

Q1仅在完成开发误差审阅后才能使用 `--q1-reviewed`。本轮20/40网格早期表面含水率差明显，**没有给予这一批准，也没有生成候选result1**。

Q23/Q4须先得到当前轨迹对应的合格事件JSON，再调用：

```text
export RUN --event VERIFIED_EVENT_JSON --out NEW_CANDIDATE_DIRECTORY
verify-output RUN WORKBOOK --question 2 --end ACTUAL_REPORT_SECONDS
```

工作簿分问取1/2/3/4；Q2和Q3对应相同的配置23，但回读频率不同。Q23一次导出同时生成result2/result3并检查同源一致性。原模板只读，候选临时写入、回读通过后原子发布；旁置manifest是该组完成标记。表内数值保持全精度并显示四位小数，Q4域外留空并另外保存半径/掩码CSV。没有合法事件时，不生成冒充完整烘干的result2–4。

## 6. 回传

```bash
python -m drying pack-return --runs results/runs --out results/stage06_return_minimum.zip
python -m drying pack-return --runs results/runs --out results/stage06_return_full.zip --full
```

先回传minimum包、`results/preflight.json`、`results/pipeline_summary.json`和`server_pipeline.log`。minimum包含各运行manifest、配置、实际环境、指标、余额、事件和结果/回读记录；full另含接受轨迹、检查点、逐步日志及源码快照。失败和预算终止也须回传，不用删去失败记录来形成全成功列表。

本仓库不包含大量本地轨迹、检查点或缓存；本地首轮摘要和真实测试记录在`workspace/evidence`，完整本地轨迹保留在原项目的`results/runs`。更细误差分析、B/C全程结构比较及物理解释的独立审查留给经人工授权的Stage07。
