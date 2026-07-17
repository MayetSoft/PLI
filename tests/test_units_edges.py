"""Unit-level edge coverage: mailer, config, ratelimit, auth, db, rounds,
organizers branches not reached by the flow tests."""

import secrets
import time
from datetime import datetime, timedelta, timezone

import pytest

from conftest import COHORT, DOMAIN, connect
from pli import auth, db as db_mod, organizers, rounds
from pli.config import Settings
from pli.crypto import KeyStore, handle
from pli.mailer import ConsoleMailer, Mail, RecordingMailer, SMTPMailer, make_mailer
from pli.ratelimit import RateLimiter

PEPPER = secrets.token_bytes(32)


# ---- mailer -----------------------------------------------------------------


def test_console_mailer(capsys):
    ConsoleMailer().send(Mail(to="a@b.example", subject="s", body="hello"))
    out = capsys.readouterr().out
    assert "a@b.example" in out and "hello" in out


def test_smtp_mailer(monkeypatch):
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self):
            calls.append(("starttls",))

        def login(self, user, password):
            calls.append(("login", user))

        def send_message(self, msg):
            calls.append(("send", msg["To"], msg["Subject"]))

    monkeypatch.setattr("pli.mailer.smtplib.SMTP", FakeSMTP)
    SMTPMailer("smtp.example", 587, "u", "p", "pli@x.example").send(
        Mail(to="a@b.example", subject="s", body="b")
    )
    assert ("login", "u") in calls and ("send", "a@b.example", "s") in calls

    calls.clear()
    SMTPMailer("smtp.example", 587, "", "", "pli@x.example").send(
        Mail(to="a@b.example", subject="s", body="b")
    )
    assert all(c[0] != "login" for c in calls)   # anonymous relay: no login


def test_make_mailer_variants(tmp_path):
    base = dict(db_path="x", pepper=PEPPER, keys_dir=str(tmp_path), cohort_id="c")
    assert isinstance(make_mailer(Settings(**base, mailer="memory")), RecordingMailer)
    assert isinstance(make_mailer(Settings(**base, mailer="smtp")), SMTPMailer)
    assert isinstance(make_mailer(Settings(**base, mailer="console")), ConsoleMailer)


# ---- config -----------------------------------------------------------------


def test_settings_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PLI_PEPPER", "ab" * 32)
    monkeypatch.setenv("PLI_DB", str(tmp_path / "x.db"))
    monkeypatch.setenv("PLI_BASE_URL", "https://pli.example/")
    settings = Settings.from_env()
    assert settings.pepper == bytes.fromhex("ab" * 32)
    assert settings.base_url == "https://pli.example"   # trailing slash stripped


def test_settings_missing_pepper(monkeypatch):
    monkeypatch.delenv("PLI_PEPPER", raising=False)
    with pytest.raises(RuntimeError):
        Settings.from_env()


# ---- ratelimit --------------------------------------------------------------


def test_ratelimiter_window():
    limiter = RateLimiter()
    assert limiter.allow("k", 2, 0.05)
    assert limiter.allow("k", 2, 0.05)
    assert not limiter.allow("k", 2, 0.05)     # over the limit
    time.sleep(0.06)
    assert limiter.allow("k", 2, 0.05)         # window slid


# ---- auth -------------------------------------------------------------------


def make_conn(tmp_path):
    conn = db_mod.connect(str(tmp_path / "a.db"))
    db_mod.init_db(conn)
    return conn


def test_org_link_lifecycle(tmp_path):
    conn = make_conn(tmp_path)
    token = auth.issue_org_link(conn, "o@x.example")
    assert auth.redeem_org_link(conn, token) == "o@x.example"
    assert auth.redeem_org_link(conn, token) is None      # single use
    assert auth.redeem_org_link(conn, "nope") is None
    now = datetime.now(tz=timezone.utc)
    token = auth.issue_org_link(conn, "o@x.example", now=now)
    late = now + auth.TOKEN_TTL + timedelta(seconds=1)
    assert auth.redeem_org_link(conn, token, now=late) is None


def test_org_session_round_trip_and_rejections():
    value = auth.sign_org_session(PEPPER, 42)
    assert auth.verify_org_session(PEPPER, value) == 42
    assert auth.verify_org_session(secrets.token_bytes(32), value) is None
    assert auth.verify_org_session(PEPPER, "garbage") is None
    assert auth.verify_org_session(PEPPER, value[:-4] + "0000") is None
    now = datetime.now(tz=timezone.utc)
    old = auth.sign_org_session(PEPPER, 42, now=now - auth.ORG_SESSION_TTL - timedelta(days=1))
    assert auth.verify_org_session(PEPPER, old) is None
    # Validly signed but structurally wrong payloads.
    assert auth.verify_org_session(PEPPER, auth._sign(auth._org_key(PEPPER), b"not-numbers")) is None
    assert auth.verify_session(PEPPER, auth._sign(auth._session_key(PEPPER), b"a.b")) is None


