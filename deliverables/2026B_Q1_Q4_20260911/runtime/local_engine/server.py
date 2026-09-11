"""Offline control/UI and robot HTTP services; Python standard library only."""
from __future__ import annotations

import collections
import json
import math
import os
from pathlib import Path
import threading
import time
import uuid
import zipfile
import hashlib
import re
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from engine import Engine, Scenario, generate_scenario, MAX_REAL_S, MAX_VIRTUAL_US, WINDOW_S
from protocol import (MAX_BODY, ROUTES, Rejected, check_media, decode_json, encode,
                      fingerprint, normalize_request, valid_id)
from store import DirectoryLock, RunStore
from access import matches, validate_bind
from scenario_io import generate_document, load_scenario


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != "nt"
    request_queue_size = 32

    def server_bind(self):
        if os.name == "nt":
            import socket
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Session:
    def __init__(self, scenario: Scenario, robot_id: str, root: Path,
                 countdown: float = 5, window_s: float = WINDOW_S, real_s: float = MAX_REAL_S,
                 mode: str = "practice", batch_id: str = "local", event_limit: int = 1000):
        self.cv = threading.Condition(threading.RLock())
        self.engine = Engine(scenario)
        self.robot_id = robot_id
        self.id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
        self.mode, self.batch_id, self.ordinal = mode, batch_id, 0
        self.case_code = f"LOCAL-{'F' if mode == 'formal' else 'P'}{scenario.problem}-{self.id}"
        self.started_at_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.ended_at_utc = None
        self.on_save = None
        self.package_name = ""
        self.package_bytes = 0
        self.directory = root / self.id
        self.directory.mkdir(parents=True)
        (self.directory / "scenario.json").write_bytes(encode(scenario.to_dict()))
        self.logfile = self.directory / "events.jsonl"
        self.phase = "countdown"
        self.countdown_end = time.monotonic() + countdown
        self.window_s, self.real_s = window_s, real_s
        self.opened = self.entered_at = None
        self.cache = {}
        self.cache_limit = 100_000
        self.inflight = None
        self.events = collections.deque(maxlen=event_limit)
        self.trace = collections.deque(maxlen=5000)
        self.trace.append({"x": 0, "y": 0})
        self.total_actions = self.measure_count = self.clear_count = 0
        self.io_error = None
        self._write_status()

    def _log(self, record):
        with self.logfile.open("ab") as stream:
            stream.write(encode(record) + b"\n")
        self.events.append(record)

    def metadata(self):
        info = {"format": "jammers-offline-run-v1.1", "run_id": self.id, "robot_id": self.robot_id,
                "mode": self.mode, "problem": self.engine.scenario.problem, "case_code": self.case_code,
                "batch_id": self.batch_id, "ordinal": self.ordinal,
                "started_at_utc": self.started_at_utc, "ended_at_utc": self.ended_at_utc,
                "phase": self.phase, "end_reason": self.engine.end_reason,
                "virtual_time_s": self.engine.virtual_us / 1_000_000,
                "cleared_channels": sorted(self.engine.cleared),
                "cleared_count": len(self.engine.cleared), "accepted_actions": self.total_actions,
                "measure_count": self.measure_count, "clear_count": self.clear_count,
                "local_only": True, "official_submission": False, "io_error": self.io_error,
                "log_file_name": self.package_name, "log_package_bytes": self.package_bytes}
        if self.mode == "practice" and self.phase == "ended":
            omni = sum(source.kind == "omni" for source in self.engine.sources.values())
            info.update(source_count=len(self.engine.sources), omni_count=omni,
                        directional_count=len(self.engine.sources)-omni)
        return info

    def _write_status(self):
        info = self.metadata()
        target = self.directory / "summary.json"
        temporary = self.directory / "summary.tmp"
        temporary.write_bytes(encode(info))
        temporary.replace(target)
        if self.on_save:
            self.on_save(info)

    def opened_now(self):
        with self.cv:
            if self.phase == "countdown":
                self.opened = time.monotonic()
                self.phase = "ready"
                self._write_status()

    def deadline(self):
        if self.opened is None:
            return None
        end = self.opened + self.window_s
        if self.entered_at is not None:
            end = min(end, self.entered_at + self.real_s)
        return end

    def _end(self, reason):
        if self.phase == "ended":
            return
        self.engine.end(reason)
        self.phase = "ended"
        self.ended_at_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        try:
            self._log({"event": "session_end", "reason": self.engine.end_reason,
                       "real_timestamp_ms": time.time_ns() // 1_000_000,
                       "virtual_time_s": self.engine.virtual_us / 1_000_000})
            self._write_status()
            name = f"{self.case_code}.zip"
            payload = {"summary.json": (self.directory / "summary.json").read_bytes(),
                       "events.jsonl": self.logfile.read_bytes()}
            if self.mode == "practice":
                payload["scenario.json"] = (self.directory / "scenario.json").read_bytes()
            payload["SHA256.json"] = encode({key: hashlib.sha256(value).hexdigest() for key, value in payload.items()})
            with zipfile.ZipFile(self.directory / name, "w", zipfile.ZIP_DEFLATED) as package:
                for filename, content in payload.items():
                    package.writestr(filename, content)
            self.package_name = name
            self.package_bytes = (self.directory / name).stat().st_size
            self._write_status()
        except OSError as error:
            self.io_error = str(error)

    def check_clock(self, now=None):
        with self.cv:
            if self.phase not in ("ready", "running") or self.inflight is not None:
                return
            now = time.monotonic() if now is None else now
            if now >= self.deadline():
                if self.entered_at is not None and self.entered_at + self.real_s < self.opened + self.window_s:
                    reason = "program_timeout"
                else:
                    reason = "window_timeout_running" if self.engine.entered else "window_timeout_before_enter"
                self._end(reason)

    def abort(self):
        with self.cv:
            self._end("manual_abort_running" if self.engine.entered else "manual_abort_before_enter")

    @staticmethod
    def rejection(status, reason):
        # Business rejections have exactly the three fields required by attachment 2.
        return status, encode({"accepted": False, "real_timestamp_ms": time.time_ns() // 1_000_000,
                               "virtual_time_s": 0}), False

    def execute(self, path, request):
        key, mark = request["request_id"], fingerprint(path, request)
        with self.cv:
            if request["arena_id"] != "default" or request["robot_id"] != self.robot_id:
                return self.rejection(200, "identity_mismatch")
            while self.inflight is not None:
                if self.inflight != (key, mark):
                    return self.rejection(409, "concurrent_action_or_request_id_conflict")
                self.cv.wait(timeout=1)
            if key in self.cache:
                saved_mark, saved_bytes = self.cache[key]
                if saved_mark != mark:
                    return self.rejection(409, "request_id_conflict")
                return 200, saved_bytes, False
            self.check_clock()
            if self.phase not in ("ready", "running"):
                return self.rejection(200, "session_not_active")
            if len(self.cache) >= self.cache_limit:
                return self.rejection(429, "local_cache_capacity_reached")
            self.inflight = (key, mark)
            try:
                now = time.monotonic()
                result = self.engine.apply(path, request)
                if not result["accepted"]:
                    self.inflight = None
                    self.cv.notify_all()
                    return self.rejection(200, "action_not_allowed_in_current_state")
                if path == "/enter":
                    self.entered_at, self.phase = now, "running"
                    result.update(max_virtual_duration_s=MAX_VIRTUAL_US // 1_000_000,
                                  max_real_duration_s=MAX_REAL_S,
                                  remaining_real_duration_s=max(0, min(MAX_REAL_S, math.floor(
                                      min(self.real_s, self.opened + self.window_s - now)))))
                    self._write_status()
                result["real_timestamp_ms"] = time.time_ns() // 1_000_000
                body = encode(result)
                self.total_actions += 1
                self.measure_count += path == "/measure"
                self.clear_count += path == "/clear"
                record = {"event": "action", "sequence": self.total_actions, "path": path,
                          "request": request, "response": result,
                          "position": {"x": self.engine.x, "y": self.engine.y},
                          "current_channel": self.engine.channel}
                self._log(record)
                if path in ("/measure", "/clear"):
                    self.trace.append(record["position"])
                self.cache[key] = (mark, body)
                if self.engine.ended:
                    self._end(self.engine.end_reason)
                return 200, body, True
            except Exception as error:
                self.io_error = f"{type(error).__name__}: {error}"
                self._end("internal_failure")
                # The failed action terminates this run; it is never replayed as a fresh action.
                status, body, _ = self.rejection(500, "internal_failure")
                return status, body, True

    def published(self):
        with self.cv:
            self.inflight = None
            self.cv.notify_all()

    def snapshot(self):
        with self.cv:
            self.check_clock()
            now = time.monotonic()
            remaining = max(0, math.ceil(self.deadline() - now)) if self.deadline() and self.phase != "ended" else 0
            info = {**self.metadata(),
                    "countdown": max(0, math.ceil(self.countdown_end - now)),
                    "remaining_real_s": remaining,
                    "virtual_time_s": self.engine.virtual_us / 1_000_000,
                    "position": {"x": self.engine.x, "y": self.engine.y},
                    "current_channel": self.engine.channel, "cleared_count": len(self.engine.cleared),
                    "cleared_channels": sorted(self.engine.cleared),
                    "accepted_actions": self.total_actions, "measure_count": self.measure_count,
                    "clear_count": self.clear_count, "end_reason": self.engine.end_reason,
                    "events": list(self.events), "trace": list(self.trace),
                    "io_error": self.io_error,
                    "counts_available": self.mode == "practice" and self.phase == "ended",
                    "entered": self.engine.entered,
                    "window_remaining_s": max(0, math.ceil(self.opened+self.window_s-now)) if self.opened and self.phase != "ended" else 0,
                    "program_remaining_s": max(0, math.ceil(self.entered_at+self.real_s-now)) if self.entered_at and self.phase != "ended" else 0}
            if self.phase == "ended" and self.mode == "practice":
                info["scenario"] = self.engine.scenario.to_dict()
            return info


