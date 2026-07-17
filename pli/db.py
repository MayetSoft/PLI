"""SQLite. Single file, WAL, tiny and ephemeral by design.

Note what is absent: no users table, no persistent identity, no history,
no created_at on declarations (a timestamp is a side channel).
participants and declarations are WITHOUT ROWID so insertion order is not
recoverable from the file — row order is PK order, another side channel
closed.
"""

from __future__ import annotations

import json
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS rounds (
  id            INTEGER PRIMARY KEY,
  cohort_id     TEXT NOT NULL,
  opens_at      TEXT NOT NULL,
  closes_at     TEXT NOT NULL,
  reveal_at     TEXT NOT NULL,
  status        TEXT NOT NULL,  -- open | closed | revealed | voided
  UNIQUE(cohort_id, opens_at)
);

CREATE TABLE IF NOT EXISTS cohorts (
  id            TEXT PRIMARY KEY,
  label         TEXT NOT NULL,
  email_domains TEXT NOT NULL,         -- JSON array; [] = any domain (join code gates instead)
  min_cohort    INTEGER NOT NULL DEFAULT 100,
  schedule      TEXT NOT NULL DEFAULT 'weekly',  -- weekly | custom
  join_code_hash BLOB                  -- HMAC(pepper, "code:" + code), optional
);

-- One row per participant per round. Deleted at reveal.
CREATE TABLE IF NOT EXISTS participants (
  round_id      INTEGER NOT NULL REFERENCES rounds(id),
  handle        BLOB NOT NULL,         -- HMAC(pepper, normalised_email)
  contact       BLOB NOT NULL,         -- AES-GCM(round_key, email)
  PRIMARY KEY (round_id, handle)
) WITHOUT ROWID;

-- The escrow. Deleted at reveal, unconditionally.
CREATE TABLE IF NOT EXISTS declarations (
  round_id      INTEGER NOT NULL REFERENCES rounds(id),
  src           BLOB NOT NULL,
  dst           BLOB NOT NULL,
  PRIMARY KEY (round_id, src, dst)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS magic_links (
  token_hash    BLOB PRIMARY KEY,
  round_id      INTEGER NOT NULL,
  handle        BLOB NOT NULL,
  expires_at    TEXT NOT NULL,
  used_at       TEXT
);

-- Organizers are accountable parties, not participants: their address is
-- an ordinary business record (abuse contact), stored in the clear. They
-- never see participant identities — only counts and round status.
CREATE TABLE IF NOT EXISTS organizers (
  id            INTEGER PRIMARY KEY,
  email         TEXT NOT NULL UNIQUE,   -- normalised
  created_at    TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'active'  -- active | banned
);

CREATE TABLE IF NOT EXISTS org_links (
  token_hash    BLOB PRIMARY KEY,
  email         TEXT NOT NULL,
  expires_at    TEXT NOT NULL,
  used_at       TEXT
);

-- Abuse flags on events. One per reporter (keyed IP hash) per event;
-- contains no participant data. Reaching the threshold auto-suspends the
-- event pending operator review.
CREATE TABLE IF NOT EXISTS flags (
  cohort_id     TEXT NOT NULL,
  reporter      BLOB NOT NULL,          -- HMAC(pepper, "flag:" + ip) — dedup only
  reason        TEXT NOT NULL,
  detail        TEXT NOT NULL DEFAULT '',
  created_at    TEXT NOT NULL,
  PRIMARY KEY (cohort_id, reporter)
) WITHOUT ROWID;

-- Mail suppression list, fed by bounce/complaint webhooks. Only a keyed
-- hash is kept: membership is all we ever need to know.
CREATE TABLE IF NOT EXISTS suppressions (
  addr_hash     BLOB PRIMARY KEY,       -- HMAC(pepper, "suppress:" + normalised_email)
  reason        TEXT NOT NULL,          -- bounce | complaint | manual
  created_at    TEXT NOT NULL
) WITHOUT ROWID;

-- Moderation blacklist for organizers: exact emails or whole domains.
-- Matching addresses cannot sign in as organizers; matches are silent.
CREATE TABLE IF NOT EXISTS blacklist (
  pattern       TEXT PRIMARY KEY,       -- "user@host.example" or "host.example"
  created_at    TEXT NOT NULL
) WITHOUT ROWID;
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # Additive migrations for databases created before the platform columns.
    for ddl in (
        "ALTER TABLE cohorts ADD COLUMN schedule TEXT NOT NULL DEFAULT 'weekly'",
        "ALTER TABLE cohorts ADD COLUMN join_code_hash BLOB",
        "ALTER TABLE cohorts ADD COLUMN organizer_id INTEGER",
        "ALTER TABLE cohorts ADD COLUMN visibility TEXT NOT NULL DEFAULT 'private'",
        "ALTER TABLE cohorts ADD COLUMN description TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE cohorts ADD COLUMN mail_intro TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE cohorts ADD COLUMN is_suspended INTEGER NOT NULL DEFAULT 0",
        # unlisted | pending | approved — public listing is moderated
        # (greylist): asking to be public queues the event for review.
        "ALTER TABLE cohorts ADD COLUMN listing_status TEXT NOT NULL DEFAULT 'unlisted'",
        "ALTER TABLE organizers ADD COLUMN plan TEXT NOT NULL DEFAULT 'free'",
        "ALTER TABLE organizers ADD COLUMN stripe_customer TEXT",
    ):
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()


def create_cohort(
    conn: sqlite3.Connection,
    cohort_id: str,
    label: str,
    email_domains: list[str],
    min_cohort: int = 100,
    schedule: str = "weekly",
    join_code_hash: bytes | None = None,
    organizer_id: int | None = None,
    visibility: str = "private",
    description: str = "",
    mail_intro: str = "",
) -> None:
    if schedule not in ("weekly", "custom"):
        raise ValueError("schedule must be 'weekly' or 'custom'")
    if visibility not in ("public", "private"):
        raise ValueError("visibility must be 'public' or 'private'")
    if not email_domains and join_code_hash is None:
        raise ValueError("a cohort needs email domains, a join code, or both")
    conn.execute(
        "INSERT OR REPLACE INTO cohorts"
        " (id, label, email_domains, min_cohort, schedule, join_code_hash,"
        "  organizer_id, visibility, description, mail_intro, is_suspended)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
        (
            cohort_id,
            label,
            json.dumps(sorted(d.lower() for d in email_domains)),
            min_cohort,
            schedule,
            join_code_hash,
            organizer_id,
            visibility,
            description,
            mail_intro,
        ),
    )
    conn.commit()


def vacuum(conn: sqlite3.Connection) -> None:
    """Reclaim deleted pages. 'We deleted it' must be true at the page
    level, not just the row level."""
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("VACUUM")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
