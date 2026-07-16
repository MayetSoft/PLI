"""Events: cohorts with their own timeline, served at /e/{id}.

The invariants are not re-negotiated for events — same handlers, same
escrow, same reveal job. These tests cover what is new: the custom
timeline state machine, event isolation, join codes, and that the default
community at the root is untouched (the whole original suite also proves
that: it runs against the root routes unmodified).
"""

import re
from datetime import timedelta

from fastapi.testclient import TestClient

from conftest import COHORT, DOMAIN, connect, declare, signup
from pli import db as db_mod
from pli import rounds
from pli.crypto import handle
from pli.normalize import normalise_email

ALICE = f"alice@{DOMAIN}"
BOB = f"bob@{DOMAIN}"


def create_event(
    app,
    event_id="devconf",
    domains=(DOMAIN,),
    join_code=None,
    min_cohort=2,
    opens_min=-5,
    closes_min=60,
    reveal_min=120,
):
    """Event whose round opens/closes/reveals at offsets (minutes) from now."""
    conn = connect(app)
    try:
        code_hash = (
            handle(app.state.settings.pepper, "code:" + join_code) if join_code else None
        )
        db_mod.create_cohort(
            conn, event_id, "Test event", list(domains), min_cohort,
            schedule="custom", join_code_hash=code_hash,
        )
        now = rounds.paris_now()
        return rounds.schedule_round(
            conn, app.state.keystore, event_id,
            now + timedelta(minutes=opens_min),
            now + timedelta(minutes=closes_min),
            now + timedelta(minutes=reveal_min),
        )
    finally:
        conn.close()


