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

from . import db, organizers, rounds, suppression
from .config import Settings
from .crypto import KeyStore, handle

EVENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=rounds.PARIS)
    return dt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")

    sub.add_parser("flags", help="list abuse flags")
    for name in ("suspend", "unsuspend"):
        p = sub.add_parser(name)
        p.add_argument("--id", required=True, help="event/cohort id")
    ban = sub.add_parser("ban-organizer", help="ban an organizer and suspend their events")
    ban.add_argument("--email", required=True)

    sub.add_parser("queue", help="events waiting for public-listing review (greylist)")
    for name in ("approve", "reject"):
        p = sub.add_parser(name, help=f"{name} a pending public listing")
        p.add_argument("--id", required=True, help="event/cohort id")
    for name in ("blacklist-add", "blacklist-remove"):
        p = sub.add_parser(name)
        p.add_argument("--pattern", required=True, help="email address or bare domain")
    sub.add_parser("blacklist", help="show the blacklist")
    supp = sub.add_parser("suppress", help="manually suppress an address from all mail")
    supp.add_argument("--email", required=True)

    oidc = sub.add_parser("set-oidc", help="configure institutional SSO for a cohort (operator only)")
    oidc.add_argument("--id", required=True, help="event/cohort id")
    oidc.add_argument("--issuer", required=True, help="OIDC issuer URL, or '' to disable")
    oidc.add_argument("--client-id", default="")
    oidc.add_argument("--client-secret", default="")

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

    args = parser.parse_args(argv)
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
        elif args.cmd == "flags":
            rows = conn.execute(
                "SELECT cohort_id, reason, detail, created_at FROM flags ORDER BY created_at"
            ).fetchall()
            for row in rows:
                print(f"{row['created_at']}  {row['cohort_id']}  {row['reason']}  {row['detail']}")
            print(f"{len(rows)} flag(s)")
        elif args.cmd == "suspend":
            organizers.set_suspended(conn, args.id, True)
            print(f"{args.id} suspended")
        elif args.cmd == "unsuspend":
            organizers.set_suspended(conn, args.id, False)
            print(f"{args.id} active (flags cleared)")
        elif args.cmd == "ban-organizer":
            n = organizers.ban_organizer(conn, args.email.strip().lower())
            print(f"banned; {n} event(s) suspended")
        elif args.cmd == "queue":
            rows = conn.execute(
                "SELECT id, label FROM cohorts WHERE listing_status = 'pending' ORDER BY id"
            ).fetchall()
            for row in rows:
                print(f"{row['id']}  {row['label']}")
            print(f"{len(rows)} pending")
        elif args.cmd in ("approve", "reject"):
            status = "approved" if args.cmd == "approve" else "unlisted"
            with conn:
                conn.execute(
                    "UPDATE cohorts SET listing_status = ? WHERE id = ?", (status, args.id)
                )
            print(f"{args.id}: listing {status}")
        elif args.cmd == "blacklist-add":
            organizers.blacklist_add(conn, args.pattern)
            print(f"blacklisted {args.pattern}")
        elif args.cmd == "blacklist-remove":
            organizers.blacklist_remove(conn, args.pattern)
            print(f"removed {args.pattern}")
        elif args.cmd == "blacklist":
            rows = conn.execute("SELECT pattern FROM blacklist ORDER BY pattern").fetchall()
            for row in rows:
                print(row["pattern"])
            print(f"{len(rows)} entr(y/ies)")
        elif args.cmd == "suppress":
            ok = suppression.suppress(conn, settings.pepper, args.email, "manual")
            print("suppressed" if ok else "not an email-shaped address")
        elif args.cmd == "set-oidc":
            with conn:
                conn.execute(
                    "UPDATE cohorts SET oidc_issuer = ?, oidc_client_id = ?,"
                    " oidc_client_secret = ? WHERE id = ?",
                    (args.issuer or None, args.client_id or None,
                     args.client_secret or None, args.id),
                )
            print(f"{args.id}: SSO {'enabled' if args.issuer else 'disabled'}")
        else:
            print("db ready")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
