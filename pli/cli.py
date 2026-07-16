"""Operator CLI.

    python -m pli.cli init-db
    python -m pli.cli create-cohort --id iut-mmi-2026 --label "IUT MMI 2026" \
        --domains etu.uca.fr --min-cohort 100
"""

from __future__ import annotations

import argparse

from . import db
from .config import Settings


def main() -> int:
    parser = argparse.ArgumentParser(prog="pli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    cohort = sub.add_parser("create-cohort")
    cohort.add_argument("--id", required=True)
    cohort.add_argument("--label", required=True)
    cohort.add_argument("--domains", required=True, help="comma-separated email domains")
    cohort.add_argument("--min-cohort", type=int, default=100)
    args = parser.parse_args()

    settings = Settings.from_env()
    conn = db.connect(settings.db_path)
    try:
        db.init_db(conn)
        if args.cmd == "create-cohort":
            db.create_cohort(conn, args.id, args.label, args.domains.split(","), args.min_cohort)
            print(f"cohort {args.id} ready")
        else:
            print("db ready")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