def event_signup(app, mailer, event_id, email, code=None):
    client = TestClient(app)
    data = {"email": email}
    if code is not None:
        data["code"] = code
    client.post(f"/e/{event_id}/join", data=data)
    norm = normalise_email(email)
    mail = next(m for m in reversed(mailer.sent) if m.to == norm and "/s/" in m.body)
    token = re.search(r"/s/([A-Za-z0-9_\-]+)", mail.body).group(1)
    resp = client.get(f"/s/{token}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/e/{event_id}/declare"
    return client


def event_declare(client, event_id, *targets):
    return client.post(f"/e/{event_id}/declare", data={"targets": list(targets)})


def tick(app, mailer, minutes_from_now):
    conn = connect(app)
    try:
        return rounds.tick(
            conn, app.state.keystore, mailer,
            now=rounds.paris_now() + timedelta(minutes=minutes_from_now),
        )
    finally:
        conn.close()


def round_status(app, rid):
    conn = connect(app)
    try:
        return conn.execute("SELECT status FROM rounds WHERE id = ?", (rid,)).fetchone()["status"]
    finally:
        conn.close()


def test_event_runs_on_its_own_timeline(app, mailer):
    """A two-hour event: open now, close at +60min, reveal at +120min —
    close and reveal happen when the clock says so, not on a weekday."""
    rid = create_event(app, closes_min=60, reveal_min=120)
    alice = event_signup(app, mailer, "devconf", ALICE)
    bob = event_signup(app, mailer, "devconf", BOB)
    event_declare(alice, "devconf", BOB)
    event_declare(bob, "devconf", ALICE)

    sent_before = len(mailer.sent)
    tick(app, mailer, 61)                       # past close, before reveal
    assert round_status(app, rid) == "closed"
    assert mailer.sent[sent_before:] == []      # closing emits nothing (I5)

    tick(app, mailer, 121)                      # past reveal
    assert round_status(app, rid) == "revealed"
    assert {m.to for m in mailer.sent[sent_before:]} == {ALICE, BOB}

    conn = connect(app)
    for table in ("declarations", "participants", "magic_links"):
        assert conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE round_id = ?", (rid,)).fetchone()["n"] == 0
    conn.close()
    assert app.state.keystore.load(rid) is None


def test_scheduled_event_is_inert_until_it_opens(app, mailer):
    """Before opens_at the round exists but nothing works: joining is
    silent, and the tick opens it only once the time comes."""
    rid = create_event(app, event_id="later", opens_min=30, closes_min=90, reveal_min=120)
    assert round_status(app, rid) == "scheduled"

    page = TestClient(app).get("/e/later")
    assert "The round opens" in page.text

    sent_before = len(mailer.sent)
    resp = TestClient(app).post("/e/later/join", data={"email": ALICE})
    assert "If that address is eligible" in resp.text   # same page as ever
    assert mailer.sent[sent_before:] == []              # ...but silence

    tick(app, mailer, 0)
    assert round_status(app, rid) == "scheduled"        # not yet
    tick(app, mailer, 31)
    assert round_status(app, rid) == "open"


def test_event_under_threshold_voids(app, mailer):
    rid = create_event(app, event_id="quiet", min_cohort=10, closes_min=60, reveal_min=120)
    alice = event_signup(app, mailer, "quiet", ALICE)
    bob = event_signup(app, mailer, "quiet", BOB)
    event_declare(alice, "quiet", BOB)
    event_declare(bob, "quiet", ALICE)          # mutual — must still never surface

    sent_before = len(mailer.sent)
    tick(app, mailer, 61)
    assert round_status(app, rid) == "voided"
    tick(app, mailer, 121)
    assert mailer.sent[sent_before:] == []

    page = TestClient(app).get("/e/quiet")
    assert "did not reach its threshold" in page.text


def test_rounds_are_isolated_across_events(app, mailer):
    """Reciprocity across two different rounds is not reciprocity.
    alice→bob in the event, bob→alice in the weekly round: no match
    anywhere, ever."""
    create_event(app, event_id="conf", closes_min=60, reveal_min=120)
    alice_event = event_signup(app, mailer, "conf", ALICE)
    event_signup(app, mailer, "conf", BOB)
    alice_weekly = signup(app, mailer, ALICE)   # default community, root routes
    bob_weekly = signup(app, mailer, BOB)

    event_declare(alice_event, "conf", BOB)     # event: alice → bob only
    declare(bob_weekly, ALICE)                  # weekly: bob → alice only
    declare(alice_weekly, f"carol@{DOMAIN}")    # noise

    sent_before = len(mailer.sent)
    tick(app, mailer, 121)                      # event closes and reveals

    from conftest import close_round, reveal_round
    close_round(app)                            # weekly round, original path
    reveal_round(app, mailer)

    assert mailer.sent[sent_before:] == []      # no pair existed in any single round


def test_join_code_gates_without_leaking(app, mailer):
    """Wrong code and right code return byte-identical pages (I8); only
    the right code produces a magic link. No shared domain required."""
    create_event(app, event_id="mixer", domains=(), join_code="sesame", closes_min=60, reveal_min=90)

    sent_before = len(mailer.sent)
    r_wrong = TestClient(app).post("/e/mixer/join", data={"email": "p1@corp.example", "code": "guess"})
    assert mailer.sent[sent_before:] == []
    r_right = TestClient(app).post("/e/mixer/join", data={"email": "p2@corp.example", "code": "sesame"})
    assert [m.to for m in mailer.sent[sent_before:]] == ["p2@corp.example"]

    assert r_wrong.status_code == r_right.status_code
    assert r_wrong.content == r_right.content

    # Full flow works on an arbitrary-domain event.
    p2 = event_signup(app, mailer, "mixer", "p3@other.example", code="sesame")
    resp = event_declare(p2, "mixer", "p1@corp.example")
    assert "Recorded" in resp.text


def test_default_root_is_untouched_and_events_are_separate_paths(app, mailer):
    """The default community keeps its root URLs; its cohort id under /e/
    redirects home; unknown events 404."""
    client = TestClient(app)
    assert client.get(f"/e/{COHORT}", follow_redirects=False).status_code == 303
    assert client.get(f"/e/{COHORT}", follow_redirects=False).headers["location"] == "/"
    assert client.get("/e/no-such-event").status_code == 404
    assert client.get("/e/Bad_ID!").status_code == 404

    page = client.get("/")
    assert "A round is open. It closes Friday at 23:59, Paris time." in page.text


def test_weekly_cohorts_autocreate_via_tick(app, mailer):
    """The tick keeps the original weekly cadence for every weekly cohort
    with no per-cohort cron entries."""
    conn = connect(app)
    db_mod.create_cohort(conn, "chess-club", "Chess club", [DOMAIN], min_cohort=2)

    now = rounds.paris_now()
    wednesday = (now + timedelta(days=(2 - now.weekday()) % 7)).replace(
        hour=12, minute=0, second=0, microsecond=0
    )
    rounds.tick(conn, app.state.keystore, mailer, now=wednesday)
    row = rounds.current_open_round(conn, "chess-club")
    conn.close()
    assert row is not None
    assert row["status"] == "open"


def test_custom_timeline_validation(app):
    """A reveal before close would be a mid-round signal. Rejected."""
    import pytest

    conn = connect(app)
    db_mod.create_cohort(conn, "bad", "Bad", [DOMAIN], schedule="custom", min_cohort=2)
    now = rounds.paris_now()
    with pytest.raises(ValueError):
        rounds.schedule_round(
            conn, app.state.keystore, "bad",
            now, now + timedelta(hours=2), now + timedelta(hours=1),
        )
    with pytest.raises(ValueError):
        rounds.schedule_round(
            conn, app.state.keystore, "bad",
            now - timedelta(hours=3), now - timedelta(hours=1), now + timedelta(hours=1),
        )
    conn.close()
