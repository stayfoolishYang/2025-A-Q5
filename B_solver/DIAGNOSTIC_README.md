# Q4诊断恢复分支

分支：`q4-diagnostic-recovery`。基线提交：`18a53e0`。正式模拟器测试仍被禁止，本轮实验只调用自建LocalSimulator。

## 运行

配置是JSON兼容的YAML，可直接由标准库读取，不需要PyYAML。默认Solver不启用新模块。

```powershell
& 'D:\Anaconda3\envs\torchgpu\python.exe' -m unittest discover -s B_solver/tests -v
& 'D:\Anaconda3\envs\torchgpu\python.exe' B_solver/paired_q4.py --count 20 --workers 4 --configs q4_p4_baseline q4_p4_diag_v1 q4_p4_diag_v2 q4_p4_route_only --output B_solver/results/diagnostic/paired20
& 'D:\Anaconda3\envs\torchgpu\python.exe' B_solver/paired_q4.py --count 100 --workers 4 --configs q4_p4_baseline q4_p4_diag_v1 q4_p4_diag_v2 q4_p4_route_only --output B_solver/results/diagnostic/paired100
& 'D:\Anaconda3\envs\torchgpu\python.exe' B_solver/failure_mining.py B_solver/results/diagnostic/paired100
& 'D:\Anaconda3\envs\torchgpu\python.exe' B_solver/solver.py --problem 4 --device cuda --config B_solver/configs/q4_p4_diag_v2.yaml --output B_solver/results/diagnostic/local_run.json
```

服务器就绪后，在仓库根目录运行：

```bash
python B_solver/paired_multi_gpu.py --gpus 0,1,2,3,4,5,6,7 --start 100 --count 1000 --configs q4_p4_baseline q4_p4_diag_v1 q4_p4_diag_v2 --output B_solver/results/diagnostic/server1000
```

每张卡独占一个独立worker，使用`CUDA_VISIBLE_DEVICES`和连续种子分区。每个worker顺序完成一个种子的所有配置，写独立目录，主进程最后合并。不同worker不共享CSV。该命令不是已经运行的服务器成绩。

## 新增机制

仅在旧策略已经准备进入网格时调用诊断。最长方向和其垂向、当前位置到MEC中心的侧向生成候选，偏移100/200/300/500/700米。历史重复测点被跳过，圆域外位置允许使用。

粒子接收分裂与端点张角/时间先筛选4个候选，再评估信号、无信号及采样带误差示向分支的剩余网格代价。v1深度1，v2深度2；实现支持深度3并有非破坏性测试，但未对深度3开展完整paired实验。深层每个候选只展开权重最高的两个分支，是受限前瞻，不是完整观测树。每次执行一条真实观测后重新规划，最多3次诊断测量。

用于规划的假设最多确定性抽取1024个；这是调度代表集，不删除原始粒子，也不是概率先验。每个信号代表位置采样负误差、零误差、正误差三种示向结果。权重是算法设计权重，采样成本不是严格的期望或最坏情形保证。

只在估计的诊断动作加后续代价低于alpha倍完整网格代价时执行；alpha=1.0。完整网格代价是扫完所有点的代价，不是未知目标被发现的真实期望代价，因此个别案例仍可能变慢。

光学兜底保留旧`optical_grid`的全部点，仅比较两种扫描方向及正反向蛇形路径。原先按距进入点的静态半径排序可能导致跨行反复折返。新增route-only对照用于隔离该变化的贡献。

## 保证不变的理由

覆盖节点及其扫描频道逻辑没有修改；诊断具有有限步上限，因此不会无限占用任务。诊断的真实direction更新仍使用原FP64角域和1500米外切距离约束，无信号不裁剪二维可行多边形。预测分支只操作副本，粒子不能调用clear。真实near及MEC半径不超过19.999米沿用原清除证书。

诊断未成功后仍扫描覆盖整个当前外包集的原网格点集；排序只改变顺序。此为几何保证的保留，不等价于所有可能场景均能在有限官方预算内完成。已有算法的虚拟时间和现实时间预算限制仍须考虑。

## CUDA与数据

CUDA只计算粒子与候选的接收计数，FP32，无BF16/FP8或Ada专用算子。分块粒子数65536，候选块按可用显存选8至32。为避免GPU边界差异漏掉候选，诊断层在CPU FP64复核所有候选的接收计数后再排序；几何一直在CPU。规划代表集较小，不能预设此路径一定获得墙钟加速。

`manifest.json`保存提交、配置、配置对应的源代码哈希、种子、硬件和Torch/CUDA版本；每行结果保存配置哈希。每个案例的详细轨迹都在`traces/`，包括仅供evaluator使用的真实源表。`AuditedSolver`是评估器，在真实观测更新后断言目标仍在外包集内；在线Solver不读取源表。

失败案例仍写入CSV和轨迹，不因失败剔除。`worst10_traces/`保存基线最差10例的各配置压缩轨迹。完整轨迹可归档保存，避免Git逐个纳入大量冗长JSON。
