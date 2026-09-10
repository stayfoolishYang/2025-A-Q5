# Linux 控制与机器人 API

控制端口默认 2027，机器人端口默认 2026。两者都可通过 `start.py` 修改。所有 JSON 使用 UTF-8。

开启令牌时，两个端口都支持 `Authorization: Bearer <token>`；网页支持 HTTP Basic（用户名 `jammers`）。未配置令牌时仅允许监听回环地址。未知或缺失认证返回 401。

## 控制端口

POST 控制请求须带 `Content-Type: application/json` 和 `X-Jammers-Local: 1`。如果包含 Origin，其主机必须与 Host 匹配。Python 控制客户端会自动设置必要请求头。

| 方法与路径 | 请求 | 响应或作用 |
|---|---|---|
| GET `/healthz` | 无 | `ok`、`version`，不可用时 503 |
| GET `/api/status` | 无 | 当前会话、端口状态、设置、本地次数 |
| POST `/api/start` | 见下文 | 新建一局，返回会话快照 |
| POST `/api/generate` | `problem`、可选 `seed` 或 `seed_hex`、可选 `format` | 完整场景 JSON |
| POST `/api/abort` | `{"confirmed":true}` | 中止当前局 |
| GET `/api/history` | 无 | 当前机器人历史列表 `runs` |
| POST `/api/configure` | 可选 `robot_id`、`robot_port`、`practice_seed`、`event_limit` | 仅空闲时修改设置 |
| POST `/api/new-batch` | `{"confirmed":true}` | 新建本地评测轮次，历史保留 |
| POST `/api/clear-finished` | `{}` | 清空当前已结束会话的界面状态 |
| GET `/api/runs/{run_id}/summary` | 无 | 已结束或中断局的摘要 |
| GET `/api/runs/{run_id}/events` | 无 | JSONL 动作记录 |
| GET `/api/runs/{run_id}/package` | 无 | 本地日志 ZIP |
| GET `/api/runs/{run_id}/scenario` | 无 | 已结束演练的离线格式场景 |

原始种子演练建局：

```json
{
  "mode": "practice",
  "problem": 4,
  "robot_id": "my-bot",
  "seed_hex": "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
}
```

指定完整场景时，改为 `"scenario": { ... }`，不可同时提供种子。如果省略 problem，可以根据导入场景运行；显式提供时必须一致。CLI 会自动识别文件的问题编号。

生成接口 `format` 可为 `native`（`scenario-v1`）或 `offline`（默认，`jammers-offline-v1`）。文本 `seed` 与原始 `seed_hex` 意义不同，见 README。

本地正式建局使用 `mode="formal"` 和 `confirmed=true`，不接受种子或场景参数。场景来源仍为本地演练生成器，本地次数不对应官方次数。

一个实例只有一个活动会话；启动另一局、修改设置或新建轮次前，须让当前局结束并等待 `closing_listener=false`。开始请求没有动作接口那样的 request_id 幂等缓存；如果建局响应丢失，请先查 status 判断是否已创建，避免盲目重试。

## 机器人端口

原有路径和字段保留：

| 路径 | 必要字段 |
|---|---|
| POST `/enter` | `arena_id`, `robot_id`, `request_id` |
| POST `/measure` | 上述字段加 `position:{x,y}`, `channel` |
| POST `/clear` | 上述字段加 `position:{x,y}`, `channel` |
| POST `/exit` | `arena_id`, `robot_id`, `request_id` |

`arena_id` 为 `default`。坐标单位为米，角度单位为度，虚拟时间单位为秒。每局起点 `(0,0)`，当前测向频道 `1`。

测量反馈由 `measure_result` 区分 `no_signal`、`near`、`direction`，后者附带 `svd_deg`。清除反馈为 `clear_result`。成功响应带 `accepted=true` 与 `virtual_time_s`；不要把 HTTP 200 单独当作动作成功，仍需检查 accepted。

相同 ID、相同规范化请求返回原响应，不重复移动或计时；相同 ID 内容改变返回 409。新的并发动作也可能返回 409。客户端应串行调用，并仅对传输错误重试原请求。

| HTTP 状态 | 含义 |
|---|---|
| 200 + `accepted=true` | 动作接受或幂等回放 |
| 200 + `accepted=false` | 身份、状态或未声明字段等业务拒绝 |
| 400 | JSON 或字段错误 |
| 401 | Linux 服务访问认证失败 |
| 404 / 405 | 路径或方法错误 |
| 409 | 请求 ID 冲突或新动作并发 |
| 413 / 415 | 请求体过大或内容类型不支持 |
| 429 | 每局幂等记录容量达到 100000 |
| 500 | 内部失败 |

空闲时机器人端口不监听，因此此时连接拒绝是预期行为。结束后该端口会关闭，不能保证会话关闭后的最后一个响应仍能通过重试取回；可以通过持续开放的控制端口核对结束状态与日志。

## 直接 Python 核心

`scenario_io.generate_document()` 提供生成，`load_scenario()` 提供导入，`engine.Engine.apply()` 提供动作计算。它们没有网络依赖。`client.ControlClient` 与 `client.RobotClient` 则连接运行中的服务，支持 HTTP 和 HTTPS 地址。

直接核心调用不包含 Session 的计时窗口、ID 缓存、并发拒绝和文件日志，详见 `examples/in_process.py`。
