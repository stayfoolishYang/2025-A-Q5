# Q4工程条件模型版 q4-material-mean-v2

冻结日期：2026-09-10。推荐烘干时长 **51.0912847222 h = 183928.625 s**。本版将Q4主模型切换为材料坐标，使用后4 h末小时均值平台；Q1—Q3保持原计算和Excel。

版本说明：566390e审计包仍保留原Eulerian主结果；4e1a819/v1已经切换主流水线。本次v2补齐新模型的收敛、敏感性、端面benchmark和防回退检查，主结果未变。不移动v1标签，也不把“冻结”解释为真实物理模型已获实验认证。

## 冻结条件

- ξ=r/R(t)，按附件2半径、固定长度、均匀径向材料收缩，固体速度v与网格速度w一致；热量和水分方程都取消相对网格输运，保留当前R²扩散尺度及表面交换。
- 质量方程s(t)=s₀(R₀/R)²保持干固体总量；附录4的ρ_eff(C)cp(C)作为有效体积热容，不将ρ_eff/(1+C)同时解释为守恒干密度。D、cp、k及ρ原经验公式、hm=8e-7 m/s、hT=25 W/(m²·K)保持。模型名称为“规定移动边界下的随体归一化坐标模型”。
- 前4 h用原数据PCHIP；后4 h推荐49.99893442622951°C、0.04998754098360656 kg/kg，即3—4 h含两端61点均值。保留末值和50°C/0.05名义平台。这是后期边界延续假设；Robin条件保留有效经验驱动力解释。
- Robin条件为−D∂rC=hm(Cs−Ceq)，以Ceq=Cair作为题给边界的有效映射。两种kg/kg的基准物不同，这不是由吸附等温线推导的严格热力学边界。
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

v2重新实算24条当前模型轨迹：dt=1 s的N41/N81/N161分别为51.0988020833/51.0916145833/51.0897916667 h，81→161差6.5625 s；BDF2 dt=1 s为51.0909548611 h，与BE差2.375 s。D/hm/hT/k的±20%扫描全部使用材料坐标、均值平台、N81、dt=1 s，单位倍率共用基准轨迹。数据和图均替换为新模型版本，详见当前报告。

端面影响由[二维轴对称对照](validation/端面验证.md)单独记录。面积比R/L=8%只是初始几何量，不是误差上界；不能给未量化误差作无条件排序。全域最大值、体积平均值及端部剖面须分开评估。

## 文件与验证

主交付为[结果Excel](results/result4.xlsx)、[表6](results/table6.csv)、[Q4消融表](results/q4_ablation.csv)、[主图PNG](results/figures/q4_drying.png)/[SVG](results/figures/q4_drying.svg)、[当前报告](results/求解报告.md)。三情景及消融完整轨迹在results/q4_scenarios/。

重新打开Excel逐单元格核对47,372个数值，检查60 s序列、最终事件、药材外部空白掩码与表面列；全部通过。数值残差审查使用材料积分而非旧几何积分。主图与导出预览已检查。

模型ID仅接受MODEL_Q1=1、MODEL_Q23=2、MODEL_Q4=4；0、3、5、999等非法编号均拒绝。主模型省略ale/tail时，Q4默认为材料/均值。导出和报告先检查model/moving/ale/tail/mode/scales及NPZ终点，Node检查中间payload对应的源文件哈希；Excel另从NPZ独立重建校验，不只与payload互相证明。冻结验证还严格要求N81、BE、dt=.5、PCHIP，纳入新验证文件、轨迹、图及测试。

[冻结清单](results/q4_freeze_manifest.json)记录本版源代码、输入、完整轨迹与交付文件的SHA-256。二进制按原始字节，文本统一LF换行后哈希，避免Windows/Git换行转换影响校验。清单不对自身求哈希；由Git提交和标签固定清单内容。未来修改应生成新版本号，不移动本标签。

```powershell
# 重算会改动当前工作副本；请在新版本中执行
& 'D:/Anaconda3/envs/torchgpu/python.exe' A_model/experiments/q4_release.py
& 'D:/Anaconda3/envs/torchgpu/python.exe' A_model/experiments/run_experiments.py
& 'D:/Anaconda3/envs/torchgpu/python.exe' A_model/export/prepare_outputs.py
# 用带@oai/artifact-tool的Node运行：A_model/export/workbooks.mjs export 4
& 'D:/Anaconda3/envs/torchgpu/python.exe' A_model/report.py
# 以下仅验证当前冻结文件
& 'D:/Anaconda3/envs/torchgpu/python.exe' A_model/validation/freeze_q4.py
```

旧基线、原Eulerian推导和审计保留在Git历史、audit/及experiments.json。旧96组只通过`run_experiments.py --legacy`显式调用；默认入口运行当前Q4验证。历史audit脚本已将旧别名3改为4并显式保留末值情景，历史JSON不修改。冻结不把经验闭合升级为实验事实，当前没有启动8卡UQ。
