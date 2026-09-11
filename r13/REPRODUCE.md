# 本地复现与交付使用

先读R13_FINAL_HANDOFF.md。结论KEEP_R12；不要把任何研究模块接到正式接口。本包没有自动启动官方程序的入口。

本研究的数值环境：Windows，D:/Anaconda3/envs/torchgpu/python.exe，8个CPU进程，各数值库1线程。环境精确版本见ENVIRONMENT.json。源代码、全部原生场景、结果JSON、完整轨迹压缩包以及SHA256均已保存。

冻结源码位于r13/baseline/q4better；研究模块在r13顶层。交付包额外包含local_engine下的已核验引擎源码。原机器运行目录为J:/2026B_experiments/q4-r13-routing-study/r13，原引擎位置G:/QQ/jammers_linux。研究批处理直接实例化Engine，不需要启动服务器或客户端。

原结果不可覆盖。若需要同机独立复现，可新建r13/results/replay_development，复制results/development中的manifest.json与scenes目录到这个新目录，**不复制core目录**。然后在研究工作树根目录执行：

```powershell
& 'D:/Anaconda3/envs/torchgpu/python.exe' r13/run_study.py run replay_development --workers 8
```

这样使用原先冻结的128个场景及7个配置，输出到新目录。源指纹变化时程序会拒绝执行；不要删除校验来冒充同版本结果。异机迁移需保留冻结源码、引擎字节、数值版本和字体，并明确记录路径适配与新的运行环境，不能把墙钟差异当算法收益。

查看现有图表无需任何Python环境：打开figures/R13_13张机制与效果图谱.pdf。SVG为可编辑文字，需要本机宋体与Times New Roman。图表统计与布局程序plot_study.py；plot_style.py复用matlab-scientific-plotting的helper，只兼容了Matplotlib3.10的StyleFlags枚举。

统计文件R13_ALL_METHODS_COMPARISON.csv覆盖开发、新验证和历史回归三类，不能混为同一数据集。RESULT_HASHES.json用于校验原始结果；CONFIG_HASHES.json用于校验方案设置；各集合MANIFEST内含执行源码和引擎哈希。每个最大回退案例的完整轨迹位于analysis/failure_mining。

包中的历史state_audit为前阶段519严格回放及13108个静态路线参考审计，不能作为本轮384个新场景的独立证据。旧审计脚本依赖旧档案路径；其保存数据已经随包提供，读CSV即可复查描述性统计。

发布状态见交付根目录DELIVERY_STATE.json：本轮提交在codex/q4-r13-routing-study，未推送远端。I盘主工作树中的其他任务文件没有混入本研究提交。
