"""Magic-link auth and round-scoped sessions.

Links are single-use, 30-minute TTL; only a SHA-256 of the token is
stored. Sessions are stateless signed cookies bound to one round —
they carry no identity beyond the opaque handle and die with the round.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

TOKEN_TTL = timedelta(minutes=30)
SESSION_TTL = timedelta(hours=12)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def issue_magic_link(
    conn: sqlite3.Connection,
    round_id: int,
    handle: bytes,
    now: datetime | None = None,
) -> str:
    now = now or _utcnow()
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).digest()
    with conn:
        conn.execute(
            "INSERT INTO magic_links (token_hash, round_id, handle, expires_at, used_at)"
            " VALUES (?, ?, ?, ?, NULL)",
            (token_hash, round_id, handle, (now + TOKEN_TTL).isoformat()),
        )
    return token


def redeem_magic_link(
    conn: sqlite3.Connection,
    token: str,
    now: datetime | None = None,
) -> tuple[int, bytes] | None:
    now = now or _utcnow()
    token_hash = hashlib.sha256(token.encode()).digest()
    row = conn.execute(
        "SELECT round_id, handle, expires_at, used_at FROM magic_links WHERE token_hash = ?",
        (token_hash,),
    ).fetchone()
    if row is None or row["used_at"] is not None:
        return None
    if datetime.fromisoformat(row["expires_at"]) < now:
        return None
    with conn:
        conn.execute(
            "UPDATE magic_links SET used_at = ? WHERE token_hash = ?",
            (now.isoformat(), token_hash),
        )
    return row["round_id"], row["handle"]


def _session_key(pepper: bytes) -> bytes:
    return hmac.new(pepper, b"pli-session-v1", hashlib.sha256).digest()


def sign_session(pepper: bytes, round_id: int, handle: bytes, now: datetime | None = None) -> str:
    now = now or _utcnow()
    expires = int((now + SESSION_TTL).timestamp())
    payload = f"{round_id}.{expires}.{handle.hex()}".encode()
    sig = hmac.new(_session_key(pepper), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload + b"." + sig).decode()


def verify_session(pepper: bytes, value: str, now: datetime | None = None) -> tuple[int, bytes] | None:
    now = now or _utcnow()
    try:
        raw = base64.urlsafe_b64decode(value.encode())
        payload, sig = raw.rsplit(b".", 1)
        expected = hmac.new(_session_key(pepper), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        round_id_s, expires_s, handle_hex = payload.decode().split(".")
        if int(expires_s) < now.timestamp():
            return None
        return int(round_id_s), bytes.fromhex(handle_hex)
    except Exception:
        return None
