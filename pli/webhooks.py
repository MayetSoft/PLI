"""Outbound status webhooks to the organizer's own systems.

The payload carries the round's lifecycle status and nothing else — no
counts, no participant data, nothing beyond what the public event page
already says. Signed with a per-event secret (X-PLI-Signature:
hex HMAC-SHA256 of the raw body) so the receiver can authenticate us.
Delivery is best-effort: a webhook is a courtesy, never a dependency —
the reveal must not wait on anyone's endpoint.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import urllib.request

STATUSES = ("opened", "closed", "voided", "revealed")


def notify(
    conn: sqlite3.Connection,
    cohort_id: str,
    round_id: int,
    status: str,
    opener=None,
) -> bool:
    """POST a status change to the event's webhook URL, if configured.
    Returns True if a delivery was attempted. Never raises."""
    if status not in STATUSES:
        return False
    row = conn.execute(
        "SELECT webhook_url, webhook_secret FROM cohorts WHERE id = ?", (cohort_id,)
    ).fetchone()
    if row is None or not row["webhook_url"]:
        return False
    body = json.dumps(
        {"event": cohort_id, "round": round_id, "status": status},
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(
        (row["webhook_secret"] or "").encode(), body, hashlib.sha256
    ).hexdigest()
    request = urllib.request.Request(
        row["webhook_url"],
        data=body,
        headers={"Content-Type": "application/json", "X-PLI-Signature": signature},
        method="POST",
    )
    opener = opener or urllib.request.urlopen
    try:
        with opener(request, timeout=5):
            pass
    except Exception:
        pass  # best-effort by design
    return True
