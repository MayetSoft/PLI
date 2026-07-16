"""Round lifecycle.

The default (a 'weekly' cohort) runs the original cadence: open Monday
00:00, close Friday 23:59, reveal Saturday 08:00 (Europe/Paris). A
'custom' cohort — an event — carries its own opens/closes/reveal
timestamps on the round row; a conference can run over three days, a
speed-dating event over two hours. Either way the state machine and the
invariants are identical: scheduled → open → closed → revealed | voided,
matching is scoped to a single round, and nothing survives the reveal.

The reveal is the heart of the product: compute reciprocal pairs, mail
each half of a pair the other's address, then delete everything —
unconditionally, even if mail fails. A failed send is a bad week; a
surviving graph is a catastrophe.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import db
from .crypto import KeyStore, unseal
from .mailer import Mail, Mailer

PARIS = ZoneInfo("Europe/Paris")
MAX_DECLARATIONS = 3

MATCH_SUBJECT = "PLI — it was mutual"
MATCH_BODY = """You named someone this week. They named you.

{other}

This is the only message either of you will receive. From here, the
conversation is yours. Nothing about this round has been retained.
"""

RECIPROCAL_PAIRS_SQL = """
SELECT a.src, a.dst FROM declarations a
JOIN declarations b
  ON a.src = b.dst AND a.dst = b.src AND a.round_id = b.round_id
WHERE a.round_id = ? AND a.src < a.dst
"""


def paris_now() -> datetime:
    return datetime.now(tz=PARIS)


def week_schedule(now: datetime) -> tuple[datetime, datetime, datetime]:
    """(opens, closes, reveal) for the week containing `now`."""
    now = now.astimezone(PARIS)
    monday = (now - timedelta(days=now.weekday())).date()
    opens = datetime(monday.year, monday.month, monday.day, 0, 0, tzinfo=PARIS)
    friday = monday + timedelta(days=4)
    closes = datetime(friday.year, friday.month, friday.day, 23, 59, tzinfo=PARIS)
    saturday = monday + timedelta(days=5)
    reveal = datetime(saturday.year, saturday.month, saturday.day, 8, 0, tzinfo=PARIS)
    return opens, closes, reveal


def open_round(
    conn: sqlite3.Connection,
    keystore: KeyStore,
    cohort_id: str,
    now: datetime | None = None,
) -> int:
    opens, closes, reveal = week_schedule(now or paris_now())
    conn.execute(
        "INSERT OR IGNORE INTO rounds (cohort_id, opens_at, closes_at, reveal_at, status)"
        " VALUES (?, ?, ?, ?, 'open')",
        (cohort_id, opens.isoformat(), closes.isoformat(), reveal.isoformat()),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, status FROM rounds WHERE cohort_id = ? AND opens_at = ?",
        (cohort_id, opens.isoformat()),
    ).fetchone()
    if row["status"] == "open":
        keystore.create(row["id"])
    return row["id"]


def schedule_round(
    conn: sqlite3.Connection,
    keystore: KeyStore,
    cohort_id: str,
    opens: datetime,
    closes: datetime,
    reveal: datetime,
    now: datetime | None = None,
) -> int:
    """Create a round on an arbitrary timeline (a 'custom' event).

    reveal may equal closes (a speed-dating event reveals at the buzzer)
    but can never precede it — a reveal inside an open round would be a
    mid-round signal, which is the thing this product must never emit.
    """
    now = (now or paris_now()).astimezone(PARIS)
    opens, closes, reveal = (
        d.astimezone(PARIS) for d in (opens, closes, reveal)
    )
    if not (opens < closes <= reveal):
        raise ValueError("timeline must satisfy opens < closes <= reveal")
    if closes <= now:
        raise ValueError("round would already be over")
    status = "open" if opens <= now else "scheduled"
    cur = conn.execute(
        "INSERT INTO rounds (cohort_id, opens_at, closes_at, reveal_at, status)"
        " VALUES (?, ?, ?, ?, ?)",
        (cohort_id, opens.isoformat(), closes.isoformat(), reveal.isoformat(), status),
    )
    conn.commit()
    round_id = cur.lastrowid
    if status == "open":
        keystore.create(round_id)
    return round_id


def current_open_round(conn: sqlite3.Connection, cohort_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM rounds WHERE cohort_id = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
        (cohort_id,),
    ).fetchone()


def latest_round(conn: sqlite3.Connection, cohort_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM rounds WHERE cohort_id = ? ORDER BY id DESC LIMIT 1",
        (cohort_id,),
    ).fetchone()


def _purge(conn: sqlite3.Connection, round_id: int, status: str) -> None:
    """Delete the round's entire footprint in one transaction."""
    with conn:
        conn.execute("DELETE FROM declarations WHERE round_id = ?", (round_id,))
        conn.execute("DELETE FROM participants WHERE round_id = ?", (round_id,))
        conn.execute("DELETE FROM magic_links  WHERE round_id = ?", (round_id,))
        conn.execute("UPDATE rounds SET status = ? WHERE id = ?", (status, round_id))


