# NCCP清除点选择：配对复核计划

本计划只改变证书清除点的选择。Q3继续采用当前P3策略，Q4继续采用diagnostic v1；保留原有发现覆盖、定位、诊断恢复、光学兜底和网格版本。是否已准备或运行，以新输出中的`PREPARED.json`、`manifest.json`及后续运行证据为准，不以本文当作执行完成记录。

## 对照与候选

从`B_solver/results/recovered/grid_v1_519/manifest.json`原样复制两份参考配置：

| 题目 | 参考配置名 | 候选配置名 |
| --- | --- | --- |
| Q3 | `P3_current_grid_v1` | `P3_current_grid_v1_nccp` |
| Q4 | `P4_diagnostic_v1_grid_v1` | `P4_diagnostic_v1_grid_v1_nccp` |

参考配置不增加字段、不改值。候选配置只有两处区别：`name`追加`_nccp`，`clearance_point`设为`nccp`。准备脚本检查完整字典及规范JSON哈希，禁止其他配置变化。两方案共享相同场景，运行相同的当前源码快照。参考提交是`3c4e844a010a36d8a441231025e2c1c9d2bc2cce`；“复制参考配置”不等于直接复用旧运行结果。

两份参考配置都要重新执行。开发集中，其逐动作轨迹必须与旧参考结果核对，不能用旧row填入新输出。新候选由Solver中的`clear_certified_polygon`接入，准备脚本不实现或运行求解器。

## 两个队列同时准备，分阶段执行

原始输入与运行结果放在空间充足的J盘：

- `J:/2026B_experiments/nccp_20260911/development100`
- `J:/2026B_experiments/nccp_20260911/holdout256`

准备时必须使用尚不存在的输出根目录；存在即报错，即使为空也不会覆盖。输入准备完整后写入根目录`PREPARED.json`。该文件不表示任何算法运行通过。

开发集和留出集须在查看任何候选结果前一起冻结。随后先运行开发集400例并完成证据、参考轨迹及安全证书审计，再决定是否执行留出集1024例。单题均有两个方案，因此计数是：

| 队列 | 不同种子 | Q3运行 | Q4运行 | 合计 |
| --- | --- | --- | --- | --- |
| development100 | 100 | 200 | 200 | 400 |
| holdout256 | 256 | 512 | 512 | 1024 |

共准备712个原生格式场景，计划1424次运行；场景数、运行数和独立种子数不得混称。

## 开发集100个种子的确定规则

在旧519种子编号中依次构造集合：

1. `range(0, 519, 6)`，共87个等间隔索引。
2. 并入`0..5`以及`105、283、366、455、518`。
3. 并入旧Q3按秒/源从大到小的最差3例；耗时相同时按旧索引从小到大。当前旧证据对应`390、363、351`。
4. 上述并集为98个，再从0开始递增补入尚未选中的旧索引，直到恰100个。当前补入`7、8`。
5. 将最终旧索引升序排列，再分配新队列本地`seed=0..99`。

manifest中每个种子同时保存`source_seed`（旧519索引）、`seed_hex`、原来源族和选入原因。因此新队列的本地`seed`与旧索引不是同一个字段。脚本重新生成开发场景，并要求其规范JSON哈希与旧manifest中的对应场景一致。

这个队列有意包含已知成功、退化和长尾案例，是开发与回归检查集，不是独立验证集。

## 新留出集256个种子

对`i=0..255`，使用以下完整UTF-8文本的SHA-256摘要作为原始32字节种子：

```text
2026B-NCCP-holdout-20260911:{i}
```

`{i}`替换为不带前导零的十进制整数。必须检查256个摘要互不重复，并且与全部旧519个`seed_hex`没有交集；出现冲突直接报错，不悄悄换种子。留出记录的`source_seed=null`，并保存`derivation_index`和来源族`sha256_nccp_holdout`。

两题分别用同一个`seed_hex`调用还原演练生成器，三核心文件必须仍与旧冻结清单一致。准备输入不连接任何服务，不打开官方App，不使用正式模式。

如果看过候选结果后修改算法、配置或选点规则，必须明确开启新实验；继续在本留出集调参后，不能把再次运行称作独立留出验证。源码哈希不一致时，原benchmark会拒绝混入新版本。

## 预算、指标与门禁

- 每例保留1200秒现实预算、360000秒虚拟预算，子进程隔离沿用现有benchmark。
- 建议`2 workers`，每个worker的BLAS线程设为1。J盘存原始轨迹；报告、manifest和summary等小文件最终同步回仓库。
- 优先统计异常、超时、协议拒绝、未全部清除及证书问题。失败记录原样保留，不能用零耗时作为速度胜出。
- 在双方有效全清除的相同场景上比较平均秒/源，同时报告P95、P99、最大值、距离及五阶段耗时。
- 开发集参考方案须与旧参考逐动作一致；留出集没有旧轨迹，应明确标为“不适用”，不能伪造参考对照。
- 只有输入完整性和完成情况通过，不足以自动说明NCCP值得采用；性能差异单独判读。

这些都是还原演练引擎的本地案例，不是官方正式种子。等间隔选样、人工加入的已知长尾以及确定性哈希派生，不应被描述成iid随机样本；不能把1424次运行当作1424个独立样本作失败率推断。

## 冻结记录

两份manifest兼容`recovered_benchmark.py --resume`，记录：

- 连续本地种子编号、原索引或派生索引、完整seed_hex、原生场景哈希。
- 参考与候选配置及其哈希；参考提交、当前Git提交、B_solver准备时工作区状态。
- 旧源码指纹、当前源码指纹及逐文件增删改差异；准备脚本本身的SHA-256。
- `plan_hash`、两队列共享的`shared_seed_plan_hash`、本队列种子哈希、Python/NumPy/BLAS环境和预算。
- 旧数据根路径、参考方案名和参考轨迹文件格式；开发集`source_seed`可以直接定位旧轨迹。

准备开始与输出完成前均检查源码没有变化；全部验证、场景生成先完成，再开始写入新目录。中途失败不会覆盖已有输出；只有存在`PREPARED.json`并且两份manifest都齐全，才具备本计划的输入准备完成证据。

## 执行入口（以下命令是后续操作说明）

核心代码完成、提交之后，准备一次两队列输入：

```powershell
& 'D:/Anaconda3/envs/torchgpu/python.exe' -B B_solver/experiments/prepare_nccp.py --output J:/2026B_experiments/nccp_20260911
```

先执行开发集：

```powershell
& 'D:/Anaconda3/envs/torchgpu/python.exe' -B B_solver/recovered_benchmark.py --sim-root G:/QQ/jammers_linux --output J:/2026B_experiments/nccp_20260911/development100 --resume --problems 3 4 --device cpu --workers 2
```

开发审计通过后，再执行留出集：

```powershell
& 'D:/Anaconda3/envs/torchgpu/python.exe' -B B_solver/recovered_benchmark.py --sim-root G:/QQ/jammers_linux --output J:/2026B_experiments/nccp_20260911/holdout256 --resume --problems 3 4 --device cpu --workers 2
```

准备脚本本身不会调用以上运行命令、启动worker、生成成绩或执行Git写操作。
