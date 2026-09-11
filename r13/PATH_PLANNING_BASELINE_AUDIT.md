# R12路径与外层调度源码审计

研究基线为r13/baseline/q4better，98文件与远端7228633一致。用户说明中的I盘B_solver不是当前R12入口；不能在那里继续改旧策略。当前工作树从a93712b建立，q4better源码单独冻结。未找到Q4_当前路径规划方案总结.md，不假定其内容与源码一致。

|条目|真实源码与行为|
|---|---|
|节点|geometry.py:393 coverage；certified25为19个三角格节点+6外围节点，970/1870米固定|
|route|geometry.py:409；固定起点，NN后至多3轮2-opt，允许反转至终点，不回起点|
|NN平局|按传入节点当前序列稳定取min；节点顺序本身属于状态|
|D1|discovery.py:6 refresh_remaining_route；比较旧顺序与重新route，必须至少短1e-8米才替换|
|局部代价|solver.py run；到MEC中心距离/5 + (半径<=19.999时5，否则20+半径/5)|
|探索代价|到nodes[0]距离/5 +(20-len(cleared))*6；是粗代理，当前频道不影响该项|
|外层选择|局部有目标且local<=explore时localize(one_step=True)，否则弹出一个节点扫描|
|扫描顺序|当前频道优先，其余1..20递增；跳过已清频道；R12使用legacy而非unknown_first|
|动作计时|本地engine与public_max37_benchmark整数微秒账本：距离/5；measure=5；测量换频道=1；clear成功5/失败3；clear不改变当前测量频道|
|confirmed16|合法direction/near或成功clear调用confirm_channel；16时记录known16_trigger；同一节点扫描可中断|
|释放|release_discovery直接nodes.clear；循环起点、localize结束、扫描结束和最终退出前调用；不是在confirm_channel内立即清空|
|cleared16|public_max_complete检验成功频道=16且无矛盾tracks；终止任务|
|主动定位|solver.localize先MEC，后失败阈值/diagnostic/fallback，否则Hypotheses.next；重复测点<0.1米改为中心+[25,25]|
|one_step例外|仅普通主动测量执行一次后返回；diagnostic可能多步，光学兜底可连续多次clear；不能一概称为单动作|
|diagnostic|directional/diagnostic_recovery.py recover/choose；最多3步，粒子规划截取最多1024；与optical fallback估价比较|
|fallback|ordered_grid与grid_v1冻结，不修改；清除按既有轨迹进行|
|重规划时机|初始route一次；每次localize返回且还有节点时D1；完整节点扫描之后没有D1|
|状态复用|节点顺序、当前位置、当前频道、cleared/confirmed、tracks硬域、views/history、粒子及RNG均已在内存；现有普通D1日志不保存路线快照，需严格回放捕获|

真实调用链：enter → route(25点,当前位置) → release检查 → 计算local/explore代理 → localize或扫描节点 → 更新位置/频道/硬域/粒子/confirmed/cleared → localize分支可D1刷新 → 下一决策 → exit。

## 对R13设计的影响
B不能把非认证localize的结束点总当MEC中心：普通测量是Hypotheses.next，diagnostic/fallback甚至是多动作。未确定结束位置时不虚构。
C不能统一按每节点6秒计算：测量当前频道只5秒，clear也不改变测量频道；必须模拟既有顺序。
D不能把remaining mandatory在满16后继续强制执行；只作可选支持。当前R12丢弃这些节点的事实不证明这是16个退步的原因。
E需要定义尾部估价和计算门槛，不能把未验证proxy说成实际剩余时间。规划开销不包含首次JIT编译，另行报告冷启动。

本审计只读，算法变更0，官方调用0。完整状态级结果另见后续回放和gap审计。
