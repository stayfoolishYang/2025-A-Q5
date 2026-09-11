# Q1/Q2 题意与文献审计（2026-09-11）

范围：只读仓库题面文本、附件和既有报告，并核验公开作者/出版社文献资料。未调用求解器、模拟器或官方接口。正式测试启动次数 = 0。本笔记不代替其他代理的代码一致性审计。

## 题意与接口定位

以下行号相对 I:/GithubRick/2025-A-Q5/B_solver/。

| 事实 | 题面/附件位置 | 论文应采用的口径 |
|---|---|---|
| 目标源位于半径1800m圆域 | source_text/B题.txt:17–19 | 限制的是源位置；不能据此把机器狗也限制在圆内。附件1.txt:48明确检测点可以超出目标区域。 |
| Q1计算多边形定位区域直径，判断直径圆覆盖 | source_text/B题.txt:21–23 | 必须直接回答覆盖问题，不可仅用MEC清除判据替代。 |
| Q2给出第二检测点选择策略与候选区域 | source_text/B题.txt:24–25 | 原文要求较好的定位效果；没有明文规定必须保证接收。C_safe属于本文主动采用的充分接收限制。 |
| 误差范围±1°；同地点误差固定 | source_text/B题.txt:70–76；附件2.txt:58–65 | 不可假设原地重复检测独立、不可以重复均值缩小硬误差界，不可把有限情景频率写成题面概率。 |
| 示向度保留两位小数并归一化[0,360) | source_text/附件2.txt:63–64、303、313 | 1.005°是冻结实现的保守工程角界。若解释为量化余量，应说明0.005°对应最邻近保留两位小数；附件未明确另列舍入算法。不要把1.005°说成题目原始误差参数。 |
| 有效接收半径每源固定在1000–1500m、接口不返回 | source_text/附件2.txt:44–49 | 1000m是统一保证半径；1500m是收到信号后的距离上界，不能混淆。 |
| 全向：距离不超过有效半径即可检测到信号 | source_text/附件2.txt:50–52 | C_safe保证信号可接收，不能说其等于真实源实际接收区域。基于外包集合再求交亦可能更保守。 |
| ≤5m时near，没有示向度 | source_text/B题.txt:103–104；附件2.txt:66–68、304–313 | 保证接收不等于保证获得第二个bearing；若near应按接口分支处理。正文若评分只预测bearing，必须说明预测简化而不虚构near分支。 |
| 速度5m/s，停止后测量，测量5s（含no_signal） | source_text/B题.txt:93–96；附件2.txt:102–118 | 动作时间是虚拟时间，与计算程序运行时间分开。第二次检测同一频道不额外换频。 |
| 换频1s，仅measure改变测向机频道 | source_text/B题.txt:91–92；附件2.txt:115–118、125 | clear目标频道不改变测向机频道，不应把它计入Q2固定时间。 |
| 光学3s、成功清除再2s，半径20m含边界 | source_text/B题.txt:99–104；附件2.txt:119–125、369–373 | 安全阈值19.999m是本文数值余量；失败clear只用3s，成功共5s另加移动。 |

仅交会角域的交集可能无界；题面全局1800m先验或有效接收距离上界可使本工程硬外包有界。应区分“纯角域交会”与“本题加入先验后的可行域”，不能拿任意巨大初始化方框截断后的有限直径冒充无界集的直径。题面没有要求专门讨论无界，但完整算法需声明有限非空输入条件或异常输出。

Q1的直径圆覆盖条件与MEC并非同一命题。题面未要求清除判据、Jung界，二者是服务后续任务的合理延伸，正文结构须让直径问题先得到明确回答。

## 文献核验

仓库现有解题报告.md:200、202、204列出三篇文献，但2011条目缺页码和DOI。本轮没有修改历史报告。

1. Tokekar, Pratap; Isler, Volkan. Sensor Placement and Selection for Bearing Sensors with Bounded Uncertainty. 2013 IEEE International Conference on Robotics and Automation, pp. 2515–2520. DOI: 10.1109/ICRA.2013.6630920.
   - 作者全文：https://tokekar.com/pubs/tokekar2013asensor.pdf
   - 作者所属大学记录：https://experts.umn.edu/en/publications/sensor-placement-and-selection-for-bearing-sensors-with-bounded-u
   - 已核正文III-A（作者稿第3页）：有界角度噪声、角域交集及可能无界；III-B以面积/直径度量不确定性。引用只支持建模依据；本题有限情景评分没有继承该文连续对抗式最坏情况或三角布点近似比。

2. Tokekar, Pratap; Vander Hook, Joshua; Isler, Volkan. Active Target Localization for Bearing Based Robotic Telemetry. 2011 IEEE/RSJ International Conference on Intelligent Robots and Systems, pp. 488–493. DOI: 10.1109/IROS.2011.6095177.
   - 作者页面及BibTeX：https://tokekar.com/tokekar2011active.html
   - 作者全文：https://tokekar.com/pubs/tokekar2011active.pdf
   - DOI说明：作者页面为6095177；UMN记录另为6048778。只读Crossref查询确认两者均指向同题，6095177的元数据明确页码488–493。采用作者页面的6095177，不将另一个条目误认为不同论文，也不在参考表重复两次。
   - 只用于移动机器人选择测量位置的相关工作；其EKF和具体遥测噪声模型不是本题硬角域的证明。

3. Vander Hook, Joshua; Tokekar, Pratap; Isler, Volkan. Cautious Greedy Strategy for Bearing-only Active Localization: Analysis and Field Experiments. Journal of Field Robotics, 2014, 31(2):296–318. DOI: 10.1002/rob.21499.
   - 作者保存的最终出版社排版全文：https://josh.vanderhook.info/media/pdf/JoshV_JFR_2013_Localization.pdf
   - 另一作者稿：https://tokekar.com/pubs/vanderhook2014cautious.pdf
   - 已核最终版首页/第297页：总时间包含移动与测量；估计为二维Gaussian、后验协方差作为精度。可以支持成本建模动机，不能移植其期望成本近似保证、也不能当成MEC安全清除证书出处。

4. Welzl, Emo. Smallest enclosing disks (balls and ellipsoids). In: Maurer, Hermann (ed.), New Results and New Trends in Computer Science. Lecture Notes in Computer Science, vol.555. Springer, 1991, pp.359–370. DOI: 10.1007/BFb0038202.
   - 出版社：https://link.springer.com/chapter/10.1007/BFb0038202
   - 出版社页面同时出现2005上线时间，但引用块和版权明确1991。不能改成年份2005。摘要支持随机最小包围圆算法背景；实际实现及浮点复核仍以代码为准。

Crossref成功返回的2011、2013原始元数据已保存在同目录crossref_reference_metadata.json。部分后续查询遇到429，未将失败查询当作证据；2014和Welzl由作者最终排版稿和出版社页面核验。

## 待主稿最终复核的措辞

- Q2“保证接收”应为本文候选筛选原则，不能宣称题目逐字强制。
- “可接收全向信号”后补near边界，不写成所有情形都有示向度。
- 数值角界采用代码真实1.005°，误差题面值仍±1°，不引入高斯或均匀概率假设。
- 仅题目原文允许检测点超出1800m源区域；任何代码额外限域都应标明搜索实现限制。
- Q1先回答直径/直径圆，再讨论安全清除与Jung；不要以清除问题替代原问。
- Q1/Q2正文不展开Q4调度、粒子与定向拒收，不把历史演练结果当作本轮新增测试。
