"""Operator CLI.

    python -m pli.cli init-db

    # A weekly community (the original product):
    python -m pli.cli create-cohort --id iut-mmi-2026 --label "IUT MMI 2026" \
        --domains etu.uca.fr --min-cohort 100

    # An event with its own timeline (a conference, a speed-dating night):
    python -m pli.cli create-event --id devconf-2026 --label "DevConf 2026" \
        --join-code sesame --min-cohort 20 \
        --opens "2026-09-10T09:00" --closes "2026-09-12T18:00" --reveal "2026-09-12T20:00"

Events are gated by email domains, a join code, or both. Naive datetimes
are read as Europe/Paris. The event page is served, unlisted, at /e/{id}.
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime

from . import db, rounds
from .config import Settings
from .crypto import KeyStore, handle

EVENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=rounds.PARIS)
    return dt


def main() -> int:
    parser = argparse.ArgumentParser(prog="pli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")

    cohort = sub.add_parser("create-cohort", help="weekly community (default product)")
    cohort.add_argument("--id", required=True)
    cohort.add_argument("--label", required=True)
    cohort.add_argument("--domains", required=True, help="comma-separated email domains")
    cohort.add_argument("--min-cohort", type=int, default=100)

    event = sub.add_parser("create-event", help="one-shot event with its own timeline")
    event.add_argument("--id", required=True)
    event.add_argument("--label", required=True)
    event.add_argument("--domains", default="", help="comma-separated email domains (optional)")
    event.add_argument("--join-code", default="", help="shared code participants must present (optional)")
    event.add_argument("--min-cohort", type=int, default=100)
    event.add_argument("--opens", required=True, help="ISO datetime; naive = Europe/Paris")
    event.add_argument("--closes", required=True)
    event.add_argument("--reveal", required=True)

    args = parser.parse_args()
    settings = Settings.from_env()
    conn = db.connect(settings.db_path)
    try:
        db.init_db(conn)
        if args.cmd == "create-cohort":
            db.create_cohort(conn, args.id, args.label, args.domains.split(","), args.min_cohort)
            print(f"cohort {args.id} ready")
        elif args.cmd == "create-event":
            if not EVENT_ID_RE.match(args.id):
                parser.error("--id must be lowercase letters, digits, hyphens (max 64)")
            domains = [d for d in args.domains.split(",") if d]
            if not domains and not args.join_code:
                parser.error("an event needs --domains, --join-code, or both")
            code_hash = (
                handle(settings.pepper, "code:" + args.join_code.strip())
                if args.join_code else None
            )
            db.create_cohort(
                conn, args.id, args.label, domains, args.min_cohort,
                schedule="custom", join_code_hash=code_hash,
            )
            round_id = rounds.schedule_round(
                conn, KeyStore(settings.keys_dir), args.id,
                parse_dt(args.opens), parse_dt(args.closes), parse_dt(args.reveal),
            )
            print(f"event {args.id} ready (round {round_id}) — share {settings.base_url}/e/{args.id}")
        else:
            print("db ready")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
