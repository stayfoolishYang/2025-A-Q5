# q3better：七点重排、蛇形兜底与主动失败计数修复

默认入口现使用 **D版**：保留7个发现点，定位结束后重排剩余路线；光学网格采用已有蛇形顺序；仅主动定位的无信号消耗连续失败次数。发现扫描的无信号保留在历史中，但不提前触发兜底。

**64场配对结果：平均每源节约47.28秒（14.15%），修复版平均286.77秒/源；128次运行全部全清并通过审计。** 这是已完成实验的结果，此次发布按用户要求没有再次运行测试。

| 集合 | 原版A秒/源 | 修复版D秒/源 | 平均每源节省 | 胜/负/平 |
|---|---:|---:|---:|---:|
| 旧32场 | 326.65 | 287.53 | 39.13秒 | 29/2/1 |
| 新增32场 | 341.44 | 286.00 | 55.44秒 | 30/1/1 |
| 全部64场 | 334.05 | 286.77 | 47.28秒 | 59/3/2 |

平均整局4079.65→3511.44秒，省568.22秒。每源节省的中位数为36.47秒；新增场景50单局省7687.96秒，拉高了均值。三场退步分别为场景21慢12.90秒、场景29慢11.37秒、场景42慢15.17秒，均全清。不存在逐场必胜保证。

## 使用

从仓库根目录运行：

```powershell
python -m pip install -r q3better/requirements.txt
python q3better/run_q3.py --sim-root 'D:\桌面\2026国赛\b模拟器\Jammers-Offline-Windows' --output q3better/runs/candidate_000.json
```

默认运行D版。加 `--baseline` 运行最初原版A；用 `--scene <场景.json>` 选择Q3场景。默认场景为随包场景000；输出文件必须不存在。

`--sim-root` 应指向自己的离线模拟器目录，内含 `engine.py`、`scenario_io.py`、`recovered_generator.py`。原实验为 Windows 1.2.0 / practice-gen-v1，仅使用离线Engine，不连接官方账户或接口。Q3执行路径需要NumPy和SciPy，不需要Torch或GPU。

## 最小改动

策略实现见 [active_failure.py](active_failure.py)，内容与64场实验执行版本逐字节相同。入口按以下方式构造候选：

```python
solver = ActiveFailureSolver(api, False, 'P3', diagnostic=dict(CONFIG, local_order=True))
solver.discovery_route = 'refresh_after_localize'
```

发现无信号不增加或清空主动失败计数；任何方向观测仍清零该计数并累计方向次数；主动定位连续3次无信号或累计8次方向观测仍进入完整光学网格。没有删除兜底，没有改变7点、频道扫描义务、MEC清除规则或停止条件，没有启用stop16。

64场D恰好未触发光学兜底。之前已通过另外的强制分支检查，确认3次主动失败和8次方向观测两种兜底仍可执行。该逻辑检查与真实场景实验分开记录。

## 结果与来源

- [64场完整报告](results/active_failure_64_01/REPORT.md)
- [逐场配对结果](results/active_failure_64_01/pairs.csv) · [分组汇总](results/active_failure_64_01/aggregate.json)
- `results/active_failure_64_01/scenes/`：64个冻结场景。
- 同目录128份压缩轨迹及 `manifest.json`、`artifact_verification.json`：执行过程、种子与文件指纹。
- `results/active_failure_64_01/executed/`：原实验脚本和候选源码的未改动副本、计数回归及强制兜底检查脚本与历史检查记录。它们保留原实验工作区路径，用于审计。
- `history/seven_route_32/`：上一发布版的入口、说明和打包清单；原 `B_solver/results/` 下的历史证据继续保留。
- `B_solver/*.py` 和 `B_solver/directional/*.py`：原始执行模块快照保持不变，其中历史工具并非本次新增策略。新策略在快照之外通过小子类实现。
- `package_manifest.json`：本次发布的文件SHA-256；`package_verification.json`记录既有验证来源和此次未重测的边界。

报告中“未推送GitHub”等表述记录实验完成时的状态；这些历史报告现在随本次更新发布。

## 复现已有64场

```powershell
python q3better/experiments/replay64.py q3better/runs/replay64_01 'D:\桌面\2026国赛\b模拟器\Jammers-Offline-Windows'
```

输出目录必须不存在。此包装脚本直接使用已保存的64场，核对源码/引擎指纹，并比较A/D完整动作与历史轨迹；不重新抽样，不能当成另一批新确认场景。原执行脚本另行完整保留。此次仅调整发布入口及复现路径，按用户要求未运行更新后的包装入口或重跑实验。

## 证据边界

旧32场用于开发，新增32场在策略固定后首次使用；全部场景在该轮执行前冻结，没有筛选输赢或混入手工压力案例。只能将新增32场称为该候选在本地生成器上的首次确认，不能将混合64场全部当作独立留出集。

证据为 `LOCAL_DEV / FRAMEWORK_INTEGRATION`、`production_eligible=false`。全清实测不等于所有未来场景均能在限时内完成，也不是官方测试成绩。依赖使用版本下限而非完整环境锁；跨环境复现须以脚本检查为准。
