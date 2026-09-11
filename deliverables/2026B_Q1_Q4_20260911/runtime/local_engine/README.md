# Jammers Linux 服务版 1.2.0

**可在 Linux 服务器运行，通过 HTTP 或 Python 调用。** 本版把已独立实现的离线仿真核心与已还原、通过对照的原版演练生成器接在一起，默认不打开浏览器。运行仅需 **Python 3.10+ 标准库**，不用安装 pip 依赖、Node.js、Go、Wine 或 Windows EXE。

本版使用 `practice-gen-v1` 生成场景。**正式比赛服务端的生成算法没有还原，包内的“正式”入口仅模拟本地评测流程，场景也由演练生成器产生。** 不连接官方服务，不消费官方正式测试机会。

## 1. 最快运行

解压后进入 `jammers_linux` 目录，在终端 A 执行：

```bash
python3 start.py --data-dir ./runs
```

终端 B 执行：

```bash
python3 jammersctl.py health
python3 jammersctl.py start --problem 4 --seed-hex 000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f
python3 demo_robot.py
python3 jammersctl.py history
```

`start` 默认等到 5 秒倒计时结束、机器人端口开放后返回。`demo_robot.py` 只演示接口，不是定位求解算法。

也可以一条命令完成“建局、调用四个接口、输出结束摘要”：

```bash
python3 examples/run_one.py
```

服务本身要先启动。重复运行前应等上一局端口关闭完成，通常不到一秒；可查看 `/api/status` 的 `closing_listener`。

| 地址 | 用途 |
|---|---|
| `http://127.0.0.1:2027/` | 可选管理网页 |
| `http://127.0.0.1:2027/healthz` | 服务健康检查 |
| `http://127.0.0.1:2027/api/...` | 开始、状态、生成场景和导出等控制接口 |
| `http://127.0.0.1:2026` | 四个机器人动作接口 |

机器人端口保持原有生命周期：**空闲时预留但不监听，倒计时结束后开放，测试结束后关闭。** 持续可访问的是控制端口 2027。控制端口可用不表示机器人已经能 `/enter`。

按 Ctrl+C 或发送 SIGTERM 停止服务，会结束当前局并保存记录。重启保留设置和历史，但不会恢复未完成的机器人会话。

## 2. 从电脑访问 Linux 服务器

默认方式适合“服务和算法都在服务器”或通过 SSH 访问。在电脑上建立转发：

```bash
ssh -N -L 2027:127.0.0.1:2027 -L 2026:127.0.0.1:2026 user@SERVER_IP
```

电脑浏览器打开 `http://127.0.0.1:2027`。电脑上的算法也可继续使用 `http://127.0.0.1:2026`。这条命令中的 `user` 和 `SERVER_IP` 需要换成实际账号、地址；SSH 使用该服务器原有的认证方式。

需要私有网络直接访问时，先生成令牌文件：

```bash
python3 - <<'PY'
from pathlib import Path
import secrets
p = Path('access-token.txt')
with p.open('x', encoding='utf-8') as f:
    f.write(secrets.token_urlsafe(32) + '\n')
p.chmod(0o600)
PY
python3 start.py --host 0.0.0.0 --token-file ./access-token.txt --data-dir ./runs
```

`0.0.0.0` 是监听地址；调用时应使用实际服务器 IP。控制端口和机器人端口都校验令牌。访问同一服务的客户端持有同一个令牌文件后可执行：

```bash
python3 jammersctl.py --url http://SERVER_IP:2027 --token-file ./access-token.txt status
python3 examples/run_one.py --control-url http://SERVER_IP:2027 --robot-url http://SERVER_IP:2026 --token-file ./access-token.txt
```

浏览器会显示 HTTP 登录框：用户名是 `jammers`，密码是令牌文件内容。脚本使用 `Authorization: Bearer <令牌>`。令牌是本服务的共享访问凭据，不是原版授权票据。

本服务内置的是 HTTP；跨公网使用上述 SSH 转发，或放在你已有的 HTTPS 反向代理后。直接监听示例用于受信任的私有网络，访问权限仍取决于服务器防火墙配置。单实例不是多用户权限隔离系统。

## 3. 接入已有算法

已有机器人程序保留以下 POST 路径：