def close_round(conn: sqlite3.Connection, keystore: KeyStore, round_id: int) -> str:
    """Friday 23:59. Under threshold: void — delete all, notify nobody of
    anything but 'no round this week' on the homepage. A voided round is
    indistinguishable from a quiet one."""
    round_row = conn.execute("SELECT * FROM rounds WHERE id = ?", (round_id,)).fetchone()
    if round_row is None or round_row["status"] != "open":
        return round_row["status"] if round_row else "missing"
    cohort = conn.execute(
        "SELECT min_cohort FROM cohorts WHERE id = ?", (round_row["cohort_id"],)
    ).fetchone()
    min_cohort = cohort["min_cohort"] if cohort else 100
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM participants WHERE round_id = ?", (round_id,)
    ).fetchone()["n"]
    if n < min_cohort:
        _purge(conn, round_id, "voided")
        keystore.destroy(round_id)
        db.vacuum(conn)
        return "voided"
    with conn:
        conn.execute("UPDATE rounds SET status = 'closed' WHERE id = ?", (round_id,))
    return "closed"


def reveal_round(
    conn: sqlite3.Connection,
    keystore: KeyStore,
    mailer: Mailer,
    round_id: int,
) -> int:
    """Saturday 08:00. Returns the number of reciprocal pairs.

    Order: compute pairs → send → delete, with delete in a finally.
    Matched pairs get mail. Nobody else does — not "no match" mail, not
    anything. Silence is the only safe null.
    """
    round_row = conn.execute("SELECT * FROM rounds WHERE id = ?", (round_id,)).fetchone()
    if round_row is None or round_row["status"] != "closed":
        return 0
    pairs = 0
    try:
        round_key = keystore.load(round_id)
        if round_key is not None:
            for row in conn.execute(RECIPROCAL_PAIRS_SQL, (round_id,)).fetchall():
                contacts = {}
                for h in (row["src"], row["dst"]):
                    p = conn.execute(
                        "SELECT contact FROM participants WHERE round_id = ? AND handle = ?",
                        (round_id, h),
                    ).fetchone()
                    if p is not None:
                        contacts[h] = unseal(round_key, p["contact"])
                if len(contacts) != 2:
                    continue  # a handle without a participant row cannot be contacted
                a, b = contacts[row["src"]], contacts[row["dst"]]
                pairs += 1
                for me, other in ((a, b), (b, a)):
                    try:
                        mailer.send(Mail(to=me, subject=MATCH_SUBJECT, body=MATCH_BODY.format(other=other)))
                    except Exception:
                        pass  # a failed send is a bad week; deletion still runs
    finally:
        _purge(conn, round_id, "revealed")
        keystore.destroy(round_id)
        db.vacuum(conn)
    return pairs


def _dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def ensure_weekly_rounds(
    conn: sqlite3.Connection, keystore: KeyStore, now: datetime
) -> None:
    """Keep the original weekly cadence for every 'weekly' cohort:
    this week's round exists whenever we are inside Monday 00:00 –
    Friday 23:59. Self-healing: a missed Monday tick is repaired by the
    next tick."""
    opens, closes, _ = week_schedule(now)
    if not (opens <= now < closes):
        return
    for row in conn.execute("SELECT id FROM cohorts WHERE schedule = 'weekly'").fetchall():
        open_round(conn, keystore, row["id"], now)


def tick(
    conn: sqlite3.Connection,
    keystore: KeyStore,
    mailer: Mailer,
    now: datetime | None = None,
) -> dict[str, int]:
    """Advance every round that is due, on its own timeline. Run once a
    minute. Replaces fixed cron positions: the schedule lives in the
    data, not in the crontab."""
    now = (now or paris_now()).astimezone(PARIS)
    stats = {"opened": 0, "closed": 0, "revealed": 0, "voided": 0}
    ensure_weekly_rounds(conn, keystore, now)

    for row in conn.execute("SELECT * FROM rounds WHERE status = 'scheduled'").fetchall():
        if now >= _dt(row["closes_at"]):
            # Never opened and already past close (scheduler outage):
            # nothing was collected, nothing runs. Void quietly.
            _purge(conn, row["id"], "voided")
            keystore.destroy(row["id"])
            stats["voided"] += 1
        elif now >= _dt(row["opens_at"]):
            with conn:
                conn.execute("UPDATE rounds SET status = 'open' WHERE id = ?", (row["id"],))
            keystore.create(row["id"])
            stats["opened"] += 1

    for row in conn.execute("SELECT * FROM rounds WHERE status = 'open'").fetchall():
        if now >= _dt(row["closes_at"]):
            outcome = close_round(conn, keystore, row["id"])
            stats["voided" if outcome == "voided" else "closed"] += 1

    for row in conn.execute("SELECT * FROM rounds WHERE status = 'closed'").fetchall():
        if now >= _dt(row["reveal_at"]):
            reveal_round(conn, keystore, mailer, row["id"])
            stats["revealed"] += 1

    return stats
