# q4better — Q4 已验证优化路线

**MEC + diagnostic v1 + D1定位后路线刷新 + 37点发现覆盖 + 成功清除16个不同频道后退出。**

这是从已验证的冻结源码复制出来的独立目录，不替换仓库原 `B_solver` 默认策略，不改变Q3。两个选项仍需显式开启，推荐组合在 [C配置](configs/q4_public_max37_C.yaml) 中。

## 效果

2026-09-11，指定 Jammers-Offline-Windows 1.2.0 / practice-gen-v1 引擎上的冻结新评估：

| 配置 | 路线 | 全清 | 平均秒/源 | P95秒/源 | P99秒/源 |
|---|---|---:|---:|---:|---:|
| [A](configs/q4_public_max37_A.yaml) | 原D1＋45点 | 128/128 | 855.631 | 1113.109 | 1137.931 |
| [B](configs/q4_public_max37_B.yaml) | D1＋45点＋16源退出 | 128/128 | 845.062 | 1113.109 | 1137.931 |
| [C](configs/q4_public_max37_C.yaml) | D1＋37点＋16源退出 | 128/128 | **730.607** | **948.990** | **974.083** |

C相对A平均节省125.024秒/源，下降14.612%；平均整局省1545.937秒，约25分46秒。完整任务时间包含移动、扫描、定位和清除。

**边界：** 128例中有生成器产生的12个全定向场景，严格混合116例与全定向12例在报告中单列。C相对B有4例退步，最大191.570秒/源；压力集C的P95上升，最大退步204.975秒/源。C通过的是冻结新评估集工程门槛，没有整局逐例不劣或官方分布保证。B的停止优化则通过了逐例时间不增加及动作前缀验证。

历史验证共549次完整运行：主体480、压力60、HTTP6、冒烟3；180个独立物理场景，全部全清。该计数属于原冻结验证，不将本次复制、单元测试或发布检查冒充新增实验。

## 最短运行方式：指定离线引擎

需要Python 3.11和NumPy。模拟器不随本目录发行；使用用户已有的完整离线目录，不连接官方App。

从仓库根目录执行：

```powershell
python -m pip install -r q4better/requirements.txt
$sim = 'D:\桌面\2026国赛\b模拟器\Jammers-Offline-Windows'

# 选择一个未使用的输出目录。冻结不会覆盖旧manifest。
python q4better/public_max37_benchmark.py --sim-root $sim --output q4better/reproduction01 --freeze

# C：一个完整Q4案例；不是单个动作。--single 0复用原确定性场景0。
python q4better/public_max37_benchmark.py --sim-root $sim --output q4better/reproduction01 --single 0 --variant C
```

入口直接调用指定目录的真实Engine。没有用 `solver.py --mode local` 中的自建LocalSimulator替代此次成绩。真实源数和场景参数只用于初始化及事后评价，在线选点和停止依据不读取隐藏场景。

需要复现完整配对实验时，对一个新输出目录先 `--freeze`，再运行：

```powershell
python q4better/public_max37_benchmark.py --sim-root $sim --output q4better/reproduction02 --freeze
python q4better/public_max37_benchmark.py --sim-root $sim --output q4better/reproduction02 --cohort development --workers 4
python q4better/public_max37_benchmark.py --sim-root $sim --output q4better/reproduction02 --cohort evaluation --workers 4
python q4better/public_max37_benchmark.py --sim-root $sim --output q4better/reproduction02 --cohort stress --workers 2
```

重复这些种子是复现，不是新的独立评估集。程序拒绝覆盖已完成或失败的单局，`--resume`保留已有结果。新评估入口检查开发集完整性门禁。

## 检查

```powershell
python -m unittest discover -s q4better/tests -p 'test_public_max*.py'
python q4better/check_coverage37.py --sim-root $sim --output q4better/reproduction_geometry.json
```

停止条件基于 `accepted=true` 且 `clear_result=success` 的不同频道集合，上限16来自题目公开常量。所有清除路径汇入共享clear入口，主循环统一正常user_exit；失败、重复和未决请求不能被当作新的成功。Q3不能开启这两个新选项。

[连续几何证明](COVERAGE37.md)包含56个三角形的显式剖分、面积与非零距离见证；[核验脚本](check_coverage37.py)另检查真实引擎边界。700米发现节点与20米光学兜底网格是不同对象，本路线没有改变后者。

## 结果和来源

- [主报告](results/public_max37/REPORT.md)
- [逐例CSV](results/public_max37/cases.csv)、[配对差CSV](results/public_max37/pairs.csv)
- [精简复核ZIP](results/public_max37/Q4_stop16_cover37_review.zip)：包含冻结场景、源码快照、全部结果行、HTTP证据和典型/退步案例轨迹。
- [原始冻结manifest](results/public_max37/frozen/manifest.json)、[本目录源码来源](PROVENANCE.json)
- [原验证机器命令及HTTP说明](results/public_max37/RUN.md)：其中绝对路径和原PID是历史执行记录；当前目录请使用上面的命令，不复用旧PID。

原验证基础提交为 `7c90ba18c863d7bb99266ad992dbe5d648a46426`。修改后的实际执行源码由冻结SHA256识别。本目录核心源码与该执行快照逐文件字节一致；`PROVENANCE.json`记录映射。其他辅助文件来自经过哈希校验的复核包。完整原始轨迹保存在原实验工作区，本目录不重复上传全部轨迹。

需要HTTP集成时使用 [带进程归属检查的脚本](experiments/http_public_max37.py)，为离线服务选择独立端口并在每次enter前核对实际进程。原验证使用32026/32027；不凭127.0.0.1地址假定服务来自离线模拟器。