```text
/enter
/measure
/clear
/exit
```

修改基础地址为服务器地址；开启令牌后追加认证请求头。通过 SSH 转发且服务未配置令牌时，原请求格式无需改变。

纯 Python 调用示例：

```python
from client import ControlClient, RobotClient

control = ControlClient('http://127.0.0.1:2027')
run = control.start(
    problem=4,
    seed_hex='000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f',
    robot_id='my-bot',
    wait=15,
)

robot = RobotClient('http://127.0.0.1:2026', robot_id='my-bot')
robot.enter()
result = robot.measure(300, 400, 1)  # x/y 为米，频道为整数
print(result)
robot.clear(300, 400, 1)
robot.exit()
```

开启认证时，两个客户端构造函数都传入 `token=...`。动作客户端在传输失败时重试同一个请求体和同一个 `request_id`，不会为重试重新生成 ID；业务拒绝会直接抛出 `APIError`。需要自己管理 ID 时可给动作方法传入 `request_id='...'`。

进入或退出的 HTTP 请求体：

```json
{"arena_id":"default","robot_id":"my-bot","request_id":"enter-1"}
```

测量或清除的请求体：

```json
{
  "arena_id": "default",
  "robot_id": "my-bot",
  "request_id": "measure-1",
  "position": {"x": 300, "y": 400},
  "channel": 1
}
```

`robot_id` 必须与建局时一致。不同动作使用不同 ID；仅在重试同一动作时复用。正常工作流每局先 `/enter`，最后 `/exit`。

控制接口无需浏览器，例如：

```bash
curl -fsS http://127.0.0.1:2027/api/start \
  -H 'Content-Type: application/json' -H 'X-Jammers-Local: 1' \
  -d '{"mode":"practice","problem":4,"seed":"experiment-1","robot_id":"my-bot"}'
```

这个 HTTP 请求返回的是当前倒计时状态，调用算法前应轮询 `/api/status`，等待 `port_open=true`。控制客户端已封装这一等待。

完整路径及状态语义见 `docs/API.md`。

## 4. 种子和场景

| 输入方式 | 实际处理 |
|---|---|
| `--seed-hex` / `seed_hex` | 直接使用 32 字节原始种子，必须写成 64 个十六进制字符 |
| `--seed` / `seed` | 文本先做 UTF-8 SHA-256，再调用相同生成器；这是本服务的便利输入 |
| 两者都不提供、文本为空 | 本地随机产生 32 字节种子；管理页面配置了固定文本种子时，未指定的演练建局会使用该设置 |
| `--scenario` / `scenario` | 使用已提供的完整明文场景，不再生成 |

**即使文本恰好是 64 个十六进制字符，`--seed` 仍会先哈希。需要与原版同种子对照时必须使用 `--seed-hex`。测试编号不等于原始种子。**

通过服务生成原版结构的 JSON，再导入运行：

```bash
python3 jammersctl.py generate --problem 4 --seed-hex 000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f --format native --output scene.json
python3 jammersctl.py start --scenario scene.json
```

不启动 HTTP 服务也能生成：

```bash
python3 recovered_generator.py --problem 4 --random-seed --format native --output scene.json
```

支持导入 `scenario-v1` 与旧离线版的 `jammers-offline-v1`。原版结构导入时校验规则、整数微米单位、源数量、频道顺序、1770 米位置边界与定向属性；加密场景包不能直接导入。旧离线格式仍允许少量源和 1800 米内位置，用于单项调试，这类自定义数据不等同于正式合法场景。

已知种子的生成结果包含频道、坐标、接收半径、类型、方向与误差场种子。新的默认生成路径允许 Q4 全部源为定向源，并使用 1770 米圆盘；不再使用旧版 Python `random.Random` 场景算法。因此旧版相同文本种子产生的场景会改变；保存的旧场景 JSON 仍可导入。

## 5. 无 HTTP 批量调用与并行实例

单实例同一时刻运行一局，四个机器人动作必须串行提交。需要并行评测时，每个实例设置独立的端口和记录目录：

```bash
python3 start.py --robot-port 3026 --ui-port 3027 --data-dir ./runs-worker1
python3 start.py --robot-port 4026 --ui-port 4027 --data-dir ./runs-worker2
```

