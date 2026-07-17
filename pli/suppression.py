"""Mail suppression list, fed by the provider's bounce/complaint
webhooks. A hard-bounced or complaining address must never be mailed
again — for deliverability, and because a complaint is a "stop" that we
honour absolutely.

Only a keyed hash of the address is stored: membership is the only
question we ever ask, so membership is the only thing we keep.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .crypto import handle
from .normalize import is_rfc_shaped, normalise_email

REASONS = ("bounce", "complaint", "manual")


def _hash(pepper: bytes, email: str) -> bytes:
    return handle(pepper, "suppress:" + email)


def suppress(conn: sqlite3.Connection, pepper: bytes, raw_email: str, reason: str) -> bool:
    """Record a suppression. Returns False for garbage input (a webhook
    payload we could not parse into an address is dropped, not stored)."""
    if not is_rfc_shaped(raw_email):
        return False
    if reason not in REASONS:
        reason = "manual"
    try:
        email = normalise_email(raw_email)
    except ValueError:
        return False
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO suppressions (addr_hash, reason, created_at) VALUES (?, ?, ?)",
            (_hash(pepper, email), reason, datetime.now(tz=timezone.utc).isoformat()),
        )
    return True


def is_suppressed(conn: sqlite3.Connection, pepper: bytes, email: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM suppressions WHERE addr_hash = ?", (_hash(pepper, email),)
    ).fetchone() is not None
