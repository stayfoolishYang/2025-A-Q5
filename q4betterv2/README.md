# q4betterv2：保留B方案

B = 冻结C-TSPN + 原certified25坐标 + 原动态路线刷新。

本目录是独立可运行的离线交付，不替换仓库原q4better。C-TSPN仅优化hard-certified清除落点并执行原下一桥接动作；覆盖点仍为原certified25，保留定位后刷新及发现节点后的动态路由。不启用固定顺序、Coverage优化节点或D方案。

## 运行

使用Python 3.11：

```powershell
python -m pip install -r q4betterv2/requirements.txt
python q4betterv2/run_b.py --scene q4betterv2/example_scene.json --output q4betterv2/run_output.json
```

此入口调用随包离线引擎。输出包含全清结果、时间、距离、完整真实动作与CT宏事件。官方HTTP适配并未在这个新增入口中实现或验证。source保留冻结源码原样，旧实验脚本中的本地路径属于历史复现环境；便携入口使用run_b.py，不直接运行旧ct_benchmark.py。

## 版本与证据

source来自C-TSPN验证时的frozen_source.zip，SOURCE_SHA256.json记录逐文件hash。config_B.json在原R12配置上只启用ctspn_enabled，其他策略保持不变；算法源不修改。

- 新独立128：R12均值550.991469→CT548.967924秒/源，128胜0平0负。
- 另批新独立256：R12均值545.032925→CT543.021026秒/源，256胜0平0负；P95 716.988848→715.019794。原审计曾误报回退事件的下一clear，复核说明保留于validation/AUDIT_256_RECONCILIATION.md；不隐去原审计边界。
- 后续同40例开发选择：B539.644467，D543.473944秒/源，D开发拒绝，故保留B。selection_review仅为选择依据，不包含D运行代码或优化坐标。
- 单次CT计算开销未达到10ms目标。全部为本地离线引擎证据，不等同官方正式测试或生产Model Freeze。

validation中报告引用的历史绝对路径供追溯，所需完整大轨迹未全部重复上传；此目录保留配对表、证明、冻结源码和一个可运行场景。历史TSPN/Coverage辅助模块随源快照保留，但run_b.py明确只实例化CTSolver与config_B，不启用它们。
