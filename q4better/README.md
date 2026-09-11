# q4better — R12（当前保留路线）

当前推荐 **R12：MEC + diagnostic v1 + D1定位后路线刷新 + certified25发现覆盖 + 发现满16源转定位清除 + 清满16源退出**。

F（隔离局部失败计数）和V（接收证书候选）未达到预先采用门槛，已从当前运行代码回退。历史试验保留在 [F×V回传包](results/fv_factorial_20260911_v1/Q4_FV_review.zip)，不作为当前运行入口。Q3和仓库其他目录保持原样。

## 本轮决定的依据

256个新严格混合10—16源场景，每组256/256全清：

|方案|平均秒/源|P95|P99|
|---|---:|---:|---:|
|R12 / S0|546.056|712.257|762.185|
|加F|544.443|712.257|772.917|
|加V|546.735|712.572|762.645|
|加F+V|545.381|712.572|772.695|

F平均仅改善0.295%，联合仅改善0.124%，均不到1%，尾部条件也未通过；V平均更慢。联合有85/256例退步。故保留R12，不宣称它逐例最优。以上是同一冻结集配对值，不与旧37点实验不同场景均值混作改善比例。

## 使用指定离线引擎复现R12

Python3.11和NumPy；不附带完整模拟器。以下只连接本地指定Engine，不启动官方App：

```powershell
python -m pip install -r q4better/requirements.txt
python q4better/run_r12.py --sim-root 'D:\桌面\2026国赛\b模拟器\Jammers-Offline-Windows' --case 50 --output q4better/reproduction_r12_50
```

默认case50，可选50、218、253、288、298、311。每次使用新输出目录。程序核对冻结场景哈希、实际全清、计时/集合审计，并与历史R12完整动作及RNG精确比较。这是历史回放，不计作新独立评估。

通用客户端仍需显式指定 [R12配置](configs/q4_known16_tri25_R12.yaml)。只有已经核对为演练的会话才使用practice入口：

```powershell
python q4better/solver.py --mode practice --problem 4 --policy P4 --config q4better/configs/q4_known16_tri25_R12.yaml --robot-id YOUR_TEAM_ID --output q4better/reproduction_practice/result.json
```

客户端不会启动演练；不要对未知服务或正式测试直接执行此命令。`solver.py --mode local`是旧自建模拟器，不用于上表的原引擎验证成绩。

## 验证与来源

- [R12源文件逐项SHA256](PROVENANCE.json)：核心与F×V实验前归档的34个R12文件逐字节一致。
- [本次发布目录回归检查](PUBLICATION_CHECK.json)：六个指定原引擎案例、完整动作/RNG及单元测试。
- [25点连续覆盖证明](COVERAGE25.md)。MEC<=19.999、粒子16384、diagnostic深度1/最多3步/beam4、光学grid_v1保持。
- [R12上一轮四组结果](results/known16_tri25_factorial_20260911_v1/REPORT.md)。当前目录只保存6个回归案例的完整轨迹；其余原始轨迹在原实验工作区。
- [F×V报告](results/fv_factorial_20260911_v1/REPORT.md)及ZIP：完整CSV、证明、冻结源码、反例、压力几何去重和补测。报告的详细相对文件请从ZIP中打开。

历史37点文件和结果继续保留，但不再是本目录推荐入口。证据均为LOCAL_DEV / FRAMEWORK_INTEGRATION，不自动升级生产Gate或Model Freeze。实际代码指纹而非旧Git提交决定版本。

发布目录测试命令：

```powershell
$env:PYTHONPATH="$PWD/q4better/reporting;D:\桌面\2026国赛\b模拟器\Jammers-Offline-Windows"
python -m unittest discover -s q4better/tests -v
```
