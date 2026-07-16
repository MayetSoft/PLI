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
  email_domains TEXT NOT NULL,         -- JSON array, e.g. ["etu.uca.fr"]
  min_cohort    INTEGER NOT NULL DEFAULT 100
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
    conn.commit()


def create_cohort(
    conn: sqlite3.Connection,
    cohort_id: str,
    label: str,
    email_domains: list[str],
    min_cohort: int = 100,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO cohorts (id, label, email_domains, min_cohort) VALUES (?, ?, ?, ?)",
        (cohort_id, label, json.dumps(sorted(d.lower() for d in email_domains)), min_cohort),
    )
    conn.commit()


def cohort_domains(conn: sqlite3.Connection, cohort_id: str) -> list[str]:
    row = conn.execute("SELECT email_domains FROM cohorts WHERE id = ?", (cohort_id,)).fetchone()
    return json.loads(row["email_domains"]) if row else []


def vacuum(conn: sqlite3.Connection) -> None:
    """Reclaim deleted pages. 'We deleted it' must be true at the page
    level, not just the row level."""
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("VACUUM")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
