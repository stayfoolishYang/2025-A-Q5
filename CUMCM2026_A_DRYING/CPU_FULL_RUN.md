# CPU 求解与全量开发测试

发布修订：**A26-06-CPU-FULL-v1**。连续数学依据仍为 **A26-04-v2**，完整推导见 [数学模型规格](workspace/04_model_specification.md)，前置数学审查见 [Stage05 QA](workspace/05_presolve_qa.md)。

本入口启用我们原有的 `CPU_REFERENCE` 分支：B 径向一维路线使用 SciPy 带状方程组求解，C 轴对称二维路线使用 SciPy 稀疏 LU。变步 BDF2/BE、耦合 Newton、物性、边界与误差控制均保留；CPU/GPU 差异位于线性求解后端。它不采用 A_model 的 Numba/Picard 实现。

历史版本：`64a1c71` 为原 CPU 包，`8b309d6` 增加 CUDA 后端并保留 CPU 参考分支，`a67d2fc` 增加 GPU 全量计划。本发布将该完整计划转换为 CPU 开发运行，重算配置指纹、运行编号和所有交叉引用。

## Linux 启动

新机器克隆仓库后，进入项目子目录；已有仓库可更新后直接进入该目录。建议使用 Python 3.11 的独立环境。

```bash
git clone https://github.com/zhuoshou111/2025-A-Q5.git
cd 2025-A-Q5/CUMCM2026_A_DRYING
python3.11 -m venv .venv-cpu
source .venv-cpu/bin/activate
python -m pip install -r requirements-cpu.txt
export PYTHONPATH="$PWD/src"
export PYTHONUTF8=1
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
python -u -m drying.cpu_campaign --plan configs/server_full.json --out results/local_cpu/CPU_FULL_001 > cpu_full_001.log 2>&1
```

CPU 入口直接通过 `PYTHONPATH` 加载 `src`，无需安装 CuPy。默认 `requirements.txt` 和 `pip install .` 的项目依赖用于原 GPU 包；本次按上述 CPU 依赖清单执行。

在另一终端查看日志：

```bash
tail -f cpu_full_001.log
```

服务器断线后仍需继续的运行，请在已有的 tmux/screen 会话或作业调度器中执行同一命令。

## Windows PowerShell 启动

先进入克隆仓库中的 `CUMCM2026_A_DRYING` 目录：

```powershell
py -3.11 -m venv .venv-cpu
& .\.venv-cpu\Scripts\python.exe -m pip install -r requirements-cpu.txt
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
$env:PYTHONUTF8 = '1'
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
& .\.venv-cpu\Scripts\python.exe -u -m drying.cpu_campaign --plan configs/server_full.json --out results/local_cpu/CPU_FULL_001 *> cpu_full_001.log
```

在另一 PowerShell 终端查看：

```powershell
Get-Content -LiteralPath cpu_full_001.log -Tail 20 -Wait
```

## 计划、恢复与结果

只展开计划，不执行求解：

```bash
python -m drying.cpu_campaign --plan configs/server_full.json --plan-only
```

恢复同一次运行：在其进程已经退出后，使用同一源码、输入、计划、环境与输出目录追加 `--resume`：

```bash
python -u -m drying.cpu_campaign --plan configs/server_full.json --out results/local_cpu/CPU_FULL_001 --resume > cpu_full_001_resume.log 2>&1
```

Windows 使用上文的 `.venv-cpu\Scripts\python.exe` 解释器和 `*>` 重定向。新计算使用新输出目录，不加 `--resume`；CPU 与 GPU 的检查点不能混用。输出目录锁会拒绝两个进程同时写入。

入口自动执行 CPU 预检、原件与数学规格哈希检查、Stage05 孤立检查，以及 `pytest -q -m "not cuda"`。这些检查通过后，才启动完整数值计划：

| 范围 | CPU 入口行为 |
| --- | --- |
| 主配置 | 保留 67 个去重配置、11 个基础配置来源 |
| 场计算 | Q1 为 1800 s；Q23/Q4 主窗口上限 72 h；B 一维及 C 二维均保留 |
| 数值误差 | 径向、轴向、联合网格、时间、Newton、dense 对照；二维最高 80×80 |
| 事件与报告候选 | 原检查点重积分、误差更新、覆盖补齐、报告候选与独立累计余额链 |
| 结构与敏感性 | 14 组比较，包含 8 个单因素敏感性变体 |
| 输出 | 配置、轨迹、检查点、诊断、指定点/观测 CSV、汇总及最小回传包 |
| CUDA 专属测试 | 不适用，不计为通过 |
| 正式 CUDA 证书及竞赛工作簿 | 不签发、不导出；开发候选保留明确用途标签 |

所有物理参数、网格、时长、容差和资源预算都保持原计划。每次调用仍受 48 h 会话预算限制，各配置保留原墙钟与步数预算；这个预算不是预计完成时间。任务未完成或误差未满足要求时如实保留 `PARTIAL_OR_UNRESOLVED`，不自动放宽标准。

结果目录包含：

```text
results/local_cpu/CPU_FULL_001/
  live_progress.json       # 实时阶段、当前运行编号、完成主任务数
  expanded_plan.json       # CPU 配置和完整来源/引用映射
  campaign_state.json      # 运行、尝试及续跑状态
  logs/invocation_001/     # CPU 预检、pytest XML 和各配置日志
  runs/                    # 实际轨迹、检查点、指标
  analysis/                # 已执行的误差/事件/余额分析
  campaign_summary.json   # 每次有限调用结束时的汇总
```

`CPU_FULL_TEST_COMPLETE` 仅表示适用的完整 CPU 开发链完成；`CPU_FULL_TEST_PARTIAL_OR_UNRESOLVED` 表示仍有预算、覆盖或误差问题；`CPU_FULL_TEST_FAILED` 表示测试、数值或工程错误。三者均不等同于 Stage07 通过或模型冻结。

执行用途固定为 `LOCAL_DEV + FRAMEWORK_INTEGRATION + production_eligible=false`。即使在服务器上运行这个 CPU 测试入口，证据用途也不会自动升级为生产验证。

## 已有执行证据

2026-09-11，本机 CPU 预检通过，适用测试为 **258 passed、13 个 CUDA 用例 deselected**，约 130.89 s。首个 Nr20、1800 s 的完整 Q1 主求解耗时 40.4393 s，接受 2757 步；这些是本机开发证据。发布时全量任务仍在执行，不声明 67 项全部完成，也不据此宣布最终模型达标。

一项原有测试曾将不同半径上的常量场插值差要求为精确零，本机产生约 5.7e-14 的温度舍入差；本修订仅将该测试改为 `64 × epsilon × 物理量尺度`，没有修改比较算法或求解器。

待提交代码在独立工作副本中核对，与本机实际执行源码/测试建立哈希映射；发布证据见 [CPU 发布检查](workspace/evidence/cpu_publication_checks.json)。原 GPU [运行入口](FULL_RUN.md)继续保留。Stage07/08 均为 NOT_RUN，模型未冻结。
