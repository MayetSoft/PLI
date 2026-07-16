"""Self-serve organizers: accounts, event configuration, abuse flags.

Organizers are accountable parties, not participants. They configure
events and see round status plus a participant count — never a roster,
never a declaration, never a match count. The participant-side invariants
are not theirs to weaken, which is why edits are guardrailed:

- The published timeline can be edited freely while the round is still
  scheduled; once the round is open it can only be *extended* — a reveal
  can never be pulled forward under people who declared expecting a
  later, published instant, and it can never precede the close.
- min_cohort is a published pre-commitment ("under N, nothing runs").
  It freezes when the round opens: no adaptive lowering after seeing
  the signup count.
- Mail is never free-form. Organizers get a plain-text note rendered
  inside the platform's fixed templates, clearly attributed to them —
  not a template editor (that would be a phishing kit).
- Cancelling an event voids the round: delete everything, reveal
  nothing. Silence is always available.
"""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
from datetime import datetime, timezone

from . import rounds
from .crypto import KeyStore, handle

FLAG_SUSPEND_THRESHOLD = 3
FLAG_REASONS = ("impersonation", "harassment", "spam", "other")
LABEL_MAX = 100
DESCRIPTION_MAX = 2000
MAIL_INTRO_MAX = 500
MIN_COHORT_FLOOR = 2

ACTIVE_ROUND_STATUSES = ("scheduled", "open", "closed")


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# ---- accounts -------------------------------------------------------------


def get_or_create_organizer(conn: sqlite3.Connection, email: str) -> sqlite3.Row:
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO organizers (email, created_at, status) VALUES (?, ?, 'active')",
            (email, _utcnow().isoformat()),
        )
    return conn.execute("SELECT * FROM organizers WHERE email = ?", (email,)).fetchone()


