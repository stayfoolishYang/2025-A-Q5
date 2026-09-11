#!/usr/bin/env python3
"""Manage a running Jammers service without opening a browser."""
import argparse
import json
import os
from pathlib import Path

from access import read_token
from client import APIError, ControlClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("JAMMERS_CONTROL_URL", "http://127.0.0.1:2027"))
    parser.add_argument("--token-file", type=Path, default=os.environ.get("JAMMERS_TOKEN_FILE"))
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "health", "history", "abort", "new-batch"):
        sub.add_parser(name)
    start = sub.add_parser("start", help="开始一次本地演练或本地评测")
    start.add_argument("--problem", type=int, choices=(3, 4))
    start.add_argument("--robot-id", default="offline-bot")
    start.add_argument("--mode", choices=("practice", "formal"), default="practice")
    start.add_argument("--wait", type=float, default=15, help="等待接口开放的最长秒数；0 表示不等待")
    choice = start.add_mutually_exclusive_group()
    choice.add_argument("--seed-hex")
    choice.add_argument("--seed")
    choice.add_argument("--scenario", type=Path)
    generate = sub.add_parser("generate", help="生成可导入的场景 JSON")
    generate.add_argument("--problem", type=int, choices=(3, 4), default=3)
    choice = generate.add_mutually_exclusive_group()
    choice.add_argument("--seed-hex")
    choice.add_argument("--seed")
    generate.add_argument("--format", choices=("offline", "native"), default="offline")
    generate.add_argument("--output", type=Path)
    export = sub.add_parser("export", help="导出已结束一局的记录")
    export.add_argument("--run-id", required=True)
    export.add_argument("--kind", choices=("package", "events", "summary", "scenario"), default="package")
    export.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        client = ControlClient(args.url, read_token(args.token_file))
        if args.command == "start":
            data = {"robot_id": args.robot_id, "mode": args.mode}
            if args.mode == "formal":
                data["confirmed"] = True
            if args.scenario:
                data["scenario"] = json.loads(args.scenario.read_text(encoding="utf-8"))
                if args.problem is None and isinstance(data["scenario"], dict):
                    data["problem"] = data["scenario"].get("problem_no", data["scenario"].get("problem", 3))
            if args.problem is not None:
                data["problem"] = args.problem
            for key in ("seed", "seed_hex"):
                if getattr(args, key) is not None:
                    data[key] = getattr(args, key)
            result = client.start(wait=args.wait, **data)
        elif args.command == "generate":
            data = {"problem": args.problem, "format": args.format}
            for key in ("seed", "seed_hex"):
                if getattr(args, key) is not None:
                    data[key] = getattr(args, key)
            result = client.call("/api/generate", data)
            if args.output:
                args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                result = {"saved": str(args.output.resolve())}
        elif args.command == "export":
            import re
            if not re.fullmatch(r"[A-Za-z0-9_-]+", args.run_id):
                raise ValueError("run-id 格式不正确")
            body = client.call(f"/api/runs/{args.run_id}/{args.kind}", raw=True)
            args.output.write_bytes(body)
            result = {"saved": str(args.output.resolve()), "bytes": len(body)}
        else:
            path, body = {"status": ("/api/status", None), "health": ("/healthz", None),
                          "history": ("/api/history", None), "abort": ("/api/abort", {"confirmed": True}),
                          "new-batch": ("/api/new-batch", {"confirmed": True})}[args.command]
            result = client.call(path, body)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, RuntimeError, APIError) as error:
        parser.exit(1, f"调用失败：{error}\n")


if __name__ == "__main__":
    main()
