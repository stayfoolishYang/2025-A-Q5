# Q3 D / Q4 R12 官方演练接入

已核对官方附件2协议、实际模拟器进程及现有客户端。地址为 `http://127.0.0.1:2026`；队号 `202627002054`；arena_id 为 `default`。截至本轮检查，界面为已结束的Q3演练 KJKC-SR4G-UXRZ-5KY9，本轮没有发出任何机器狗HTTP请求。

新版统一入口：`run_latest_practice.py`。Q3加载 J:/2026B_runs/q3_latest_79766ec/source/q3better 的ActiveFailureSolver、local_order=True及路线刷新；Q4加载 J:/2026B_runs/q4_latest_7228633/source/q4better 的R12配置。两者均CPU，源码指纹与各自519种子复测绑定。旧run_candidate_practice.py是历史入口，不能代表新版D/R12。

## 启动顺序

1. 在官方App的“演练测试”中开启相应问题，等待倒计时结束及“等待机器狗进入”。不进入正式测试。
2. 用computer-use重新读取该窗口的document_text，核对问题、演练、案例编号、队号；将当次原始文本保存为before文件。保持模拟器独占，不在读取后切换会话。
3. 两分钟内运行下方对应命令，将案例编码与before文件换成本次实际值。每次输出使用新案例目录，已有目录拒绝覆盖。

```powershell
& 'D:\Anaconda3\envs\torchgpu\python.exe' 'I:\GithubRick\2025-A-Q5\comparisons\better_20260911\run_latest_practice.py' --problem 3 --case '本次案例编码' --before '本次界面文本.txt'
# Q4使用同一命令，将 --problem 改为4，并使用该Q4案例的编号和界面文本。
```

## 协议与验证边界

- POST /enter 入场；/measure 检测和隐式移动/换频；/clear 移动和清除，不切测向频道；/exit 正常退出。
- 使用当前登录队号、唯一request_id和JSON请求。串行发送；网络重试复用原请求ID和内容。
- /enter会开始本局程序计时，不能用作无副作用的连通性探测；按返回remaining_real_duration_s管理现实截止时间。
- 官方机器人四接口不提供可靠的“本局演练/正式”识别字段。`--mode practice`这个本地参数本身不防止进入正式会话，因此必须在发送前核对真实UI；文本门禁只是防误操作，不能替代实时界面检查或避免核对后切换会话的竞争风险。
- 结果保存到 J:/2026B_runs/official_latest/q问题_案例/，包括manifest、before.txt、wire.jsonl、result.json。异常保存error.json，不自动开启下一场。
- 接口不直接告知源总数。运行结束后需核对官方界面公布的源总数与成功清除的唯一频道数，再确认全清；脚本不会单凭正常退出就宣称全清。

本轮完成接口与源码接入准备，尚未以新版进行官方演练验证。没有修改模型，没有发出/enter、/measure、/clear、/exit，也没有启动正式测试。
