#!/usr/bin/env python3
"""Run Jammers as a Linux service, without a desktop or third-party packages."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import threading

from access import read_token
from server import Manager, create_ui


def main():
    parser = argparse.ArgumentParser(description="Jammers Linux 离线服务版")
    parser.add_argument("--version", action="version", version="Jammers 1.2.0-linux")
    parser.add_argument("--host", default=os.environ.get("JAMMERS_HOST", "127.0.0.1"))
    parser.add_argument("--robot-port", type=int, default=int(os.environ.get("JAMMERS_ROBOT_PORT", "2026")))
    parser.add_argument("--ui-port", "--control-port", dest="ui_port", type=int,
                        default=int(os.environ.get("JAMMERS_CONTROL_PORT", "2027")))
    parser.add_argument("--token-file", type=Path, default=os.environ.get("JAMMERS_TOKEN_FILE"))
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("JAMMERS_DATA_DIR", "./runs")))
    parser.add_argument("--auto-start", action="store_true", help="服务启动后创建一局演练")
    parser.add_argument("--problem", type=int, choices=(3, 4))
    parser.add_argument("--robot-id", default="offline-bot", help="自动开始的演练所用机器人编号")
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--seed-hex", help="原版 32 字节种子，以 64 个十六进制字符表示")
    inputs.add_argument("--seed", help="便利文本种子；先做 SHA-256 再传给还原生成器")
    inputs.add_argument("--scenario", type=Path, help="scenario-v1 或 jammers-offline-v1 明文 JSON")
    parser.add_argument("--countdown", type=float, default=5, help="每局倒计时，0 至 60 秒")
    parser.add_argument("--no-browser", action="store_true", help="兼容旧脚本；本版默认不打开浏览器")
    parser.add_argument("--open-browser", action="store_true", help="可选：在本机打开管理页面")
    args = parser.parse_args()
    if not (1 <= args.robot_port <= 65535 and 1 <= args.ui_port <= 65535) or args.robot_port == args.ui_port:
        parser.error("请选择两个不同的 1 至 65535 端口")
    if not 0 <= args.countdown <= 60:
        parser.error("countdown 必须为 0 至 60 秒")
    if not args.auto_start and any(x is not None for x in (args.seed, args.seed_hex, args.scenario, args.problem)):
        parser.error("启动时指定场景或问题需要 --auto-start；也可启动后使用 jammersctl.py start")
    manager = control = worker = None
    stopped = threading.Event()
    old_handlers = {}
    try:
        token = read_token(args.token_file)
        for sig in (signal.SIGINT, signal.SIGTERM):
            old_handlers[sig] = signal.signal(sig, lambda *_: stopped.set())
        manager = Manager(args.data_dir.resolve(), args.robot_port, args.countdown,
                          host=args.host, access_token=token)
        if manager.port_error:
            raise ValueError(manager.port_error)
        control = create_ui(manager, args.ui_port)
        if args.auto_start:
            data = {"robot_id": args.robot_id}
            if args.scenario:
                data["scenario"] = json.loads(args.scenario.read_text(encoding="utf-8"))
                if args.problem is None and isinstance(data["scenario"], dict):
                    data["problem"] = data["scenario"].get("problem_no", data["scenario"].get("problem", 3))
            if args.problem is not None:
                data["problem"] = args.problem
            if args.seed_hex is not None:
                data["seed_hex"] = args.seed_hex
            elif args.seed is not None:
                data["seed"] = args.seed
            manager.start(data)
        worker = threading.Thread(target=control.serve_forever, kwargs={"poll_interval": .1},
                                  name="jammers-control", daemon=True)
        worker.start()
        print(json.dumps({"event": "service_ready", "version": "1.2.0-linux",
                          "control_bind": f"{manager.host}:{args.ui_port}",
                          "robot_bind": f"{manager.host}:{manager.robot_port}",
                          "generator_version": "practice-gen-v1", "authentication": bool(token),
                          "data_dir": str(args.data_dir.resolve())}, ensure_ascii=False), flush=True)
        if args.open_browser and not args.no_browser:
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{args.ui_port}")
        while not stopped.wait(.2):
            if not worker.is_alive() or not manager.monitor.is_alive():
                raise RuntimeError("服务工作线程已退出")
    except (OSError, ValueError, RuntimeError) as error:
        print(f"启动或运行失败：{error}", file=sys.stderr, flush=True)
        return 1
    finally:
        if control:
            if worker and worker.is_alive():
                control.shutdown()
                worker.join(timeout=2)
            control.server_close()
        if manager:
            manager.close()
        for sig, previous in old_handlers.items():
            signal.signal(sig, previous)
    print(json.dumps({"event": "service_stopped"}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
