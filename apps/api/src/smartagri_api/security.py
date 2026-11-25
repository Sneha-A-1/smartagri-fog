"""Password hashing (scrypt, standard library) and JWT access tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt

_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        return False
    _, salt_b64, digest_b64 = stored.split("$")
    digest = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), n=_N, r=_R, p=_P, dklen=32)
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


def create_access_token(user_id: str, secret: str, minutes: int) -> str:
    now = datetime.now(UTC)
    payload = {"sub": user_id, "iat": now, "exp": now + timedelta(minutes=minutes)}
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, secret: str) -> str | None:
    try:
        return str(jwt.decode(token, secret, algorithms=["HS256"])["sub"])
    except jwt.PyJWTError:
        return None