def test_participant_session_expiry():
    now = datetime.now(tz=timezone.utc)
    old = auth.sign_session(PEPPER, 1, b"\x01" * 32, now=now - auth.SESSION_TTL - timedelta(hours=1))
    assert auth.verify_session(PEPPER, old) is None


# ---- db ---------------------------------------------------------------------


def test_create_cohort_validation(tmp_path):
    conn = make_conn(tmp_path)
    with pytest.raises(ValueError):
        db_mod.create_cohort(conn, "x", "X", ["a.example"], schedule="hourly")
    with pytest.raises(ValueError):
        db_mod.create_cohort(conn, "x", "X", ["a.example"], visibility="unlisted")
    with pytest.raises(ValueError):
        db_mod.create_cohort(conn, "x", "X", [])
    db_mod.init_db(conn)   # second init exercises the already-migrated path


# ---- rounds -----------------------------------------------------------------


def test_round_state_machine_edges(app, mailer):
    conn = connect(app)
    ks = app.state.keystore

    assert rounds.close_round(conn, ks, 999) == "missing"
    assert rounds.reveal_round(conn, ks, mailer, 999) == 0

    rid = rounds.latest_round(conn, COHORT)["id"]
    assert rounds.reveal_round(conn, ks, mailer, rid) == 0     # open, not closed
    rounds.void_round(conn, ks, rid)
    assert rounds.close_round(conn, ks, rid) == "voided"       # already terminal

    # Re-opening the same week is a no-op that must not mint a new key.
    again = rounds.open_round(conn, ks, COHORT)
    assert again == rid
    assert ks.load(rid) is None
    conn.close()


def test_reveal_skips_pair_with_missing_participant(app, mailer):
    """A reciprocal declaration pair whose participant rows are gone (a
    handle that never verified, a purged row) is skipped: nobody can be
    contacted, so nobody is."""
    conn = connect(app)
    rid = rounds.latest_round(conn, COHORT)["id"]
    a, b = handle(PEPPER, f"x@{DOMAIN}"), handle(PEPPER, f"y@{DOMAIN}")
    conn.execute("INSERT INTO declarations VALUES (?, ?, ?)", (rid, a, b))
    conn.execute("INSERT INTO declarations VALUES (?, ?, ?)", (rid, b, a))
    conn.execute("UPDATE rounds SET status = 'closed' WHERE id = ?", (rid,))
    conn.commit()
    assert rounds.reveal_round(conn, app.state.keystore, mailer, rid) == 0
    conn.close()
    assert all("/s/" in m.body for m in mailer.sent)   # only magic-link mail ever


def test_reveal_without_key_still_purges(app, mailer):
    conn = connect(app)
    rid = rounds.latest_round(conn, COHORT)["id"]
    conn.execute("UPDATE rounds SET status = 'closed' WHERE id = ?", (rid,))
    conn.commit()
    app.state.keystore.destroy(rid)
    assert rounds.reveal_round(conn, app.state.keystore, mailer, rid) == 0
    assert conn.execute("SELECT status FROM rounds WHERE id = ?", (rid,)).fetchone()["status"] == "revealed"
    conn.close()


def test_schedule_round_rejects_past(app):
    conn = connect(app)
    now = rounds.paris_now()
    db_mod.create_cohort(conn, "past", "Past", [DOMAIN], min_cohort=2, schedule="custom")
    with pytest.raises(ValueError):
        rounds.schedule_round(conn, app.state.keystore, "past",
                              now - timedelta(hours=2), now - timedelta(hours=1), now)
    conn.close()


def test_ensure_weekly_is_inert_on_weekends(app, mailer):
    conn = connect(app)
    now = rounds.paris_now()
    saturday = (now + timedelta(days=(5 - now.weekday()) % 7)).replace(hour=12, minute=0)
    before = conn.execute("SELECT COUNT(*) AS n FROM rounds").fetchone()["n"]
    rounds.ensure_weekly_rounds(conn, app.state.keystore, saturday)
    assert conn.execute("SELECT COUNT(*) AS n FROM rounds").fetchone()["n"] == before
    conn.close()


def test_tick_voids_scheduled_round_that_missed_its_window(app, mailer):
    """Scheduler outage across an entire event: nothing was collected,
    nothing runs, the round voids quietly."""
    conn = connect(app)
    now = rounds.paris_now()
    db_mod.create_cohort(conn, "missed", "Missed", [DOMAIN], min_cohort=2, schedule="custom")
    rid = rounds.schedule_round(
        conn, app.state.keystore, "missed",
        now + timedelta(minutes=10), now + timedelta(minutes=20), now + timedelta(minutes=30),
    )
    stats = rounds.tick(conn, app.state.keystore, mailer, now=now + timedelta(hours=2))
    assert stats["voided"] >= 1
    assert conn.execute("SELECT status FROM rounds WHERE id = ?", (rid,)).fetchone()["status"] == "voided"
    conn.close()


