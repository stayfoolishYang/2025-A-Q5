#!/usr/bin/env python3
"""Start a practice session, exercise the four robot APIs, and print its summary.

This is an integration example, not a source-location strategy.
"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from access import read_token
from client import ControlClient, RobotClient


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--control-url", default="http://127.0.0.1:2027")
    ap.add_argument("--robot-url", default="http://127.0.0.1:2026")
    ap.add_argument("--robot-id", default="offline-bot")
    ap.add_argument("--problem", type=int, choices=(3, 4), default=4)
    ap.add_argument("--seed-hex", default=bytes(range(32)).hex())
    ap.add_argument("--token-file")
    args = ap.parse_args()
    token = read_token(args.token_file)
    control = ControlClient(args.control_url, token)
    run = control.start(problem=args.problem, seed_hex=args.seed_hex, robot_id=args.robot_id, wait=15)
    robot = RobotClient(args.robot_url, args.robot_id, token)
    print(json.dumps({"run_id": run["run_id"]}))
    try:
        for path, action in [("enter", robot.enter), ("measure", lambda: robot.measure(300, 400, 1)),
                             ("clear", lambda: robot.clear(300, 400, 1)), ("exit", robot.exit)]:
            result = action()
            print(json.dumps({"action": path, **result}, ensure_ascii=False))
    except Exception:
        control.abort()
        raise
    print(json.dumps(control.call(f'/api/runs/{run["run_id"]}/summary'), ensure_ascii=False))


if __name__ == "__main__":
    main()
