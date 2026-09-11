# 论文撰写内部证据大纲

范围：2026 A《药材的烘干问题》Q1–Q4完整中文初稿。用户给定 cumcm.tex 模板；以同一 LaTeX 主稿生成 PDF，随后可转换 Word。此文件供写作核对，不进入论文正文或支撑材料清单。

## 输入与数值口径
- 原题 A_model/data/A题.pdf；数据 A_model/data/；题目分析报告和术语表为早期材料，仅采用与最新物理定义一致的部分。
- 最新结果与假设以 A_model/results/q{1,2,3,4}.json、对应NPZ、results/求解报告.md、physics/material.py、solver/fvm_cpu.py、physics/boundary.py 为准。
- Q3固定半径、附录3物性、末点延续，57.172586805555554 h；Q4附录4物性、规定R(t)、均匀随体径向收缩、独立干密度、末小时均值平台，51.09128472222222 h。不得把两者之差解释为纯收缩效应。
- Q4末点延续50.8234722222 h、名义平台51.0898611111 h只是边界情景，不是置信区间；52.3813888889 h为旧Eulerian末点模型，非主结果。主文如需Eulerian配对用相同均值平台52.65484375 h。

## 拟定结构和落点
1. 摘要（最后写）：热质传递非线性、规定收缩的变量口径；Q1 1800 s 中心33.5764°C/表面36.7861°C，Q2 3 h中心49.8494°C/最大C=1.7662；Q3/Q4时长；Q4网格加密6.5625 s、时间加密1.1875 s、守恒4.667e-14（内部预算不含末次事件二分）；适用条件。证据：六个题目表、q1–q4.json、q4_convergence.csv。
2. 问题重述、分析与假设：四问任务/数据范围；固定长度，径向主传递；附录物性按题号独立采用；C干基kg水/kg干固体；空气边界使用Ceq=Cair经验映射，不误称相对湿度。
3. 数据与符号：附件1共241点0–4h每60s；附件2半径145点0–72h；PCHIP；末小时61点温度均值49.9989344262°C与Ceq=0.049987540984。图boundary、radius与boundary scenarios；来源boundary.py和audit/source_evidence.json。PCHIP引用核验后文献。
4. 固定圆柱热质传递与统一离散：容量rho_eff*cp；温度摄氏/Arrhenius开尔文；中心Neumann、表面Robin；FVM权重v_i=(xi_face_right²-xi_face_left²)/2；D沿线性T/C重构进行8点Gauss正求积（仅等温时严格Kirchhoff差商）；k调和平均；BE/Picard/Thomas，81节点dt0.5s；BDF2为验证。来源solver/fvm_cpu.py与physics/material.py；FVM/变形连续介质方法文献核验后引用。
5. Q1：附录2物性、0–1800s。逐项抄入results/table1.csv、table2.csv；fig:q1-fields来自results/figures/q1_fields；解释热穿透快于水分向中心的影响；只报实际结果。
6. Q2：全程附录3物性，0–3h。table3.csv、table4.csv；fig:q2-fields。与Q1同时间比较必须说明模型物性不同，不视为数值误差。D随T升高增大、随C下降减小的偏导直接由公式导出。
7. Q3：t*=inf{t:max C<=0.15}；先粗步跨越再BE子步二分；table5.csv；fig:q3-drying。终点显示0.1500由四位小数舍入，全精度已达标；附录Excel每60s加终点、固定位置每0.1cm。末点边界仅延续假设。
8. Q4：规定移动边界的随体归一化坐标模型；推导干连续方程及(sC)水质量方程，v=w使相对网格通量为0，sR²恒定，材料坐标不含额外扫掠项；热学有效物性与质量s分开，不声称rho/(1+C)守恒；table6.csv、fig:q4-drying；超出当前半径为空，表面独立输出。rho作为真实湿密度的反例以当前主轨迹重新计算精确比值后再引用。
9. 验证：tests.json的Thomas、常数几何、Robin模态网格收敛、Gauss界面核验、材料预算；fig:q4-convergence 与q4_convergence.csv；场和达标时间精度分开，事件括区不充当总误差。
10. 严格消融与敏感性：q4_ablation.csv，同附录4物性、均值平台固定129.8561458333h/材料51.0912847222h/Eulerian52.65484375h；图ablation和q4_sensitivity；q4_sensitivity.csv完整20%扰动；仅说明D影响最强，不将给定扰动当参数分布。
11. 端面对照：validation/端面验证.md、endface_summary.json/csv，图endface_comparison；二维nr81 nz37 dt15同配对1D都51.1008300781h，在事件定位分辨率内未分辨时差，不等于连续模型无端面误差。4h平均C1.42299055→1.37869807，端面贡献3.9032%；不得将细级2D与dt0.5主值相减作端面误差。
12. 评价与结论：有效模型条件、4h后工艺外推、Ceq映射、规定R与物性质量解释、吸附/潜热信息不足；优势有可检验证据；不作无量化统一误差排序，不夸大未运行8卡UQ。
13. 真实AI使用声明、已核验参考文献。
14. 附录：结果文件与程序清单、求解/验证/导出所需完整可运行源码。剔除机器绝对路径/身份信息和内部流程术语。

## 图表覆盖
拟使用12幅正式图：boundary；radius；q1_fields；q2_fields；q3_drying；q4_drying；q4_boundary；q4_scenarios；convergence；ablation；q4_sensitivity；endface_comparison。从权威NPZ/CSV重新导出适合论文的矢量PDF或>=300dpiPNG，每幅真实题注和正文引用。题目6表必须逐数一致。额外有符号、物性、数值验证、消融、敏感性、端面表。

## 规则与文献
- 2026官方格式：https://www.mcm.edu.cn/html_cn/node/4cd596519c9eb9fbd866398f6df0caa3.html。电子PDF首摘要≤1页，无目录；正文≤30页，不含附录；页边距>=2.5cm；附录源程序和材料列表。
- AI规范：https://www.mcm.edu.cn/html_cn/node/fef94648f2836ab6cc81586f4c38512b.html。声明与另附详情PDF据实写。
- 文献正由独立任务完成双引擎发现与出版社元数据核验；文献仅支持插值、有限体积、材料坐标和干燥模型背景，不为本项目数值提供外部背书。论文结果主张不依赖未核验文献。

验收问题：上述主张能否从指定路径复核？四问是否全部覆盖？是否有误用旧Q4结果、把结构假设当事实或把二分精度当预测精度？文献最终清单另行补齐后才进入正文引用。