# ---- organizers -------------------------------------------------------------


def test_organizer_unit_edges(app):
    conn = connect(app)
    ks = app.state.keystore

    assert organizers.ban_organizer(conn, "ghost@x.example") == 0
    assert organizers.slugify(conn, "!!!").startswith("event-")
    assert organizers.cancel_event(conn, ks, "no-such-event") is None

    clean, errors = organizers._parse_config({
        "label": "ok", "description": "d" * 2001, "mail_intro": "m" * 501,
        "visibility": "unlisted", "min_cohort": "abc",
        "opens": "x", "closes": "x", "reveal": "x",
    })
    joined = " ".join(errors)
    assert "2000 characters" in joined and "500 characters" in joined
    assert "public or private" in joined and "threshold" in joined
    assert "not a valid date" in joined

    org = organizers.get_or_create_organizer(conn, "unit@x.example")
    assert organizers.get_or_create_organizer(conn, "unit@x.example")["id"] == org["id"]
    conn.close()


def form_for(now, **over):
    def t(minutes):
        return (now + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M")

    form = {
        "label": "Unit", "description": "", "mail_intro": "", "visibility": "private",
        "domains": DOMAIN, "join_code": "", "min_cohort": "2",
        "opens": t(-5), "closes": t(60), "reveal": t(120),
    }
    form.update(over)
    return form


def test_update_event_remaining_guardrails(app):
    conn = connect(app)
    ks = app.state.keystore
    pepper = app.state.settings.pepper
    now = rounds.paris_now()

    org = organizers.get_or_create_organizer(conn, "unit@x.example")
    event_id, errors = organizers.create_event(conn, ks, pepper, org["id"], form_for(now))
    assert errors == []
    cohort = conn.execute("SELECT * FROM cohorts WHERE id = ?", (event_id,)).fetchone()

    def t(minutes):
        return (now + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M")

    # Open round: reveal pulled before the (extended) close.
    errors = organizers.update_event(conn, ks, pepper, cohort,
                                     form_for(now, closes=t(90), reveal=t(80)))
    assert any("pulled earlier" in e or "precede" in e for e in errors)
    errors = organizers.update_event(conn, ks, pepper, cohort,
                                     form_for(now, closes=t(150), reveal=t(140)))
    assert any("cannot precede the close" in e for e in errors)

    # Closed round: only the reveal may move.
    conn.execute("UPDATE rounds SET status = 'closed' WHERE cohort_id = ?", (event_id,))
    conn.commit()
    errors = organizers.update_event(conn, ks, pepper, cohort,
                                     form_for(now, closes=t(70), reveal=t(120)))
    assert any("only the reveal time can still move" in e for e in errors)

    # Gate removal must not leave the event ungated.
    errors = organizers.update_event(conn, ks, pepper, cohort,
                                     form_for(now, domains="", remove_join_code="1"))
    assert any("join code, or both" in e for e in errors)

    # Scheduled round: broken timeline is rejected.
    conn.execute("UPDATE rounds SET status = 'scheduled' WHERE cohort_id = ?", (event_id,))
    conn.commit()
    errors = organizers.update_event(conn, ks, pepper, cohort,
                                     form_for(now, closes=t(200), reveal=t(150)))
    assert any("opens < closes" in e for e in errors)

    # No active round: config-only edits (and a join-code swap) apply.
    conn.execute("UPDATE rounds SET status = 'voided' WHERE cohort_id = ?", (event_id,))
    conn.commit()
    errors = organizers.update_event(conn, ks, pepper, cohort,
                                     form_for(now, label="Renamed", join_code="newcode"))
    assert errors == []
    updated = conn.execute("SELECT * FROM cohorts WHERE id = ?", (event_id,)).fetchone()
    assert updated["label"] == "Renamed"
    assert updated["join_code_hash"] is not None

    # schedule_new_round: active-round conflict, bad dates, past timeline.
    conn.execute("UPDATE rounds SET status = 'open' WHERE cohort_id = ?", (event_id,))
    conn.commit()
    assert organizers.schedule_new_round(conn, ks, event_id, form_for(now)) == \
        ["A round is already scheduled or running."]
    conn.execute("UPDATE rounds SET status = 'voided' WHERE cohort_id = ?", (event_id,))
    conn.commit()
    assert any("not a valid date" in e for e in
               organizers.schedule_new_round(conn, ks, event_id, {"opens": "x", "closes": "x", "reveal": "x"}))
    assert any("already be over" in e for e in
               organizers.schedule_new_round(conn, ks, event_id,
                                             form_for(now, opens=(now - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M"),
                                                      closes=(now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"),
                                                      reveal=(now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"))))

    # create_event: timeline rejection cleans up the cohort row.
    event2, errors = organizers.create_event(conn, ks, pepper, org["id"],
                                             form_for(now, closes=t(-60), reveal=t(-30)))
    assert event2 is None and errors
    conn.close()
