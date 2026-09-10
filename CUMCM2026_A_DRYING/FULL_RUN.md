# GPU 服务器全量自动运行

实现修订：**A26-06-FULL-v1 / 0.6.2**；数学基线保持 **A26-04-v2**。此入口由服务器执行，当前只有静态检查，GPU 预检、测试、求解和端到端运行均 **NOT_RUN**。

## 直接运行

在仓库的 `CUMCM2026_A_DRYING` 子目录、已安装依赖的 Python 3.11+ 虚拟环境中执行：

```bash
python -u -m drying full-run --plan configs/server_full.json --out results/full/A26_FULL_001 > server_full_001.log 2>&1
```

入口自动执行 CUDA 预检和必跑测试，无需再手动调用 `preflight --tests`。首次环境安装见 [README_RUN.md](README_RUN.md)。建议在服务器的 tmux/screen 会话或作业调度系统中运行，以免 SSH 断开影响进程。

查看进度与断点恢复：

```bash
tail -f server_full_001.log
python -u -m drying full-run --plan configs/server_full.json --out results/full/A26_FULL_001 --resume > server_full_001_resume.log 2>&1
```

`--resume` 使用相同源码、输入、配置和计划。恢复前会再次进行设备预检和测试，重新校验已完成任务的身份与实际轨迹块；合法完成项复用，部分运行从有效检查点续接。初始化中断、尚无检查点的目录保留，另分配新尝试目录。改动源码、输入、计划或设备/数值配置后，使用新的输出目录，例如 `A26_FULL_002`。

仅查看展开计划：

```bash
python -m drying full-run --plan configs/server_full.json --out results/full/A26_FULL_001 --plan-only > full_plan_preview.json
```

该选项只读取计划并输出展开的 JSON，不创建运行目录、不探测 GPU、不开始求解。

## “全量”覆盖什么

| 内容 | 自动执行范围 |
| --- | --- |
| 前置验收 | 原件/数学规格/配置核验、CUDA float64 设备检查、原 Stage05 孤立检查、强制 GPU 测试 |
| 基础配置 | 随附的 11 份 RunConfig，包括 Q1 20/40/80、B 的 Q23/Q4、短 C0/C1 和全程 C1 Q23/Q4 |
| 数值误差 | Q1、B_Q23、B_Q4 的径向/时间/Newton/dense 各三级；C1_Q23/C1_Q4 另含轴向和联合网格各三级 |
| 事件细化 | 四个烘干 case 的 0.01/0.005/0.0025 s 实际检查点重积分；Q1 无烘干事件要求 |
| 严格报告 | 实测误差 → 有限覆盖与报告准备 → 最终轨迹证据刷新 → 独立累计余额 → 当前轨迹认证 |
| 结构对照 | 两个短 C0 的匹配 B 对照，以及 Q23/Q4 在基础/参考网格上的 B/C 场、全域最大值、事件时间和 C 轴向离差 |
| 敏感性 | 8 个单因素变体：B_Q23/B_Q4 各自 S1、S0 的 2.5/3.5 h 窗口，加 Q4 PCHIP 和固定几何 |
| 交付 | 时序/指定点 CSV、真实证据与失败记录、条件生成并回读 result1–result4、最小回传 ZIP |

按配置集合静态核算，默认计划预期为 **67 个去重后的主求解配置、14 组比较**；数量断言及与既有加严生成器的交叉检查已写入服务器测试，尚未在本机执行。事件重积分、报告准备、余额重算和重试另计，因此 67 不是总进程数或总计算次数。相同完整 RunConfig 指纹只求解一次。主求解按计划顺序执行，当前入口使用一个选定 GPU，没有多卡并行调度。

局部事件细化会从合法检查点按原时间控制实际推进到事件附近，保存新的真实接受检查点，再使用细步长；两段共用有限预算并保存 `phase_diagnostics.json`。共同覆盖先取实测事件附近，再按实测误差余量和完整源轨迹的阈值扫描按需补齐，避免无条件用极小步长推进整个允许等待上限。

这里的全量是上述有限实验计划。Q1 覆盖 1800 s，Q23/Q4 主窗口上限 72 h；Q4 默认半径数据到期即止，不自动延长。没有自动执行无限参数搜索、无限网格加密或模型改进。

## 预算、资源与状态

`configs/server_full.json` 集中配置设备、显存/主存和工作预算：