class BodyHandler(BaseHTTPRequestHandler):
    def authorize(self):
        token = getattr(self.server, "access_token", None)
        headers = self.headers.get_all("Authorization", [])
        if len(headers) > 1 or not matches(headers[0] if headers else "", token):
            self.reply(401, encode({"error": "authentication_required"}), extra={
                "WWW-Authenticate": 'Basic realm="Jammers Linux", charset="UTF-8"'})
            return False
        return True

    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, fmt, *args):
        pass

    def read_body(self):
        lengths = self.headers.get_all("Content-Length", [])
        encodings = self.headers.get_all("Transfer-Encoding", [])
        if len(lengths) > 1 or len(encodings) > 1 or (lengths and encodings):
            raise Rejected(400, "invalid_body_framing")
        if encodings:
            if encodings[0].strip().lower() != "chunked":
                raise Rejected(400, "unsupported_transfer_encoding")
            data = bytearray()
            while True:
                line = self.rfile.readline(1024)
                if not line.endswith(b"\r\n"):
                    raise Rejected(400, "invalid_chunk")
                try:
                    token = line[:-2].split(b";", 1)[0]
                    if not token or any(c not in b"0123456789abcdefABCDEF" for c in token):
                        raise ValueError()
                    size = int(token, 16)
                except ValueError:
                    raise Rejected(400, "invalid_chunk") from None
                if len(data) + size > MAX_BODY:
                    raise Rejected(413, "body_too_large")
                if size == 0:
                    trailer_size = 0
                    while True:
                        trailer = self.rfile.readline(MAX_BODY + 1)
                        trailer_size += len(trailer)
                        if not trailer.endswith(b"\r\n") or trailer_size > MAX_BODY:
                            raise Rejected(400, "invalid_trailer")
                        if trailer == b"\r\n":
                            return bytes(data)
                chunk = self.rfile.read(size)
                if len(chunk) != size or self.rfile.read(2) != b"\r\n":
                    raise Rejected(400, "invalid_chunk")
                data.extend(chunk)
        try:
            token = lengths[0].strip() if lengths else "0"
            if not token.isascii() or not token.isdigit():
                raise ValueError()
            size = int(token)
        except ValueError:
            raise Rejected(400, "invalid_content_length") from None
        if size > MAX_BODY:
            raise Rejected(413, "body_too_large")
        body = self.rfile.read(size)
        if len(body) != size:
            raise Rejected(400, "incomplete_body")
        return body

    def reply(self, status, body, content_type="application/json; charset=utf-8", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if extra:
            for key, value in extra.items():
                self.send_header(key, value)
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            self.wfile.write(body)
            self.wfile.flush()


class RobotHandler(BodyHandler):
    def send_error(self, code, message=None, explain=None):
        # BaseHTTPRequestHandler also uses this for malformed HTTP and unknown verbs.
        if code == 501:
            code = 405 if self.path in ROUTES else 404
        status, body, _ = Session.rejection(code, message or "http_error")
        self.reply(status, body)

    def do_POST(self):
        if not self.authorize():
            return
        session = self.server.session
        owner = False
        try:
            if self.path not in ROUTES:
                raise Rejected(404, "unknown_path")
            if len(self.headers.get_all("Content-Type", [])) != 1 or len(self.headers.get_all("Content-Encoding", [])) > 1:
                raise Rejected(415, "invalid_media_headers")
            check_media(self.headers.get("Content-Type", ""), self.headers.get("Content-Encoding", ""))
            request = normalize_request(self.path, decode_json(self.read_body()))
            status, body, owner = session.execute(self.path, request)
            self.reply(status, body)
        except Rejected as error:
            status, body, _ = Session.rejection(error.status, error.reason)
            self.reply(status, body)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        finally:
            if owner:
                session.published()

    def wrong_method(self):
        status, body, _ = Session.rejection(405 if self.path in ROUTES else 404, "method_not_allowed")
        self.reply(status, body, extra={"Allow": "POST"} if status == 405 else None)

    do_GET = do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = wrong_method


class Manager:
    def __init__(self, root: Path, robot_port: int | None = None, countdown: float = 5,
                 host="127.0.0.1", access_token=None):
        self.host = validate_bind(host, access_token)
        self.access_token = access_token
        self.root, self.countdown = root, countdown
        self.root.mkdir(parents=True, exist_ok=True)
        self.directory_lock = DirectoryLock(root)
        try:
            self.store = RunStore(root)
        except Exception:
            self.directory_lock.close()
            raise
        self.robot_port = self.store.settings()["robot_port"] if robot_port is None else robot_port
        self.lock = threading.RLock()
        self.session = None
        self.robot_server = None
        self.closing_listener = False
        self.port_error = None
        self.reserved = None
        self._reserve()
        self.stop_event = threading.Event()
        self.monitor = threading.Thread(target=self._monitor, name="local-session-clock", daemon=True)
        self.monitor.start()

    def _bind_reserved(self, port):
        listener = LocalServer((self.host, port), RobotHandler, bind_and_activate=False)
        listener.access_token = self.access_token
        try:
            listener.server_bind()  # Reserve without listening: idle clients still cannot connect.
            return listener
        except OSError:
            listener.server_close()
            raise

    def _reserve(self):
        try:
            self.reserved = self._bind_reserved(self.robot_port)
            self.robot_port = self.reserved.server_address[1]
            self.port_error = None
        except OSError as error:
            self.reserved = None
            self.port_error = f"端口 {self.robot_port} 不可用：{error}"

    def _require_idle(self):
        if self.session and (self.session.phase != "ended" or self.session.inflight is not None):
            raise ValueError("请先结束当前测试")
        if self.robot_server or self.closing_listener:
            raise ValueError("本地接口正在关闭，请稍后重试")

    def start(self, data):
        with self.lock:
            if not isinstance(data, dict) or set(data) - {"robot_id", "mode", "problem", "confirmed", "scenario", "seed", "seed_hex"}:
                raise ValueError("启动参数包含未知字段或不是 JSON 对象")
            self._require_idle()
            settings = self.store.settings()
            robot_id = data.get("robot_id", settings["robot_id"])
            if not valid_id(robot_id, 64):
                raise ValueError("robot_id 必须为 1 至 64 字节且不含控制或格式字符")
            mode, problem = data.get("mode", "practice"), data.get("problem", 3)
            if mode not in ("practice", "formal") or type(problem) is not int or problem not in (3, 4):
                raise ValueError("请选择演练或正式测试，以及问题 3 或问题 4")
            if mode == "formal":
                if data.get("confirmed") is not True:
                    raise ValueError("正式测试需要完成两次确认")
                if "scenario" in data or "seed" in data or "seed_hex" in data:
                    raise ValueError("正式模式不接受自定义场景或指定种子")
                if self.store.attempts(robot_id)[str(problem)]["remaining"] <= 0:
                    raise ValueError("本轮该问题的 3 次离线正式测试机会已用完")
                scenario = Scenario.from_dict(generate_document(problem=problem))
            else:
                if data.get("scenario") is not None:
                    if "seed" in data or "seed_hex" in data:
                        raise ValueError("导入场景时不能同时指定种子")
                    scenario = load_scenario(data["scenario"])
                else:
                    seed_args = ({"seed_hex": data["seed_hex"]} if "seed_hex" in data else
                                 {"seed": data.get("seed", settings["practice_seed"])})
                    if "seed" in data and "seed_hex" in data:
                        raise ValueError("seed 与 seed_hex 只能提供一个")
                    scenario = Scenario.from_dict(generate_document(problem=problem, **seed_args))
                if "problem" in data and scenario.problem != problem:
                    raise ValueError("场景的问题编号与所选演练模块不一致")
            if not self.reserved:
                self._reserve()
            if not self.reserved:
                raise ValueError(self.port_error)
            session = Session(scenario, robot_id, self.root, self.countdown, mode=mode,
                              batch_id=settings["batch_id"], event_limit=settings["event_limit"])
            self.store.register(session)
            session.on_save = self.store.update
            session._write_status()
            self.store.configure({"robot_id": robot_id})
            self.session = session
            return self.session.snapshot()

    def configure(self, data):
        with self.lock:
            self._require_idle()
            if set(data) - {"robot_id", "robot_port", "event_limit", "practice_seed"}:
                raise ValueError("设置包含未知字段")
            values = {**self.store.settings(), "robot_port": self.robot_port, **data}
            if not valid_id(values["robot_id"], 64):
                raise ValueError("机器人编号格式不正确")
            if type(values["robot_port"]) is not int or not 1 <= values["robot_port"] <= 65535:
                raise ValueError("端口应为 1 至 65535 的整数")
            if type(values["event_limit"]) is not int or not 100 <= values["event_limit"] <= 5000:
                raise ValueError("界面事件数量应为 100 至 5000")
            if not isinstance(values["practice_seed"], str) or len(values["practice_seed"]) > 256:
                raise ValueError("演练种子不能超过 256 字符")
            if values["robot_port"] != self.robot_port or not self.reserved:
                new_listener = self._bind_reserved(values["robot_port"])
                if self.reserved:
                    self.reserved.server_close()
                self.reserved, self.robot_port = new_listener, values["robot_port"]
                self.port_error = None
            self.store.configure(data)
            return self.snapshot()

    def new_batch(self):
        with self.lock:
            self._require_idle()
            self.store.configure({"batch_id": uuid.uuid4().hex[:12]})
            return self.snapshot()

    def clear_finished(self):
        with self.lock:
            self._require_idle()
            self.session = None
            return {"ok": True}

    def abort(self):
        with self.lock:
            if self.session:
                self.session.abort()

    def snapshot(self):
        with self.lock:
            settings = self.store.settings()
            run = self.session.snapshot() if self.session else None
            draining = self.closing_listener or bool(self.robot_server and run and run["phase"] == "ended")
            return {"version": "1.2.0-linux", "robot_endpoint": f"http://{self.host}:{self.robot_port}",
                    "generator_version": "practice-gen-v1", "authentication": bool(self.access_token),
                    "formal_scene_source": "local_practice_generator",
                    "port_open": self.robot_server is not None and run["phase"] in ("ready", "running"),
                    "port_error": self.port_error, "port_available": bool(self.reserved or self.robot_server),
                    "closing_listener": draining,
                    "settings": {**settings, "robot_port": self.robot_port},
                    "attempts": self.store.attempts(settings["robot_id"]),
                    "session": run}

    def _monitor(self):
        while not self.stop_event.wait(.05):
            closing = None
            with self.lock:
                session = self.session
                if not session:
                    continue
                session.check_clock()
                if session.phase == "countdown" and time.monotonic() >= session.countdown_end:
                    try:
                        if not self.reserved:
                            raise OSError("预留端口已失效")
                        listener, self.reserved = self.reserved, None
                        listener.server_activate()
                        listener.session = session
                        session.opened_now()
                        self.robot_server = listener
                        threading.Thread(target=listener.serve_forever, kwargs={"poll_interval": .05},
                                         name="local-robot-api", daemon=True).start()
                    except OSError as error:
                        self.port_error = f"端口 {self.robot_port} 无法开放：{error}"
                        session.io_error = self.port_error
                        session._end("internal_failure")
                if session.phase == "ended" and session.inflight is None and self.robot_server:
                    closing, self.robot_server = self.robot_server, None
                    self.closing_listener = True
            if closing:
                closing.shutdown()
                closing.server_close()
                with self.lock:
                    self.closing_listener = False
                    if not self.stop_event.is_set():
                        self._reserve()

    def close(self):
        self.abort()
        self.stop_event.set()
        self.monitor.join(timeout=2)
        with self.lock:
            if self.robot_server:
                self.robot_server.shutdown()
                self.robot_server.server_close()
                self.robot_server = None
            if self.reserved:
                self.reserved.server_close()
                self.reserved = None
            self.store.close()
            self.directory_lock.close()


class UIHandler(BodyHandler):
    def local_host(self):
        if not self.authorize():
            return False
        if len(self.headers.get_all("Host", [])) != 1:
            self.reply(400, encode({"error": "invalid_host_header"}))
            return False
        port = self.server.server_address[1]
        if not self.server.access_token and self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            self.reply(403, encode({"error": "local_host_required"}))
            return False
        return True

    def do_GET(self):
        if not self.local_host():
            return
        manager = self.server.manager
        try:
            if self.path == "/healthz":
                ok = manager.monitor.is_alive() and not manager.port_error
                self.reply(200 if ok else 503, encode({"ok": bool(ok), "version": "1.2.0-linux"}))
            elif self.path == "/api/status":
                self.reply(200, encode(manager.snapshot()))
            elif self.path == "/api/history":
                self.reply(200, encode({"runs": manager.store.history(manager.store.settings()["robot_id"])}))
            elif match := re.fullmatch(r"/api/runs/([A-Za-z0-9_-]+)/(package|events|summary|scenario)", self.path):
                run_id, kind = match.groups()
                info = manager.store.get(run_id)
                if not info or info["robot_id"] != manager.store.settings()["robot_id"]:
                    self.reply(404, encode({"error": "本地记录不存在"}))
                    return
                if info["phase"] not in ("ended", "interrupted"):
                    self.reply(409, encode({"error": "测试结束后可导出"}))
                    return
                if kind == "scenario" and info["mode"] == "formal":
                    self.reply(403, encode({"error": "正式测试不提供场景真值导出"}))
                    return
                name = info.get("log_file_name", "") if kind == "package" else {"events": "events.jsonl", "summary": "summary.json", "scenario": "scenario.json"}[kind]
                if not name:
                    self.reply(404, encode({"error": "本局没有完成打包，可导出已有动作记录"}))
                    return
                body = encode(info) if kind == "summary" else (manager.root / run_id / name).read_bytes()
                self.reply(200, body, "application/zip" if kind == "package" else "application/json; charset=utf-8",
                           extra={"Content-Disposition": f'attachment; filename="{name}"'})
            elif self.path in ("/api/export/scenario", "/api/export/events", "/api/export/summary"):
                with manager.lock:
                    session = manager.session
                    if not session or session.phase != "ended":
                        self.reply(409, encode({"error": "测试结束后可导出完整记录与场景"}))
                        return
                    if self.path.endswith("/scenario") and session.mode == "formal":
                        self.reply(403, encode({"error": "正式测试不提供场景真值导出"}))
                        return
                    name = {"scenario": "scenario.json", "events": "events.jsonl", "summary": "summary.json"}[self.path.rsplit("/", 1)[1]]
                    body = (session.directory / name).read_bytes()
                self.reply(200, body, extra={"Content-Disposition": f'attachment; filename="{session.id}-{name}"'})
            else:
                name = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/style.css": "style.css",
                        "/native.css": "native.css", "/ui-flow.js": "ui-flow.js", "/logo.png": "logo.png"}.get(self.path)
                if not name:
                    self.reply(404, encode({"error": "not_found"}))
                    return
                body = (Path(__file__).parent / "dist" / name).read_bytes()
                mime = "image/png" if name.endswith(".png") else "text/css" if name.endswith(".css") else "text/javascript" if name.endswith(".js") else "text/html"
                self.reply(200, body, mime + "; charset=utf-8", extra={
                    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except OSError as error:
            self.reply(500, encode({"error": str(error)}))

    def do_POST(self):
        if not self.local_host():
            return
        try:
            # UI mutations are same-origin only. Robot API has separate documented semantics.
            origin = self.headers.get("Origin")
            expected_host = self.headers.get("Host", "")
            parsed = urlsplit(origin) if origin else None
            if self.headers.get("X-Jammers-Local") != "1" or (parsed and (
                    parsed.scheme not in ("http", "https") or parsed.netloc != expected_host
                    or parsed.path not in ("", "/") or parsed.query or parsed.fragment)):
                self.reply(403, encode({"error": "local_ui_header_required"}))
                return
            check_media(self.headers.get("Content-Type", ""), self.headers.get("Content-Encoding", ""))
            data = decode_json(self.read_body())
            if not isinstance(data, dict):
                raise ValueError("控制请求必须是 JSON 对象")
            if self.path == "/api/start":
                result = self.server.manager.start(data)
            elif self.path == "/api/abort":
                if data.get("confirmed") is not True:
                    raise ValueError("请完成两次中止确认")
                self.server.manager.abort()
                result = {"ok": True}
            elif self.path == "/api/configure":
                if data.get("robot_port") == self.server.server_address[1]:
                    raise ValueError("机器狗端口不能与界面端口相同")
                result = self.server.manager.configure(data)
            elif self.path == "/api/new-batch":
                if data.get("confirmed") is not True:
                    raise ValueError("请确认创建新的本地评测轮次")
                result = self.server.manager.new_batch()
            elif self.path == "/api/clear-finished":
                result = self.server.manager.clear_finished()
            elif self.path == "/api/generate":
                if set(data) - {"seed", "seed_hex", "problem", "format"}:
                    raise ValueError("生成参数包含未知字段")
                result = generate_document(**data)
            else:
                self.reply(404, encode({"error": "not_found"}))
                return
            self.reply(200, encode(result))
        except Rejected as error:
            self.reply(error.status, encode({"error": error.reason}))
        except (ValueError, TypeError, KeyError) as error:
            self.reply(400, encode({"error": str(error)}))
        except OSError as error:
            self.reply(500, encode({"error": str(error)}))


def create_ui(manager, port=2027):
    server = LocalServer((manager.host, port), UIHandler)
    server.manager = manager
    server.access_token = manager.access_token
    return server