分别在不同终端启动，或由你已有的进程管理工具调度。不同进程不能共享同一数据目录；文件锁会阻止这种误用。

如果只做算法批量研究，可在 Python 进程中直接构造独立 `Engine`，见 `examples/in_process.py`：

```bash
python3 examples/in_process.py
```

直接调用核心省去了网络往返，但也不包含 HTTP 幂等缓存、现实时间窗口、会话管理和日志持久化。最终机器人接口验证仍应经过 HTTP 服务。仿真核心在 CPU 上执行，你的求解算法可以自行使用 GPU。

## 6. 后台运行与 Docker

普通 shell 启动（可配合 tmux）已经过实际验证。服务器提供 systemd 用户服务时，可以安装为后台服务：

```bash
sh deploy/install-user-service.sh
systemctl --user status jammers-linux
journalctl --user -u jammers-linux -f
```

脚本将程序安装到 `~/.local/share/jammers-linux`，记录保存到 `~/.local/state/jammers-linux`，默认监听本机。安装前先关闭占用 2026/2027 的手动实例。停止使用 `systemctl --user stop jammers-linux`；更新程序后执行 `systemctl --user restart jammers-linux`。退出 SSH 后是否继续运行取决于服务器的用户服务与 linger 配置。

**systemd 单元已通过语法检查；当前环境没有可运行的用户服务管理器，因此没有实际安装、启动这个单元。**

Docker Compose 可选部署：

```bash
mkdir -m 700 secrets
python3 - <<'PY'
from pathlib import Path
import secrets
p = Path('secrets/token')
with p.open('x', encoding='utf-8') as f:
    f.write(secrets.token_urlsafe(32) + '\n')
p.chmod(0o444)  # 允许容器非 root 用户读取挂载文件；宿主目录仍是 0700。
PY
docker compose up -d --build
docker compose ps
python3 jammersctl.py --token-file secrets/token health
```

首次构建需已有 `python:3.12-slim` 镜像或能拉取该镜像；程序运行期间不需要外网。Compose 将端口发布到宿主机回环地址，适合继续使用 SSH 转发。记录存放于命名卷 `jammers-data`，不要在保留历史时执行删除卷的操作。

**当前环境没有 Docker，Dockerfile/Compose 尚未完成实际构建和启动验证。**

## 7. 日志、演练与本地正式流程

每局在数据目录下保存 `scenario.json`、`events.jsonl`、`summary.json` 和日志 ZIP，SQLite 保存设置、历史和本地评测次数。

```bash
python3 jammersctl.py history
python3 jammersctl.py export --run-id YOUR_RUN_ID --output run.zip
```

把 `YOUR_RUN_ID` 替换成 `start` 或 `history` 返回的编号。演练结束后可以导出场景；本地正式模式的接口和日志包不提供场景真值，但服务器文件所有者仍能读取内部文件。

`jammersctl.py start --mode formal --problem 4` 表示**明确启动一次本地评测**：每机器人、每轮、每题各 3 次，不能指定种子或导入场景；`new-batch` 创建新的本地轮次。这里“formal”只是兼容现有四模块界面，不表示官方正式数据或服务。所有自动验证仅使用本地进程和合成场景。

## 8. 验证范围

本版在 Linux x86-64 / Python 3.12 环境验证：

- 56 项核心、协议、生命周期、模式、认证和生成器接入测试通过。
- 实际 shell/Python 入口、命令行客户端、SDK、两个实例并行、原版 JSON 导入、日志导出、SIGTERM 和重启保留记录通过。
- 附件计时序列复现为 `0 → 105 → 111 → 194 → 199 → 199` 秒。
- 服务生成的一份完整原版结构场景与此前原始生成指令输出逐字段一致；还原生成器文件保持原样。此前 518 个种子、1036 个场景的对照结果见 `docs/generator_comparison.md`。

复跑：

```bash
python3 verify_offline.py --report validation/test-results.json
python3 tests/smoke_linux.py
```

未完成远端服务器实际部署、另一台物理机器的网络连通性验证、Docker 启动、systemd 服务实际启动或网页视觉验收。也未证明完整仿真引擎和原版 Windows EXE 在所有数值边界上完全一致。服务化和演练生成器对齐的结论，不扩展为官方正式比赛场景已复现。
