# Q4晨检入口

先看 [离线图表与519例筛选网页](results/recovered/q4_morning_review/index.html)。网页需下载后用浏览器打开；GitHub不直接执行HTML。给GPT审阅可发送 [文字结论](results/recovered/q4_morning_review/README.md) 和 [四例动作审计](results/recovered/q4_morning_review/CASE_NOTES.md)，详细数值在 [配对CSV](results/recovered/q4_morning_review/paired_519.csv)。

Q4同一批519个种子，基线、仅路线、v1各自全部清除。平均虚拟秒/源分别为 **1312.75、963.69、900.17**；v1相对基线省31.43%，相对仅路线省6.59%。P99为 **4526.54、1475.51、1211.35**。

最大收益、最大对基线回退、最大对路线回退、v1最慢分别是seed **366、455、105、283**；已保存三方案共12份原始轨迹。当前主要瓶颈转为发现扫描。网格版本影响和CUDA结果一致性单列，未声称GPU加速。

求解器冻结于 `3c4e844`，完整证据提交为 `a3d94ff`。这是本地还原演练引擎的结构压力集合，不能冒充官方正式测试或iid样本。正式测试启动次数为 **0**。

便携包位于仓库 `交付包/2026B_Q4_晨检对比_519种子_3c4e844.zip`，同目录附SHA256。解压后先打开 `index.html` 或 `README.md`。全2436次原始轨迹继续保存在此前的完整证据包，本晨检包保存主表和四个重点案例。
