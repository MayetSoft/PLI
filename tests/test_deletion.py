"""'We deleted it' must be true at the page level, not just the row level.

Greps the raw database file (and WAL/SHM) for known plaintext addresses.
They must never appear — before reveal (contacts are sealed, handles are
HMACs) and after reveal (rows deleted, VACUUM run).
"""

from pathlib import Path

from conftest import DOMAIN, close_round, declare, reveal_round, round_id, signup

ALICE = f"alice@{DOMAIN}"
BOB = f"bob@{DOMAIN}"
GHOST = f"ghost@{DOMAIN}"


def raw_db_bytes(app) -> bytes:
    base = Path(app.state.settings.db_path)
    blob = b""
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(base) + suffix)
        if p.exists():
            blob += p.read_bytes()
    return blob


def test_no_plaintext_address_in_db_file_ever(app, mailer):
    alice = signup(app, mailer, ALICE)
    bob = signup(app, mailer, BOB)
    declare(alice, BOB, GHOST)
    declare(bob, ALICE)

    # Even mid-round, addresses exist on disk only as HMACs and AES-GCM blobs.
    mid_round = raw_db_bytes(app)
    for address in (ALICE, BOB, GHOST):
        assert address.encode() not in mid_round

    rid = round_id(app)
    close_round(app)
    reveal_round(app, mailer)

    after = raw_db_bytes(app)
    for address in (ALICE, BOB, GHOST):
        assert address.encode() not in after

    # The round key is destroyed with the round.
    assert app.state.keystore.load(rid) is None
    assert not list(Path(app.state.settings.keys_dir).glob(f"round-{rid}.key"))


def test_deletion_runs_even_if_mail_fails(app, mailer):
    """Compute pairs → send → delete, delete in a finally. A failed send is
    a bad week; a surviving graph is a catastrophe."""
    alice = signup(app, mailer, ALICE)
    bob = signup(app, mailer, BOB)
    declare(alice, BOB)
    declare(bob, ALICE)
    close_round(app)

    class ExplodingMailer:
        def send(self, mail):
            raise ConnectionError("provider down")

    reveal_round(app, ExplodingMailer())

    from conftest import connect

    conn = connect(app)
    for table in ("declarations", "participants", "magic_links"):
        assert conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"] == 0
    conn.close()