def get_organizer(conn: sqlite3.Connection, organizer_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM organizers WHERE id = ?", (organizer_id,)).fetchone()


def organizer_by_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM organizers WHERE email = ?", (email,)).fetchone()


def ban_organizer(conn: sqlite3.Connection, email: str) -> int:
    """Ban an organizer and suspend every event they run. Returns the
    number of events suspended."""
    row = organizer_by_email(conn, email)
    if row is None:
        return 0
    with conn:
        conn.execute("UPDATE organizers SET status = 'banned' WHERE id = ?", (row["id"],))
        cur = conn.execute(
            "UPDATE cohorts SET is_suspended = 1 WHERE organizer_id = ?", (row["id"],)
        )
    return cur.rowcount


# ---- event configuration ---------------------------------------------------


def slugify(conn: sqlite3.Connection, label: str) -> str:
    """URL id from the label plus a random suffix. The suffix avoids both
    collisions and 'that name is taken' responses that would confirm a
    private event's existence."""
    base = re.sub(r"-+", "-", re.sub(r"[^a-z0-9]", "-", label.lower())).strip("-")[:40] or "event"
    while True:
        slug = f"{base}-{secrets.token_hex(2)}"
        if conn.execute("SELECT 1 FROM cohorts WHERE id = ?", (slug,)).fetchone() is None:
            return slug


def _parse_config(form: dict) -> tuple[dict, list[str]]:
    """Validate the organizer-editable fields. Returns (clean, errors)."""
    errors: list[str] = []
    clean: dict = {}

    label = (form.get("label") or "").strip()
    if not label or len(label) > LABEL_MAX:
        errors.append(f"A label is required (at most {LABEL_MAX} characters).")
    clean["label"] = label

    description = (form.get("description") or "").strip()
    if len(description) > DESCRIPTION_MAX:
        errors.append(f"The description is limited to {DESCRIPTION_MAX} characters.")
    clean["description"] = description

    mail_intro = (form.get("mail_intro") or "").strip()
    if len(mail_intro) > MAIL_INTRO_MAX:
        errors.append(f"The email note is limited to {MAIL_INTRO_MAX} characters.")
    clean["mail_intro"] = mail_intro

    visibility = form.get("visibility") or "private"
    if visibility not in ("public", "private"):
        errors.append("Visibility must be public or private.")
    clean["visibility"] = visibility

    domains = [d.strip().lower() for d in (form.get("domains") or "").split(",") if d.strip()]
    if any(not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", d) for d in domains):
        errors.append("One of the email domains is not a valid domain.")
    clean["domains"] = domains

    clean["join_code"] = (form.get("join_code") or "").strip()

    try:
        min_cohort = int(form.get("min_cohort") or 0)
    except ValueError:
        min_cohort = 0
    if min_cohort < MIN_COHORT_FLOOR:
        errors.append(f"The threshold must be at least {MIN_COHORT_FLOOR}.")
    clean["min_cohort"] = min_cohort

    for field in ("opens", "closes", "reveal"):
        raw = (form.get(field) or "").strip()
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=rounds.PARIS)
            clean[field] = dt
        except ValueError:
            errors.append(f"'{field}' is not a valid date and time.")
            clean[field] = None

    return clean, errors


def create_event(
    conn: sqlite3.Connection,
    keystore: KeyStore,
    pepper: bytes,
    organizer_id: int,
    form: dict,
) -> tuple[str | None, list[str]]:
    """Create a cohort + its scheduled round from an organizer form.
    Returns (event_id, errors)."""
    clean, errors = _parse_config(form)
    if not clean["domains"] and not clean["join_code"]:
        errors.append("An event needs an email-domain restriction, a join code, or both.")
    if errors:
        return None, errors

    event_id = slugify(conn, clean["label"])
    code_hash = (
        handle(pepper, "code:" + clean["join_code"]) if clean["join_code"] else None
    )
    try:
        # Validate the timeline before writing the cohort row.
        from . import db as db_mod

        db_mod.create_cohort(
            conn, event_id, clean["label"], clean["domains"], clean["min_cohort"],
            schedule="custom", join_code_hash=code_hash, organizer_id=organizer_id,
            visibility=clean["visibility"], description=clean["description"],
            mail_intro=clean["mail_intro"],
        )
        rounds.schedule_round(
            conn, keystore, event_id, clean["opens"], clean["closes"], clean["reveal"]
        )
    except ValueError as exc:
        with conn:
            conn.execute("DELETE FROM cohorts WHERE id = ?", (event_id,))
        return None, [str(exc)]
    return event_id, []


def active_round(conn: sqlite3.Connection, cohort_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM rounds WHERE cohort_id = ? AND status IN (?, ?, ?)"
        " ORDER BY id DESC LIMIT 1",
        (cohort_id, *ACTIVE_ROUND_STATUSES),
    ).fetchone()


def update_event(
    conn: sqlite3.Connection,
    keystore: KeyStore,
    pepper: bytes,
    cohort: sqlite3.Row,
    form: dict,
) -> list[str]:
    """Apply an organizer edit, enforcing the guardrails documented in the
    module docstring. Returns a list of errors (empty on success)."""
    clean, errors = _parse_config(form)
    remove_code = bool(form.get("remove_join_code"))

    code_hash = cohort["join_code_hash"]
    if clean["join_code"]:
        code_hash = handle(pepper, "code:" + clean["join_code"])
    elif remove_code:
        code_hash = None
    if not clean["domains"] and code_hash is None:
        errors.append("An event needs an email-domain restriction, a join code, or both.")

    round_row = active_round(conn, cohort["id"])
    new_times: dict[str, datetime] = {}
    if round_row is not None and all(clean[f] for f in ("opens", "closes", "reveal")):
        # Forms carry minute precision; compare at minute precision so a
        # round-trip through the edit form is not a spurious "change".
        def _minute(dt: datetime) -> datetime:
            return dt.replace(second=0, microsecond=0)

        opens, closes, reveal = (_minute(clean[f]) for f in ("opens", "closes", "reveal"))
        old = {
            f: _minute(datetime.fromisoformat(round_row[f + "_at"]))
            for f in ("opens", "closes", "reveal")
        }
        status = round_row["status"]
        if status == "scheduled":
            if not (opens < closes <= reveal):
                errors.append("The timeline must satisfy opens < closes ≤ reveal.")
            else:
                new_times = {"opens": opens, "closes": closes, "reveal": reveal}
        elif status == "open":
            if opens != old["opens"]:
                errors.append("The round is open: its opening time is in the past and fixed.")
            elif closes < old["closes"] or reveal < old["reveal"]:
                errors.append(
                    "The round is open: the close and the reveal can be pushed later, "
                    "never pulled earlier — people declared against the published times."
                )
            elif not closes <= reveal:
                errors.append("The reveal cannot precede the close.")
            else:
                new_times = {"closes": closes, "reveal": reveal}
        else:  # closed, awaiting reveal
            if reveal < old["reveal"]:
                errors.append("The round is closed: the reveal can only be pushed later.")
            elif opens != old["opens"] or closes != old["closes"]:
                errors.append("The round is closed: only the reveal time can still move.")
            else:
                new_times = {"reveal": reveal}

        if round_row["status"] != "scheduled" and clean["min_cohort"] != cohort["min_cohort"]:
            errors.append(
                "The threshold is a published pre-commitment: it freezes once the round opens."
            )

    if errors:
        return errors

    with conn:
        conn.execute(
            "UPDATE cohorts SET label = ?, description = ?, mail_intro = ?,"
            " visibility = ?, email_domains = ?, join_code_hash = ?, min_cohort = ?"
            " WHERE id = ?",
            (
                clean["label"], clean["description"], clean["mail_intro"],
                clean["visibility"],
                json.dumps(sorted(clean["domains"])),
                code_hash,
                clean["min_cohort"] if (round_row is None or round_row["status"] == "scheduled")
                else cohort["min_cohort"],
                cohort["id"],
            ),
        )
        if round_row is not None and new_times:
            sets = ", ".join(f"{f}_at = ?" for f in new_times)
            conn.execute(
                f"UPDATE rounds SET {sets} WHERE id = ?",
                (*(d.isoformat() for d in new_times.values()), round_row["id"]),
            )
    return []


def cancel_event(conn: sqlite3.Connection, keystore: KeyStore, cohort_id: str) -> bool:
    """Void the active round: delete everything, reveal nothing, notify
    nobody. Returns True if a round was voided."""
    round_row = active_round(conn, cohort_id)
    if round_row is None:
        return False
    rounds.void_round(conn, keystore, round_row["id"])
    return True


def schedule_new_round(
    conn: sqlite3.Connection,
    keystore: KeyStore,
    cohort_id: str,
    form: dict,
) -> list[str]:
    """A finished event can run again — a new round, from nothing, because
    nothing from the previous one survived."""
    if active_round(conn, cohort_id) is not None:
        return ["A round is already scheduled or running."]
    clean, errors = _parse_config({**form, "label": "x", "min_cohort": "2"})
    errors = [e for e in errors if "date and time" in e]
    if errors:
        return errors
    try:
        rounds.schedule_round(
            conn, keystore, cohort_id, clean["opens"], clean["closes"], clean["reveal"]
        )
    except ValueError as exc:
        return [str(exc)]
    return []


def organizer_events(conn: sqlite3.Connection, organizer_id: int) -> list[dict]:
    """Dashboard data: configuration, round status, participant count.
    Deliberately nothing else — no rosters, no declaration or match
    counts, which do not exist to be shown."""
    out = []
    for cohort in conn.execute(
        "SELECT * FROM cohorts WHERE organizer_id = ? ORDER BY id", (organizer_id,)
    ).fetchall():
        round_row = rounds.latest_round(conn, cohort["id"])
        participants = 0
        if round_row is not None and round_row["status"] in ACTIVE_ROUND_STATUSES:
            participants = conn.execute(
                "SELECT COUNT(*) AS n FROM participants WHERE round_id = ?",
                (round_row["id"],),
            ).fetchone()["n"]
        out.append({"cohort": cohort, "round": round_row, "participants": participants})
    return out


# ---- flags ------------------------------------------------------------------


def flag_event(
    conn: sqlite3.Connection,
    pepper: bytes,
    cohort_id: str,
    reason: str,
    detail: str,
    client_ip: str,
) -> None:
    """Record an abuse flag. One per reporter per event (keyed IP hash —
    no reporter identity is stored). At the threshold the event suspends
    itself pending operator review: joins and declarations stop, and a
    reveal that arrives while suspended voids instead."""
    if reason not in FLAG_REASONS:
        reason = "other"
    reporter = handle(pepper, "flag:" + client_ip)
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO flags (cohort_id, reporter, reason, detail, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (cohort_id, reporter, reason, detail[:500], _utcnow().isoformat()),
        )
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM flags WHERE cohort_id = ?", (cohort_id,)
        ).fetchone()["n"]
        if n >= FLAG_SUSPEND_THRESHOLD:
            conn.execute("UPDATE cohorts SET is_suspended = 1 WHERE id = ?", (cohort_id,))


def set_suspended(conn: sqlite3.Connection, cohort_id: str, suspended: bool) -> None:
    with conn:
        conn.execute(
            "UPDATE cohorts SET is_suspended = ? WHERE id = ?",
            (1 if suspended else 0, cohort_id),
        )
        if not suspended:
            conn.execute("DELETE FROM flags WHERE cohort_id = ?", (cohort_id,))
