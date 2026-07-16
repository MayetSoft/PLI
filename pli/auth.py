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
ORG_SESSION_TTL = timedelta(days=30)


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


def issue_org_link(
    conn: sqlite3.Connection,
    email: str,
    now: datetime | None = None,
) -> str:
    now = now or _utcnow()
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).digest()
    with conn:
        conn.execute(
            "INSERT INTO org_links (token_hash, email, expires_at, used_at)"
            " VALUES (?, ?, ?, NULL)",
            (token_hash, email, (now + TOKEN_TTL).isoformat()),
        )
    return token


def redeem_org_link(
    conn: sqlite3.Connection,
    token: str,
    now: datetime | None = None,
) -> str | None:
    now = now or _utcnow()
    token_hash = hashlib.sha256(token.encode()).digest()
    row = conn.execute(
        "SELECT email, expires_at, used_at FROM org_links WHERE token_hash = ?",
        (token_hash,),
    ).fetchone()
    if row is None or row["used_at"] is not None:
        return None
    if datetime.fromisoformat(row["expires_at"]) < now:
        return None
    with conn:
        conn.execute(
            "UPDATE org_links SET used_at = ? WHERE token_hash = ?",
            (now.isoformat(), token_hash),
        )
    return row["email"]


def _session_key(pepper: bytes) -> bytes:
    return hmac.new(pepper, b"pli-session-v1", hashlib.sha256).digest()


def _org_key(pepper: bytes) -> bytes:
    return hmac.new(pepper, b"pli-org-session-v1", hashlib.sha256).digest()


def _sign(key: bytes, payload: bytes) -> str:
    sig = hmac.new(key, payload, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(payload).decode() + "." + sig


def _verify(key: bytes, value: str) -> bytes | None:
    try:
        payload_b64, sig = value.rsplit(".", 1)
        payload = base64.urlsafe_b64decode(payload_b64.encode())
        expected = hmac.new(key, payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        return payload
    except Exception:
        return None


def sign_org_session(pepper: bytes, organizer_id: int, now: datetime | None = None) -> str:
    now = now or _utcnow()
    expires = int((now + ORG_SESSION_TTL).timestamp())
    return _sign(_org_key(pepper), f"{organizer_id}.{expires}".encode())


def verify_org_session(pepper: bytes, value: str, now: datetime | None = None) -> int | None:
    now = now or _utcnow()
    payload = _verify(_org_key(pepper), value)
    if payload is None:
        return None
    try:
        organizer_id_s, expires_s = payload.decode().split(".")
        if int(expires_s) < now.timestamp():
            return None
        return int(organizer_id_s)
    except Exception:
        return None


def sign_session(pepper: bytes, round_id: int, handle: bytes, now: datetime | None = None) -> str:
    now = now or _utcnow()
    expires = int((now + SESSION_TTL).timestamp())
    # Payload and signature are separately encoded (see _sign): raw signature
    # bytes may themselves contain the separator, corrupting the split.
    return _sign(_session_key(pepper), f"{round_id}.{expires}.{handle.hex()}".encode())


def verify_session(pepper: bytes, value: str, now: datetime | None = None) -> tuple[int, bytes] | None:
    now = now or _utcnow()
    payload = _verify(_session_key(pepper), value)
    if payload is None:
        return None
    try:
        round_id_s, expires_s, handle_hex = payload.decode().split(".")
        if int(expires_s) < now.timestamp():
            return None
        return int(round_id_s), bytes.fromhex(handle_hex)
    except Exception:
        return None
