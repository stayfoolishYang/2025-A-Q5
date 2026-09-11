"""Strict robot request parsing, independent of HTTP transport."""
from __future__ import annotations

import json
import re
import unicodedata

from engine import finite_number

MAX_BODY = 65536
ROUTES = {"/enter", "/measure", "/clear", "/exit"}


class Rejected(Exception):
    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status, self.reason = status, reason


def valid_id(value, size: int) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return 1 <= len(value.encode("utf-8")) <= size and all(
            unicodedata.category(c) not in ("Cc", "Cf", "Cs") for c in value)
    except UnicodeError:
        return False


def check_media(content_type: str, content_encoding: str):
    pattern = r'application/json(?:\s*;\s*charset\s*=\s*(?:utf-8|"utf-8"))?\s*'
    if not re.fullmatch(pattern, content_type.strip(), re.IGNORECASE):
        raise Rejected(415, "unsupported_content_type")
    if content_encoding.strip().lower() not in ("", "identity"):
        raise Rejected(415, "unsupported_content_encoding")


def decode_json(body: bytes):
    if len(body) > MAX_BODY:
        raise Rejected(413, "body_too_large")

    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise ValueError("duplicate key")
            obj[key] = value
        return obj

    def constant(value):
        raise ValueError("non JSON number")

    def depth(value, level=1):
        if isinstance(value, (dict, list)):
            if level > 16:
                raise ValueError("nesting too deep")
            for child in value.values() if isinstance(value, dict) else value:
                depth(child, level + 1)

    try:
        data = json.loads(body.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        if not isinstance(data, dict):
            raise ValueError("object required")
        depth(data)
        # Reject unpaired Unicode surrogates, including in ignored fields.
        json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise Rejected(400, "invalid_json") from None
    return data


def normalize_request(path: str, data: dict) -> dict:
    common = {"arena_id", "robot_id", "request_id"}
    action_fields = {"position", "channel"} if path in ("/measure", "/clear") else set()
    if not common | action_fields <= set(data):
        raise Rejected(400, "missing_field")
    if not isinstance(data["arena_id"], str) or not valid_id(data["robot_id"], 64) or not valid_id(data["request_id"], 128):
        raise Rejected(400, "invalid_identity")
    result = {key: data[key] for key in common}
    unknown = bool(set(data) - common - action_fields)
    if action_fields:
        position, channel = data["position"], data["channel"]
        if not isinstance(position, dict) or not {"x", "y"} <= set(position):
            raise Rejected(400, "invalid_position")
        try:
            x, y = finite_number(position["x"], "x"), finite_number(position["y"], "y")
            numeric_channel = finite_number(channel, "channel", 20)
            if numeric_channel != int(numeric_channel) or numeric_channel < 1:
                raise ValueError("invalid channel")
        except ValueError:
            raise Rejected(400, "invalid_position_or_channel") from None
        result.update(position={"x": x, "y": y}, channel=int(numeric_channel))
        unknown |= bool(set(position) - {"x", "y"})
    if unknown:
        raise Rejected(200, "unknown_field")
    return result


def encode(data: dict) -> bytes:
    return json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def fingerprint(path: str, data: dict) -> str:
    return path + "\n" + json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