- 默认可见 GPU 0，CuPy 显存池和主存各 2048 MiB。可在首次运行前修改 `hardware`；生产任务没有 CPU 自动回退。显存池预算不等于 cuSOLVER 全进程硬限额。
- 每次明确调用 `full-run` 或 `--resume` 的计算阶段上限 **48 h**，然后最多另用 **300 s** 尝试打包；这两个数都是上限，不是预计耗时。
- 每个唯一运行每次调用最多尝试 3 次；保留原 RunConfig 的单次墙钟、步数和物理时间上限。
- 测试预算 3600 s，普通比较/后处理单项预算 1200 s，事件单项预算 3600 s，事件最多 8 层，报告闭环最多 3 轮。
- 时间比较默认最多 200000 点、6 层中点加密。达到上限保留未解析状态，不放松误差阈值。

二维细网格与严格误差比较可能显著增加计算量；没有服务器实测，不能承诺 48 h 内全部完成，也不能把 GPU 标签当作加速证据。预算中止后用同一版本 `--resume` 获得新一轮有限预算。确定性数值/GPU/工程失败需要先诊断；相同配置重复恢复不能替代修复。误差超过规定容限时也不会自动修改已批准模型。

| 退出码/状态 | 含义 |
| --- | --- |
| `0 / CAMPAIGN_COMPUTATION_COMPLETE` | 全部主窗口、适用数值验收、条件导出、比较、观察记录与回传包已完成；Stage07 仍未执行 |
| `2 / CAMPAIGN_PARTIAL_OR_UNRESOLVED` | 预算、事件、误差、覆盖或回传包仍未解决；保留已有成果与原因 |
| `1 / CAMPAIGN_FAILED` | 预检、必跑测试、数值/GPU或工程错误；日志和已有检查点保留 |

单项预算耗尽后，在会话预算允许时继续独立任务；全会话到期则收尾。输出目录带操作系统锁，同一目录不能有两个运行者。子进程超时/异常退出时，即使已有部分成功 JSON，也不会据此把当次动作标成成功。

## 结果在哪里

```text
results/full/A26_FULL_001/
  expanded_plan.json             # 完整配置、来源哈希、去重关系、预算
  campaign_state.json            # 状态、尝试历史、依赖与检查点目录
  campaign_summary.json          # 最新汇总、case 状态、候选及回传包路径
  campaign_summary_invocation_001.json
  logs/invocation_001/           # 服务器测试 XML/日志、各主求解日志
  run_configs/                  # 实际生成的完整 RunConfig
  runs/                         # 主轨迹、检查点、环境、指标与观察 CSV
  operations/                   # 预检、摘要、比较等子进程请求和真实输出
  analysis/                     # 每次分析的依赖身份、独立副本、误差/事件/候选
results/full/A26_FULL_001_return_001.zip
```

候选工作簿位于各 case 的独立分析尝试目录，准确路径见 `campaign_summary.json` 的 `case_results`，不会覆盖原始模板。分析缓存同时核验实际文件哈希与前序动作依赖；前序证据重做或 C 参考时间改变时，相关下游证书不会沿用旧缓存。

Q1 须通过早期层在内的三层场误差与独立余额检查才自动生成候选 result1。历史 CPU Q1 的早期表面差尚不合格，不能保证现有 20/40/80 网格会通过。Q23/Q4 必须实际获得严格事件、完整误差与回读检查才导出；Q23 的 result2/result3 共用一条轨迹。C 只形成参考数值证据，不导出正式题目表。没有足够覆盖或误差证据时，返回明确原因，不填造结果。

## 回传与证据边界

优先回传自动生成的 `A26_FULL_001_return_001.zip`，同时保留最新 `campaign_summary.json` 和外部 `server_full_001.log` / resume 日志。ZIP 是打包开始时的数值证据快照，其中打包动作自身可能仍为 RUNNING；最终打包状态以包外最新汇总为准。会话中断后，如自动包生成失败，可以手动打包：

```bash
python -m drying pack-return --runs results/full/A26_FULL_001 --out results/full/A26_FULL_001_manual_return.zip
```

最小包不含 trajectory、checkpoints、source_snapshot 等大文件；完整轨迹保留在服务器，复查时用上述命令加 `--full` 并使用新的 ZIP 名称。Stage07 重算审计需要完整轨迹及当时源码快照，最小包不能替代它们。

自动数值检查、测得 B/C 差和条件候选导出属于 **Stage06 证据收集**。比较的 `resolved=true` 只表示比较过程完成，不表示一维假设成立或物理模型通过验证。Stage07/08 为 `NOT_RUN`，最佳已验证模型为 `null`，模型未冻结；是否进入下一阶段仍由人工决定。
