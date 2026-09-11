# q3better：保留七点，定位后刷新发现路线

本目录交付 Q3 七点路线候选及可复核的离线实验。32 场配对结果中，平均每源节省 **31.293833 秒**，平均整局节省 **380.916200 秒（9.52%）**。这不是六点布局，也没有启用清除 16 源提前退出。

| 指标 | A 原版 | B 定位后刷新 |
| --- | ---: | ---: |
| 平均整局时间 | 4001.830718 s | 3620.914518 s |
| 每场秒/源的算术平均 | 326.654411 s | 295.360578 s |
| 秒/源 P95 | 407.332189 s | 354.290440 s |
| 秒/源 P99 | 412.675447 s | 409.724875 s |
| 全清 | 32/32 | 32/32 |
| 光学兜底总次数 | 1 | 5 |

**28 场变快、3 场变慢、1 场持平。最大退步为 1232.146439 秒，最大节省为 959.895606 秒。** 本目录提供可运行候选，不代表已确认的生产默认方案。数据是复用 32 个探索场景的真实离线计算，不是官方测试成绩或独立留出集。

## 改动原理

原版扫完发现点后已经重排，但定位改变实际位置后未立即重排。候选构造相同 Q3/P3 求解器后仅设置：

```python
solver.discovery_route = 'refresh_after_localize'
```

复用 `discovery.refresh_remaining_route`，保留全部七点和各点尚未清除频道的扫描义务。从同一当前位置比较剩余完整开放路线，选择更短者。局部路线变短不保证完整任务逐场变快，因为观测和定位过程也随访问顺序改变。

`run_q3.py` 是本目录专用离线入口，默认使用候选 B；`--baseline` 运行 A。仓库其他入口和默认配置没有修改。源码快照保留已有构造器限制，不能把该参数直接塞进旧 Q3 构造配置，须使用这里展示的实例设置方式。

## 安装与单场运行

从仓库根目录执行：

```powershell
python -m pip install -r q3better/requirements.txt
python q3better/run_q3.py --sim-root 'D:\桌面\2026国赛\b模拟器\Jammers-Offline-Windows' --output q3better/runs/candidate_000.json
python q3better/run_q3.py --sim-root 'D:\桌面\2026国赛\b模拟器\Jammers-Offline-Windows' --baseline --output q3better/runs/baseline_000.json
```

请将 `--sim-root` 改为自己的指定离线模拟器目录，其中应有 `engine.py`、`scenario_io.py`、`recovered_generator.py`。原实验使用 Windows 1.2.0 / practice-gen-v1。模拟器不随包上传；不使用目录内的自建 `simulator.LocalSimulator` 生成本报告成绩，也不连接官方服务。只运行本 Q3 路径需要 NumPy、SciPy，不需要 Torch 或 GPU。

默认使用随包场景 000；用 `--scene <场景.json>` 选择其他 Q3 场景。输出文件必须不存在。单场入口会验证七点扫描、整数微秒账本、正常退出和全清，真实源信息只用于运行后的评价。

## 复现完整 32 场配对

```powershell
python q3better/B_solver/experiments/q3_seven_route_probe.py --sim-root 'D:\桌面\2026国赛\b模拟器\Jammers-Offline-Windows' --output q3better/runs/paired_repeat_01
```

输出目录必须不存在。脚本重跑 A、B，检查 A 完整动作日志与随包历史基线精确一致，并校验源码、场景和引擎指纹。若引擎版本不同，指纹检查会拒绝将其冒充原实验复现。可用 `--count 2` 做短验证；完整结果需要默认 32 场。

## 文件与来源

- [完整实验报告](B_solver/results/q3_seven_route_probe_01/REPORT.md)：阶段成本、全部退步案例及证据限制。
- [逐场配对结果](B_solver/results/q3_seven_route_probe_01/pairs.csv) 与 [汇总](B_solver/results/q3_seven_route_probe_01/summary.json)。
- `B_solver/results/q3_seven_route_probe_01/traces/`：64 份完整轨迹；`verification.json` 保留原落盘验证及轨迹哈希。
- `B_solver/results/q3_stop16_pilot_01/`：仅打包本次复现所需的 32 个物理场景和原版 A 轨迹。筛选后的 manifest 保留原来源 manifest 的 SHA-256；没有包含或宣传旧 stop16 候选结果。
- `B_solver/*.py`、`B_solver/directional/*.py`：按原实验指纹保留的完整模块集合，包括未在 Q3 路径使用的历史模块；没有把其他模块变更合入仓库原位置。此集合用于确保 `source_hashes` 可原样复核。
- 两个 `experiments/*.py` 保留原实验字节；旧报告中的绝对路径是历史来源，当前复现使用本 README 命令。
- `package_manifest.json`：本发布目录文件的 SHA-256，排除 manifest 自身和 `runs/`。

证据类型：`execution_backend=LOCAL_DEV`、`execution_purpose=FRAMEWORK_INTEGRATION`、`production_eligible=false`。32 场均完成 A/B 配对，64 次全部全清且审计通过；这不证明所有新场景都改善，也不支持模型冻结。
