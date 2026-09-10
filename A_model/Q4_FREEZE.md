# Q4冻结版 q4-material-mean-v1

冻结日期：2026-09-10。推荐烘干时长 **51.0912847222 h = 183928.625 s**。本版将Q4主模型切换为材料坐标，使用后4 h末小时均值平台；Q1—Q3保持原计算和Excel。

## 冻结条件

- ξ=r/R(t)，按附件2半径、固定长度、均匀径向材料收缩，固体速度v与网格速度w一致；热量和水分方程都取消相对网格输运，保留当前R²扩散尺度及表面交换。
- 质量方程s(t)=s₀(R₀/R)²保持干固体总量；附录4的ρ作为热方程有效经验系数，不将ρ/(1+C)同时解释为守恒干密度。D、cp、k及ρ原经验公式、hm=8e-7 m/s、hT=25 W/(m²·K)保持。
- 前4 h用原数据PCHIP；后4 h推荐49.99893442622951°C、0.04998754098360656 kg/kg，即3—4 h含两端61点均值。保留末值和50°C/0.05名义平台。这是后期边界延续假设；Robin条件保留有效经验驱动力解释。
- 81节点、BE、dt=0.5 s、Picard容差1e-7°C和1e-9 kg/kg。max(C)≤0.15时二分定位。输出每60 s及终点，共3066个数据行；另有1行表头。最后max(C)=0.1499999894372128，四位小数显示0.1500。

## 三个边界情景与消融

| 计算 | 时长 h |
|---|---:|
| 材料坐标，均值平台（主结果） | 51.0912847222 |
| 材料坐标，末值平台 | 50.8234722222 |
| 材料坐标，名义平台 | 51.0898611111 |
| 固定半径，均值平台 | 129.8561458333 |
| 原Eulerian，均值平台 | 52.6548437500 |

消融只比较相同平台、附录4物性、81节点与0.5 s，不沿用旧末值平台129.10/52.38 h作为新平台对照。dt=1 s材料均值结果51.0916145833 h，与主结果差1.1875 s；41节点、dt=0.5 s为51.0984722222 h，与81节点差25.875 s。

## 文件与验证

主交付为[结果Excel](results/result4.xlsx)、[表6](results/table6.csv)、[Q4消融表](results/q4_ablation.csv)、[主图PNG](results/figures/q4_drying.png)/[SVG](results/figures/q4_drying.svg)、[当前报告](results/求解报告.md)。三情景及消融完整轨迹在results/q4_scenarios/。

重新打开Excel逐单元格核对47,372个数值，检查60 s序列、最终事件、药材外部空白掩码与表面列；全部通过。数值残差审查使用材料积分而非旧几何积分。主图与导出预览已检查。

[冻结清单](results/q4_freeze_manifest.json)记录本版源代码、输入、完整轨迹与交付文件的SHA-256。二进制按原始字节，文本统一LF换行后哈希，避免Windows/Git换行转换影响校验。清单不对自身求哈希；由Git提交和标签固定清单内容。未来修改应生成新版本号，不移动本标签。

```powershell
# 重算会改动当前工作副本；请在新版本中执行
& 'D:/Anaconda3/envs/torchgpu/python.exe' A_model/experiments/q4_release.py
& 'D:/Anaconda3/envs/torchgpu/python.exe' A_model/export/prepare_outputs.py
# 用带@oai/artifact-tool的Node运行：A_model/export/workbooks.mjs export 4
& 'D:/Anaconda3/envs/torchgpu/python.exe' A_model/report.py
# 以下仅验证当前冻结文件
& 'D:/Anaconda3/envs/torchgpu/python.exe' A_model/validation/freeze_q4.py
```

旧基线、原Eulerian推导和审计保留在Git历史、audit/及experiments.json；旧收敛/灵敏度图不能作为新版验证。冻结不把经验闭合升级为实验事实，当前没有启动8卡UQ。
