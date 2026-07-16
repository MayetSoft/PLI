import secrets
from datetime import datetime, timedelta, timezone

from pli import db as db_mod
from pli.auth import (
    TOKEN_TTL,
    issue_magic_link,
    redeem_magic_link,
    sign_session,
    verify_session,
)


def make_conn(tmp_path):
    conn = db_mod.connect(str(tmp_path / "t.db"))
    db_mod.init_db(conn)
    return conn


def test_magic_link_single_use(tmp_path):
    conn = make_conn(tmp_path)
    h = secrets.token_bytes(32)
    token = issue_magic_link(conn, 1, h)
    assert redeem_magic_link(conn, token) == (1, h)
    assert redeem_magic_link(conn, token) is None  # second use fails


def test_magic_link_expires(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime.now(tz=timezone.utc)
    token = issue_magic_link(conn, 1, secrets.token_bytes(32), now=now)
    late = now + TOKEN_TTL + timedelta(seconds=1)
    assert redeem_magic_link(conn, token, now=late) is None


def test_magic_link_unknown_token(tmp_path):
    conn = make_conn(tmp_path)
    assert redeem_magic_link(conn, "no-such-token") is None


def test_session_round_trip_and_tamper():
    pepper = secrets.token_bytes(32)
    h = secrets.token_bytes(32)
    value = sign_session(pepper, 7, h)
    assert verify_session(pepper, value) == (7, h)
    assert verify_session(secrets.token_bytes(32), value) is None  # wrong pepper
    assert verify_session(pepper, value[:-4] + "AAAA") is None     # tampered
    assert verify_session(pepper, "garbage") is None
