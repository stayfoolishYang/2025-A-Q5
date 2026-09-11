"""Small synchronous clients for scripts on the server or a remote private host."""
from __future__ import annotations

import http.client
import json
import time
from urllib.parse import urlsplit
import uuid


class APIError(RuntimeError):
    def __init__(self, status, body):
        self.status, self.body = status, body
        super().__init__(f"HTTP {status}: {body}")


def request(url, path, data=None, *, token=None, control=False, timeout=10, raw=False):
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("URL 应为 http(s)://主机:端口，不应包含账号密码")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("基础 URL 不应包含路径、查询参数或片段")
    connection_type = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    connection = connection_type(parsed.hostname, parsed.port, timeout=timeout)
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    if control:
        headers["X-Jammers-Local"] = "1"
    payload = None
    if data is not None:
        payload = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    try:
        connection.request("GET" if data is None else "POST", path, payload, headers)
        response = connection.getresponse()
        body = response.read()
        if response.status >= 400:
            raise APIError(response.status, body.decode("utf-8", errors="replace"))
        return body if raw else json.loads(body)
    finally:
        connection.close()


class ControlClient:
    def __init__(self, url="http://127.0.0.1:2027", token=None, timeout=10):
        self.url, self.token, self.timeout = url, token, timeout

    def call(self, path, data=None, *, raw=False):
        return request(self.url, path, data, token=self.token, control=True, timeout=self.timeout, raw=raw)

    def status(self):
        return self.call("/api/status")

    def start(self, *, wait=0, **parameters):
        run = self.call("/api/start", parameters)
        if wait:
            return self.wait_ready(run["run_id"], wait)
        return run

    def wait_ready(self, run_id, timeout=15):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            status = self.status()
            session = status.get("session")
            if not session or session["run_id"] != run_id:
                raise RuntimeError("当前会话已改变")
            if session["phase"] == "ended":
                raise RuntimeError("会话在接口开放前已结束：" + str(session.get("end_reason")))
            if status["port_open"]:
                return session
            time.sleep(.05)
        raise TimeoutError("等待机器人接口开放超时")

    def abort(self):
        return self.call("/api/abort", {"confirmed": True})


class RobotClient:
    def __init__(self, url="http://127.0.0.1:2026", robot_id="offline-bot", token=None,
                 timeout=10, retries=2):
        self.url, self.robot_id, self.token = url, robot_id, token
        self.timeout, self.retries = timeout, retries

    def action(self, path, *, request_id=None, position=None, channel=None):
        data = {"arena_id": "default", "robot_id": self.robot_id,
                "request_id": request_id or uuid.uuid4().hex}
        if position is not None:
            data["position"] = {"x": position[0], "y": position[1]}
        if channel is not None:
            data["channel"] = channel
        for attempt in range(self.retries + 1):
            try:
                result = request(self.url, path, data, token=self.token, timeout=self.timeout)
                if not result.get("accepted"):
                    raise APIError(200, result)
                return result
            except (OSError, http.client.HTTPException):
                if attempt == self.retries:
                    raise
                time.sleep(.1 * (attempt + 1))  # Preserve this action's ID and entire body.

    def enter(self, **kwargs):
        return self.action("/enter", **kwargs)

    def measure(self, x, y, channel, **kwargs):
        return self.action("/measure", position=(x, y), channel=channel, **kwargs)

    def clear(self, x, y, channel, **kwargs):
        return self.action("/clear", position=(x, y), channel=channel, **kwargs)

    def exit(self, **kwargs):
        return self.action("/exit", **kwargs)
