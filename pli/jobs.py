"""Round jobs, callable from APScheduler or a cron container.

The scheduler runs `tick` once a minute: it keeps weekly cohorts on the
original Monday/Friday/Saturday cadence and advances custom-timeline
events at their own opens/closes/reveal instants.

    python -m pli.jobs tick    # advance everything that is due (run every minute)

The original fixed commands still work for a plain-cron deployment of a
single weekly community:

    python -m pli.jobs open    # Monday 00:00 Europe/Paris
    python -m pli.jobs close   # Friday 23:59
    python -m pli.jobs reveal  # Saturday 08:00

Output is deliberately sparse: counts and statuses only, never addresses,
never handles.
"""

from __future__ import annotations

import sys

from . import db, rounds
from .config import Settings
from .crypto import KeyStore
from .mailer import make_mailer


def run_open(settings: Settings) -> int:
    conn = db.connect(settings.db_path)
    try:
        db.init_db(conn)
        return rounds.open_round(conn, KeyStore(settings.keys_dir), settings.cohort_id)
    finally:
        conn.close()


def run_close(settings: Settings) -> str:
    conn = db.connect(settings.db_path)
    try:
        row = rounds.current_open_round(conn, settings.cohort_id)
        if row is None:
            return "no-open-round"
        return rounds.close_round(conn, KeyStore(settings.keys_dir), row["id"])
    finally:
        conn.close()


def run_reveal(settings: Settings) -> int:
    conn = db.connect(settings.db_path)
    try:
        row = conn.execute(
            "SELECT * FROM rounds WHERE cohort_id = ? AND status = 'closed' ORDER BY id DESC LIMIT 1",
            (settings.cohort_id,),
        ).fetchone()
        if row is None:
            return 0
        return rounds.reveal_round(
            conn, KeyStore(settings.keys_dir), make_mailer(settings), row["id"],
            pepper=settings.pepper,
        )
    finally:
        conn.close()


def run_tick(settings: Settings) -> dict[str, int]:
    conn = db.connect(settings.db_path)
    try:
        db.init_db(conn)
        return rounds.tick(
            conn, KeyStore(settings.keys_dir), make_mailer(settings), pepper=settings.pepper
        )
    finally:
        conn.close()


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in ("open", "close", "reveal", "tick"):
        print("usage: python -m pli.jobs {tick|open|close|reveal}", file=sys.stderr)
        return 2
    settings = Settings.from_env()
    if argv[0] == "tick":
        stats = run_tick(settings)
        print(" ".join(f"{k}={v}" for k, v in stats.items()))
    elif argv[0] == "open":
        print(f"round {run_open(settings)} open")
    elif argv[0] == "close":
        print(f"close: {run_close(settings)}")
    else:
        print(f"reveal: {run_reveal(settings)} pair(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
