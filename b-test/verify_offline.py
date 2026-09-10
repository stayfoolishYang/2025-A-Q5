"""Run the test suite while denying non-loopback socket operations in this process.

This does not alter any system firewall settings. It observes the Python runtime
used by the tests; it is not an operating-system isolation claim.
"""
import argparse
import json
from pathlib import Path
import platform
import sys
import time
import unittest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    observed = {"loopback_connects": 0, "loopback_binds": 0, "blocked_attempts": []}

    def guard(event, arguments):
        if event not in ("socket.connect", "socket.bind", "socket.getaddrinfo"):
            return
        target = arguments[1] if event != "socket.getaddrinfo" else arguments[0]
        host = target[0] if isinstance(target, tuple) else target
        if host not in ("127.0.0.1", "::1", "localhost"):
            observed["blocked_attempts"].append({"event": event, "host": str(host)})
            raise PermissionError("Offline verification disallows non-loopback socket operations")
        if event == "socket.connect": observed["loopback_connects"] += 1
        if event == "socket.bind": observed["loopback_binds"] += 1

    sys.addaudithook(guard)
    start = time.monotonic()
    tests = unittest.defaultTestLoader.discover(str(Path(__file__).parent / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(tests)
    report = {"timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
              "python": sys.version, "platform": platform.platform(), "tests": result.testsRun,
              "failures": len(result.failures), "errors": len(result.errors),
              "elapsed_s": round(time.monotonic()-start,3),
              "socket_audit": observed,
              "passed": result.wasSuccessful() and not observed["blocked_attempts"],
              "scope": "Independent implementation tests with a Python audit hook. Original EXE and Windows build were not executed."}
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
