"""RFC 6238 TOTP (Docspell-style two-factor authentication).

Implemented without an extra dependency: HMAC-SHA1, 30s windows, 6 digits.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _hotp(key: bytes, counter: int, digits: int = 6) -> str:
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{code % (10 ** digits):0{digits}d}"


def totp(secret: str, timestamp: int | None = None, interval: int = 30) -> str:
    padded = secret + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded.upper())
    counter = int(timestamp if timestamp is not None else time.time()) // interval
    return _hotp(key, counter)


def verify_totp(secret: str, code: str, window: int = 1, interval: int = 30) -> bool:
    if not secret or not code:
        return False
    supplied = code.strip()
    if not supplied.isdigit() or len(supplied) != 6:
        return False
    now_ts = int(time.time())
    for offset in range(-window, window + 1):
        if hmac.compare_digest(supplied, totp(secret, now_ts + offset * interval, interval)):
            return True
    return False


def otpauth_url(secret: str, username: str, issuer: str = "NewtonEDMS") -> str:
    label = quote(f"{issuer}:{username}")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
        f"&algorithm=SHA1&digits=6&period=30"
    )
