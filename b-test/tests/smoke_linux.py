"""Run real Linux entrypoints, two instances, CLI, SDK, auth, shutdown and restart."""
from __future__ import annotations

import json
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
import io

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from client import APIError, ControlClient, RobotClient


def free_port(used):
    while True:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        if port not in used:
            used.add(port)
            return port


def wait_for(test, process, timeout=6):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            result = test()
            if result:
                return result
        except OSError:
            pass
        if process.poll() is not None:
            raise RuntimeError(f"server exited: {process.returncode}")
        time.sleep(.03)
    raise TimeoutError("service did not reach expected state")


def cli(port, *args, token_file=None):
    command = [sys.executable, str(ROOT / "jammersctl.py"), "--url", f"http://127.0.0.1:{port}"]
    if token_file:
        command += ["--token-file", str(token_file)]
    result = subprocess.run(command + list(args), cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def main():
    used = set()
    rp1, cp1, rp2, cp2 = [free_port(used) for _ in range(4)]
    seed = bytes(range(32)).hex()
    checks = []
    with tempfile.TemporaryDirectory() as tmp:
        temp = Path(tmp)
        token = "smoke-server-token-" + "b" * 32
        token_file = temp / "token"; token_file.write_text(token + "\n"); token_file.chmod(0o600)
        commands = [
            [str(ROOT / "start_linux.sh"), "--robot-port", str(rp1), "--ui-port", str(cp1),
             "--data-dir", str(temp / "first"), "--countdown", "0", "--auto-start",
             "--scenario", str(ROOT / "examples/timing_fixture.json")],
            [sys.executable, str(ROOT / "start.py"), "--robot-port", str(rp2), "--ui-port", str(cp2),
             "--data-dir", str(temp / "second"), "--countdown", "0", "--host", "0.0.0.0",
             "--token-file", str(token_file)],
        ]
        logs = [(temp / f"process-{i}.log").open("w+") for i in range(3)]
        processes = []
        try:
            for i, command in enumerate(commands):
                processes.append(subprocess.Popen(command, cwd=temp, stdout=logs[i], stderr=subprocess.STDOUT))
            first = ControlClient(f"http://127.0.0.1:{cp1}")
            second = ControlClient(f"http://127.0.0.1:{cp2}", token)
            wait_for(lambda: first.status()["port_open"], processes[0])
            wait_for(lambda: second.call("/healthz")["ok"], processes[1])
            checks.append("two_isolated_instances_ready")
            run1 = first.status()["session"]["run_id"]
            demo = subprocess.run([sys.executable, str(ROOT / "demo_robot.py"), "--port", str(rp1)],
                                  cwd=temp, capture_output=True, text=True, timeout=10)
            assert demo.returncode == 0, demo.stdout + demo.stderr
            values = [json.loads(line[line.index("{"):])["virtual_time_s"] for line in demo.stdout.splitlines()]
            assert values == [0, 105, 111, 194, 199, 199], values
            checks.append("documented_timing_via_actual_shell_entrypoint")
            try:
                ControlClient(second.url).status()
                raise AssertionError("anonymous request was accepted")
            except APIError as error:
                assert error.status == 401
            generated = temp / "native.json"
            cli(cp2, "generate", "--problem", "4", "--seed-hex", seed,
                "--format", "native", "--output", str(generated), token_file=token_file)
            assert json.loads(generated.read_text()) == json.loads((ROOT / "tests/fixtures/original_practice_q4.json").read_text())
            checks.append("remote_bind_auth_and_exact_native_generation")
            run2 = cli(cp2, "start", "--scenario", str(generated), "--wait", "3", token_file=token_file)
            robot = RobotClient(f"http://127.0.0.1:{rp2}", token=token)
            robot.enter(); robot.measure(0, 0, 1); robot.clear(0, 0, 1); robot.exit()
            path = temp / "log.zip"
            cli(cp2, "export", "--run-id", run2["run_id"], "--output", str(path), token_file=token_file)
            with zipfile.ZipFile(path) as package:
                assert package.testzip() is None
                assert json.loads(package.read("summary.json"))["accepted_actions"] == 4
                assert json.loads(package.read("scenario.json"))["generator_seed"] == "practice-gen-v1:" + seed
            checks.append("cli_import_sdk_four_actions_and_log_export")
            assert [r["run_id"] for r in first.call("/api/history")["runs"]] == [run1]
            assert [r["run_id"] for r in second.call("/api/history")["runs"]] == [run2["run_id"]]
            checks.append("instance_histories_do_not_mix")
            wait_for(lambda: not first.status()["closing_listener"], processes[0])
            current = cli(cp1, "start", "--problem", "3", "--seed-hex", seed, "--wait", "3")
            RobotClient(f"http://127.0.0.1:{rp1}").enter()
            processes[0].send_signal(signal.SIGTERM)
            assert processes[0].wait(timeout=8) == 0
            saved = json.loads((temp / "first" / current["run_id"] / "summary.json").read_text())
            assert saved["phase"] == "ended" and saved["log_file_name"]
            checks.append("sigterm_finishes_active_run_and_persists_logs")
            command = [sys.executable, str(ROOT / "start.py"), "--robot-port", str(rp1),
                       "--ui-port", str(cp1), "--data-dir", str(temp / "first"), "--countdown", "0"]
            processes.append(subprocess.Popen(command, cwd=temp, stdout=logs[2], stderr=subprocess.STDOUT))
            wait_for(lambda: first.call("/healthz")["ok"], processes[2])
            assert first.status()["session"] is None
            assert len(first.call("/api/history")["runs"]) == 2
            assert first.status()["port_open"] is False
            checks.append("restart_retains_history_and_starts_idle")
            for i in (1, 2):
                processes[i].send_signal(signal.SIGTERM)
                assert processes[i].wait(timeout=8) == 0
            for log in logs:
                log.flush(); log.seek(0)
                content = log.read()
                assert token not in content
                assert "Traceback" not in content, content
            checks.append("all_servers_stop_cleanly_and_do_not_log_token")
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=8)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
            for log in logs:
                log.close()
    report = {"passed": True, "platform": sys.platform, "checks": checks,
              "timing_seconds": values, "listening_address_tested": "0.0.0.0",
              "client_connection_address": "127.0.0.1",
              "official_services_contacted": False,
              "limits": ["No connection from another physical machine was tested.",
                         "Docker and a running systemd user manager were not available."]}
    destination = ROOT / "validation/linux-smoke.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
