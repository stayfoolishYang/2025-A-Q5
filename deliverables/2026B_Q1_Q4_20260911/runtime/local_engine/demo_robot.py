"""Protocol smoke test; does not implement a source-location strategy.

Start a practice run in the UI, then: python demo_robot.py --robot-id offline-bot
"""
import argparse
import http.client
import json
import time
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--robot-id", default="offline-bot")
    parser.add_argument("--port", type=int, default=2026)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--token-file")
    args = parser.parse_args()
    from access import read_token
    token = read_token(args.token_file)
    prefix = uuid.uuid4().hex[:8]

    def post(path, number, position=None, channel=None):
        payload = {"arena_id": "default", "robot_id": args.robot_id, "request_id": f"demo-{prefix}-{number}"}
        if position is not None:
            payload.update(position={"x": position[0], "y": position[1]}, channel=channel)
        body = json.dumps(payload).encode("utf-8")
        for attempt in range(3):
            connection = http.client.HTTPConnection(args.host, args.port, timeout=5)
            try:
                headers = {"Content-Type": "application/json"}
                if token:
                    headers["Authorization"] = "Bearer " + token
                connection.request("POST", path, body, headers)
                response = connection.getresponse()
                data = json.loads(response.read())
                print(path, response.status, json.dumps(data, ensure_ascii=False))
                if response.status != 200 or data.get("accepted") is not True:
                    raise RuntimeError("动作被拒绝；请确认已开始新测试，且 robot_id 一致")
                return data
            except (OSError, http.client.HTTPException):
                if attempt == 2:
                    raise
                time.sleep(.5)  # Retry EXACTLY the same payload and id after transport failure.
            finally:
                connection.close()

    post("/enter", 0)
    post("/measure", 1, (300, 400), 1)
    post("/measure", 2, (300, 400), 2)
    post("/clear", 3, (300, 0), 3)
    post("/measure", 4, (300, 0), 2)
    post("/exit", 5)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError) as error:
        raise SystemExit(f"演练未完成：{error}。请先启动模拟器并等待倒计时结束。")
