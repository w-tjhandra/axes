"""Autentikasi: argon2, TOTP, cookie sesi, dan rate limit login."""

from __future__ import annotations

import hashlib
import os
import secrets
import time
from collections import defaultdict, deque
from typing import Any

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import HTTPException, Request

try:  # dukung `uvicorn main:app` maupun `uvicorn app.main:app`
    from .db import utcnow, utc_after
except ImportError:  # pragma: no cover - jalur eksekusi langsung
    from db import utcnow, utc_after  # type: ignore[no-redef]

_hasher = PasswordHasher()
COOKIE_NAME = os.environ.get("SESSION_COOKIE_NAME", "ukk_session")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(
        name=username, issuer_name="UKK Junior Network Technician"
    )


def verify_totp(secret: str, code: str | None) -> bool:
    if not code:
        return False
    code = str(code).strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return False
    return bool(pyotp.TOTP(secret).verify(code, valid_window=2))


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_days() -> int:
    try:
        return max(1, int(os.environ.get("SESSION_DAYS", "7")))
    except ValueError:
        return 7


def is_https(request: Request | None) -> bool:
    if request is None:
        return False
    if request.url.scheme == "https":
        return True
    if os.environ.get("TRUST_PROXY", "").lower() in {"1", "true", "yes"}:
        proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
        return proto == "https"
    return False


def cookie_secure(request: Request | None = None) -> bool:
    enabled = os.environ.get("COOKIE_SECURE", "").lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return False
    if request is not None and not is_https(request):
        return False
    return True


def create_session(conn, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO session (token_hash, user_id, created_at, expires_at, last_seen) VALUES (?, ?, ?, ?, ?)",
        (_hash_token(token), user_id, utcnow(), utc_after(session_days()), utcnow()),
    )
    conn.commit()
    return token


def get_session_user(conn, token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    row = conn.execute(
        """
        SELECT u.id, u.username, u.totp_secret, s.expires_at
        FROM session s JOIN user u ON u.id = s.user_id
        WHERE s.token_hash = ?
        """,
        (_hash_token(token),),
    ).fetchone()
    if row is None:
        return None
    if row["expires_at"] <= utcnow():
        conn.execute("DELETE FROM session WHERE token_hash = ?", (_hash_token(token),))
        conn.commit()
        return None
    conn.execute(
        "UPDATE session SET last_seen = ? WHERE token_hash = ?", (utcnow(), _hash_token(token))
    )
    conn.commit()
    return {"id": row["id"], "username": row["username"], "totp_enabled": bool(row["totp_secret"])}


def delete_session(conn, token: str | None) -> None:
    if token:
        conn.execute("DELETE FROM session WHERE token_hash = ?", (_hash_token(token),))
        conn.commit()


def require_user(conn, request: Request) -> dict[str, Any]:
    user = get_session_user(conn, request.cookies.get(COOKIE_NAME))
    if user is None:
        raise HTTPException(status_code=401, detail={"error": "unauthorized"})
    return user


class LoginRateLimiter:
    """Rate limit in-memory: maksimal 5 percobaan per 60 detik per IP."""

    def __init__(self, limit: int = 5, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window = window_seconds
        self._items: dict[str, deque[float]] = defaultdict(deque)

    def enabled(self) -> bool:
        return os.environ.get("UKK_DISABLE_RATE_LIMIT", "") not in {"1", "true", "yes"}

    def check(self, key: str) -> bool:
        if not self.enabled():
            return True
        now = time.monotonic()
        bucket = self._items[key]
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()
        return len(bucket) < self.limit

    def hit(self, key: str) -> None:
        if self.enabled():
            self._items[key].append(time.monotonic())

    def reset(self) -> None:
        self._items.clear()


def client_ip(request: Request) -> str:
    if os.environ.get("TRUST_PROXY", "").lower() in {"1", "true", "yes"}:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
