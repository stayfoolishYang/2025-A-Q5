# Stage 06 Validation Return Requirements

## 1. Minimum Return Package

GPU修订验收仍NOT_RUN。交回服务器CUDA预检、results/server_tests.xml，以及每次真实运行manifest.json、config.json、environment.json及所有environment_attempt_NNN.json、metrics.json、diagnostics.json、run.log；加上前置检查/测试结果、pipeline_summary、事件扫描、误差分类比较、候选/回读清单。未产生的内容明确写NOT_RUN/UNRESOLVED及原因。

### Execution / Reasoning Metadata

Operating Mode: PERFORMANCE。Primary Model / Reasoning Level: 见06_implementation的实际工具请求与未核实后端说明。Reviewer Used: YES；Reviewer Role: 有界模块/集成复审；Review Status: 已闭环。Task Type: RESULT_ORGANIZATION；Task Complexity: MEDIUM；Decision Risk: HIGH；Routing Source: 当前用户授权与Stage06合同。此文档不执行Stage07。

## 2. Full Diagnostic Return Package

追加trajectory/index.json及其全部npz块、checkpoint.json、checkpoints目录、steps.jsonl、source_snapshot、细化父子来源、恢复保存的旧索引/日志、实际误差对照轨迹。不得仅交四舍五入表或只交成功运行。保留原目录相对关系。

## 3. Route B Required Outputs

Q1需1800s全覆盖、题面指定点、轴心/真实表面早期层及至少20/40/80空间对照。Q23只有一个正式解源，记录3h展示覆盖及全域最大G，不以Cmin、平均值或单个中心点判干。Q4记录R重建、尾部情景、每输出距离域掩码、真实表面及72h输入边界状态。若有严格报告，提供t_hat/tL/tR、五类三级加严、eT/eC/eG/et、η、t+/t-、t_eligible/t_report及未舍入G(t_report)+η；没有合法报告则只交部分轨迹。

## 4. Route P Required Outputs

不适用：KEEP_IN_RESERVE，不要求虚构P结果。启用前必须经过授权上游模型变更。

## 5. Route C Required Outputs

固定/移动C0退化与C1端面交换分开。全程Q23/Q4参考需Nr/Nz、二维场、轴向离差、侧/端面通量、全部边界节点最大值及独立余额；数值误差分别包含径向、轴向、联合网格对照和时间/非线性/dense/event。B/C都满足各自预算后才比较结构差，不用短C1成功代替全程一维合理性判断。

## 6. Failed-Run Return Requirements

记录GPU型号/可见编号、驱动/runtime/CuPy、float64、成功GPU线性求解次数、传输字节和同步计时；GPU_BACKEND_FAILURE禁止CPU自动后备。记录退出码、精确状态、最后接受物理时刻、实际墙钟、拒步/失败原因、最后有效检查点和源身份。WALL_BUDGET_REACHED/STEP_BUDGET_REACHED、INPUT_HORIZON_REACHED、NO_EVENT、EVENT_UNRESOLVED和NUMERICAL_FAILURE分开。不得把终端等待结束当求解失败，也不得把预算停止写成完整干燥。

## 7. Expected File Locations

运行在`results/runs/<run_id>/`；预检为`results/preflight.json`；流水线汇总`results/pipeline_summary.json`；候选在该run下独立候选目录（只有合格时创建）；细化目录由--out指定且不得已存在。minimum/full压缩包由`python -m drying pack-return`生成，详见README_RUN。

## 8. What to Provide to Stage 07

先提供minimum包、preflight、pipeline_summary和顶层运行日志，指出哪些任务实际执行、哪一条作为候选、哪些因预算或输入到期停止。先通过GPU/CPU线性和短时PDE对照，旧CPU记录不算GPU验证。Stage07优先审查Q1早期表面层、真实问题误差收敛、事件时间条件性、同源Q23输出和移动域掩码；再进行C1全程结构/输入敏感性与物理解释。服务器返回数值结果后仍需人工授权Stage07，不自动写PASS或冻结。
