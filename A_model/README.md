# 2026 A题：药材烘干

**审计结论：** 同物性严格对照为固定129.1006 h、移动材料坐标50.8235 h、原Eulerian 52.3814 h。后4 h边界仍是延续假设，原几何守恒不能证明干基质量守恒；暂不上8卡UQ。见[审计报告](audit/审计报告.md)和[当前阶段](STATUS.md)。旧Excel保留为条件模型基线。

四问完整求解、有限体积误差验证和CUDA批量对照。入口结果见 [求解报告](results/求解报告.md)、[图表导航](results/index.html)。原仓库2025题保持原状。

## 运行

本机计算解释器：`D:\Anaconda3\envs\torchgpu\python.exe`（Python 3.10、SciPy、Numba、CUDA PyTorch）。原默认Anaconda Python 3.8中的旧Numba与NumPy不兼容，因此没有使用该环境。

```powershell
& 'D:\Anaconda3\envs\torchgpu\python.exe' -X utf8 A_model/tests/test_solver.py
& 'D:\Anaconda3\envs\torchgpu\python.exe' -X utf8 A_model/run.py
& 'D:\Anaconda3\envs\torchgpu\python.exe' -X utf8 A_model/experiments/run_experiments.py
& 'D:\Anaconda3\envs\torchgpu\python.exe' -X utf8 A_model/solver/gpu_batch.py
& 'D:\Anaconda3\envs\torchgpu\python.exe' -X utf8 A_model/export/prepare_outputs.py
& 'C:\Users\13578\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' --max-old-space-size=8192 A_model/export/workbooks.mjs
& 'D:\Anaconda3\envs\torchgpu\python.exe' -X utf8 A_model/report.py
```

跨机器安装数值依赖：`pip install numpy scipy numba matplotlib`。只有GPU实验需要CUDA版PyTorch。电子表格输出使用Codex附带的`@oai/artifact-tool`和Node，A_model/node_modules需链接到该机器的runtime node_modules。已提供原始CSV、模板和完整结果；无需访问原OneDrive路径即可重复求解。重新提取附件使用 `preprocess/prepare.py <A题目录>`，该只读脚本还需openpyxl。

`run.py --n 81 --dt 0.5`为默认主结果。Q1/Q2每1 s输出，Q3/Q4每60 s及最后事件时刻输出。数组文件保留未舍入全精度状态；Excel按题意保留四位小数。Q4的固定物理半径超出当时表面时留空，不外推药材外部浓度；独立末列表面值随R(t)移动，实际半径见q4_radius_output.csv。

`experiments/run_experiments.py`按实验名称恢复已完成任务。修改模型或物性后应将旧experiments.json改名备份，再全量运行，不能把不同模型版本结果混合。本次记录对应最终Kirchhoff面扩散通量、低Peclet中心ALE通量的版本。

## 文件职责

- `physics/material.py`：附录2/3/4、Kirchhoff面扩散求积。
- `physics/boundary.py`：附件PCHIP/线性插值、后4小时平台假设。
- `solver/fvm_cpu.py`：FVM、三对角、Picard、BE/BDF2、ALE、事件定位、几何积分审计。
- `solver/gpu_batch.py`：FP64 PyTorch多样本批量Q3、与CPU同离散全轨迹终态比较。
- `tests/test_solver.py`：SciPy线性求解对照、圆柱解析特征模态、几何常数场、Q1物理与守恒检查。
- `experiments/run_experiments.py`：网格、步长、插值、松弛系数、消融、±20%单参数、24样本LHS。
- `export/`：采样、四位小数、按模板输出四个工作簿。
- `report.py`：题目表1—6、数值报告、SVG/PNG和HTML。

本次采用ponytail原则，将非线性、动域、守恒、事件定位放在同一个短求解器中，避免建立只转发函数的空模块。

## 8卡运行方式

Linux服务器每卡运行一个独立进程，例如卡0：

```bash
CUDA_VISIBLE_DEVICES=0 python A_model/solver/gpu_batch.py --batch 256 --worker 0 --workers 8
```

其余卡分别将两个0替换为1—7。每个worker按样本索引切片，不使用DataParallel；每个结果写入独立gpu_worker_i.json。此实现的GPU路径目前针对Q3固定域，Q4仍使用已验证的CPU ALE求解器。小网格的稠密batched solve便于验证，但不保证GPU比CPU快；本次8样本实测CPU更快。4090/V100与8卡性能未在本地硬件上伪造。

## 模型解释

详见题目分析报告：后4小时边界为假设；Q4采用用户指定的Eulerian扩散方程坐标变换。移动域审计包括边界扫掠项，但不把含水率几何积分称为真实水质量。材料随动坐标另作消融。所有数值结果均为此数学模型下的条件预测。
