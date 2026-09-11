# 已验证的本机命令

工作目录：`E:\数模\projects\CUMCM2026_B_Q4_OPT`。解释器：`C:\Users\asus\AppData\Local\Programs\Python\Python311\python.exe`。

## 代码与配置

三个JSON兼容YAML配置：

- A：`B_solver/configs/q4_public_max37_A.yaml`
- B：`B_solver/configs/q4_public_max37_B.yaml`
- C：`B_solver/configs/q4_public_max37_C.yaml`

均继承原 `q4_p4_diag_v1_grid_v1_refresh.yaml`。A/B只差`stop_after_public_max_clear`，B/C只差`discovery_coverage`，除用于标识的name外无其他变化。默认Solver仍旧，配置仅允许Q4/P4。

## 本轮实际执行

```powershell
Set-Location 'E:\数模\projects\CUMCM2026_B_Q4_OPT'
$env:JAMMERS_SIM_ROOT = 'D:\桌面\2026国赛\b模拟器\Jammers-Offline-Windows'
python -m unittest discover -s B_solver/tests -p 'test_*.py'
python B_solver/check_coverage37.py --sim-root $env:JAMMERS_SIM_ROOT --output B_solver/results/public_max37/geometry.json

python B_solver/public_max37_benchmark.py --sim-root $env:JAMMERS_SIM_ROOT --output B_solver/results/public_max37/frozen --freeze
python B_solver/public_max37_benchmark.py --sim-root $env:JAMMERS_SIM_ROOT --output B_solver/results/public_max37/frozen --cohort development --workers 4
python B_solver/public_max37_benchmark.py --sim-root $env:JAMMERS_SIM_ROOT --output B_solver/results/public_max37/frozen --cohort evaluation --workers 4
python B_solver/public_max37_benchmark.py --sim-root $env:JAMMERS_SIM_ROOT --output B_solver/results/public_max37/frozen --cohort stress --workers 2
```

这些目录已有证据，`--freeze`拒绝覆盖已冻结的manifest；单局也拒绝覆盖已完成或失败记录。重新做完整复现实验请使用新的输出目录，例如`B_solver/results/public_max37/reproduction01`，不要删旧结果。断点续跑可加`--resume`，会保留已有结果；源哈希发生变化则拒绝混跑。只重新汇总可用`--report --cohort evaluation`。

测试中的原`test_diagnostic`需要版本库已有的`B_solver/results/batch_v2/cases.csv`。该原始fixture已在本机恢复；复制最小源码包时应从同一基线仓库取得该fixture，不能自行伪造预期值。

## 指定离线HTTP服务

在独立终端启动（实际执行过，服务已在本轮结束后停止）：

```powershell
python 'D:\桌面\2026国赛\b模拟器\Jammers-Offline-Windows\start.py' --robot-port 32026 --control-port 32027 --data-dir 'E:\数模\projects\CUMCM2026_B_Q4_OPT\B_solver\results\public_max37\http_service' --countdown 0 --no-browser
```

0秒仅取消建局前倒计时，未更改引擎计时、检测、噪声或物理规则。每局measure的5秒仍为虚拟累计，没有现实sleep(5)。

核对刚启动服务的PID后运行集成脚本；本轮PID为28828，重启后应重新查询，不能复用旧PID：

```powershell
Get-NetTCPConnection -State Listen -LocalPort 32027 | Select-Object LocalPort,OwningProcess
Get-CimInstance Win32_Process -Filter "name='python.exe'" | Where-Object { $_.CommandLine -like '*Jammers-Offline-Windows*start.py*' } | Select-Object ProcessId,CommandLine

python B_solver/experiments/http_public_max37.py --sim-root 'D:\桌面\2026国赛\b模拟器\Jammers-Offline-Windows' --output B_solver/results/public_max37/frozen --server-pid 28828 --ids 0 1
```

集成脚本只操作32026/32027并验证对应启动进程；在每一次`/enter`前再次检查robot端口所有者与指定引擎路径。不符合即停止，不连接2026端口，也不结束未知进程。每局串行，三个方案复用同一冻结场景。`/enter`返回的实际剩余现实时间由原Client采用，重试复用原request_id与请求内容。

HTTP目录已保存6次结果，重复执行同一目录会拒绝覆盖。复现HTTP时应先在新输出目录完成开发集，再将`--output`改为该目录。六局的原始wire记录、进程证明与核心一致性检查在`frozen/http/`。

## 直接运行一个候选完整离线案例

下面使用一个全新目录，先冻结后执行C单局；`--single`表示完整场景，不是单个动作：

```powershell
python B_solver/public_max37_benchmark.py --sim-root 'D:\桌面\2026国赛\b模拟器\Jammers-Offline-Windows' --output B_solver/results/public_max37/reproduction01 --freeze
python B_solver/public_max37_benchmark.py --sim-root 'D:\桌面\2026国赛\b模拟器\Jammers-Offline-Windows' --output B_solver/results/public_max37/reproduction01 --single 0 --variant C
```

本轮相同入口的`smoke`目录A/B/C三次已执行验证。新目录示例没有预先执行，避免制造或覆盖运行记录。

## 重新生成报告与精简回传包

```powershell
python B_solver/experiments/package_public_max37.py
```

打包只读冻结结果，核对源码/场景哈希与所有540条核心记录，重建报告、CSV、diff与ZIP，不启动Solver或模拟器。ZIP不包含账户信息、浏览器数据、整个模拟器发行包、A题或论文目录。全部核心轨迹保留在本机实验目录，ZIP选择典型案例及最大退步案例。
