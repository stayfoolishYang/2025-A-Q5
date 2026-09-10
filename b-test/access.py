"""Optional shared token for a private server deployment, without remote dependencies."""
import base64
import binascii
import hmac
import ipaddress
from pathlib import Path


def read_token(path):
    if path is None:
        return None
    token = Path(path).read_text(encoding="utf-8").strip()
    if not 32 <= len(token) <= 512 or not token.isascii() or any(c.isspace() for c in token):
        raise ValueError("token 文件必须包含 32 至 512 个不含空白的 ASCII 字符")
    return token


def validate_bind(host, token):
    host = "127.0.0.1" if host == "localhost" else host
    try:
        address = ipaddress.IPv4Address(host)
    except ipaddress.AddressValueError:
        raise ValueError("host 必须为 IPv4 地址，例如 127.0.0.1 或 0.0.0.0") from None
    if not address.is_loopback and not token:
        raise ValueError("监听非本机地址时必须配置 --token-file；也可使用默认监听配合 SSH 转发")
    return host


def matches(header, token):
    if token is None:
        return True
    try:
        scheme, credential = header.split(" ", 1)
        if scheme.lower() == "bearer":
            supplied = credential.encode("ascii")
        elif scheme.lower() == "basic":
            user, supplied = base64.b64decode(credential, validate=True).split(b":", 1)
            if user != b"jammers":
                return False
        else:
            return False
        return hmac.compare_digest(supplied, token.encode("ascii"))
    except (ValueError, UnicodeError, binascii.Error):
        return False
