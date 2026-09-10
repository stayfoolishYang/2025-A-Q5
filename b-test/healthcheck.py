"""Container health probe; accepts the same token-file environment as the server."""
import os
from access import read_token
from client import request

if __name__ == "__main__":
    try:
        result = request("http://127.0.0.1:" + os.environ.get("JAMMERS_CONTROL_PORT", "2027"),
                         "/healthz", token=read_token(os.environ.get("JAMMERS_TOKEN_FILE")), timeout=2)
        raise SystemExit(0 if result.get("ok") else 1)
    except (OSError, ValueError, RuntimeError):
        raise SystemExit(1)
