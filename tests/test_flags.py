"""Abuse flags: anonymous reporting, auto-suspension, silence under
suspension. A suspended event blocks joins and declarations, and a reveal
falling due while suspended voids — deleted, revealing nothing."""

from fastapi.testclient import TestClient

from conftest import DOMAIN, connect
from pli import organizers
from test_platform import create_event, event_signup, event_declare, tick

ALICE = f"alice@{DOMAIN}"
BOB = f"bob@{DOMAIN}"


def flag(app, event_id, ip, reason="spam", detail=""):
    conn = connect(app)
    try:
        organizers.flag_event(conn, app.state.settings.pepper, event_id, reason, detail, ip)
    finally:
        conn.close()


def suspended(app, event_id):
    conn = connect(app)
    try:
        return bool(conn.execute(
            "SELECT is_suspended FROM cohorts WHERE id = ?", (event_id,)
        ).fetchone()["is_suspended"])
    finally:
        conn.close()


def test_report_route_records_and_thanks(app, mailer):
    create_event(app, event_id="party")
    client = TestClient(app)
    assert "Report this event" in client.get("/e/party").text
    assert client.get("/e/party/report").status_code == 200
    resp = client.post("/e/party/report", data={"reason": "spam", "detail": "looks fake"})
    assert "Thank you" in resp.text
    assert client.get("/e/no-such/report").status_code == 404
    assert client.post("/e/no-such/report", data={"reason": "spam"}).status_code == 404

    conn = connect(app)
    row = conn.execute("SELECT * FROM flags").fetchone()
    conn.close()
    assert row["cohort_id"] == "party" and row["reason"] == "spam" and row["detail"] == "looks fake"


def test_one_reporter_cannot_suspend_alone(app, mailer):
    create_event(app, event_id="party")
    for _ in range(organizers.FLAG_SUSPEND_THRESHOLD + 2):
        flag(app, "party", "1.1.1.1")           # same reporter, deduplicated
    assert not suspended(app, "party")
    conn = connect(app)
    assert conn.execute("SELECT COUNT(*) AS n FROM flags").fetchone()["n"] == 1
    conn.close()


def test_threshold_suspends_and_suspension_means_silence(app, mailer):
    create_event(app, event_id="party")
    alice = event_signup(app, mailer, "party", ALICE)
    bob = event_signup(app, mailer, "party", BOB)
    event_declare(alice, "party", BOB)
    event_declare(bob, "party", ALICE)          # a mutual pair sits in escrow

    for i in range(organizers.FLAG_SUSPEND_THRESHOLD):
        flag(app, "party", f"10.0.0.{i}", reason="not-a-reason")  # coerced to 'other'
    assert suspended(app, "party")

    client = TestClient(app)
    assert "paused pending review" in client.get("/e/party").text

    # Joins are silent; sessions can't declare.
    sent_before = len(mailer.sent)
    client.post("/e/party/join", data={"email": f"carol@{DOMAIN}"})
    assert mailer.sent[sent_before:] == []
    resp = alice.get("/e/party/declare", follow_redirects=False)
    assert resp.status_code == 303

    # The reveal falls due while suspended: void, not reveal. Even the
    # mutual pair hears nothing — silence is the only safe null here too.
    tick(app, mailer, 121)
    assert mailer.sent[sent_before:] == []
    conn = connect(app)
    assert conn.execute(
        "SELECT status FROM rounds WHERE cohort_id = 'party' ORDER BY id DESC LIMIT 1"
    ).fetchone()["status"] == "voided"
    for table in ("declarations", "participants"):
        assert conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"] == 0
    conn.close()


def test_unsuspend_clears_flags(app, mailer):
    create_event(app, event_id="party")
    for i in range(organizers.FLAG_SUSPEND_THRESHOLD):
        flag(app, "party", f"10.0.0.{i}")
    assert suspended(app, "party")

    conn = connect(app)
    organizers.set_suspended(conn, "party", False)
    assert conn.execute("SELECT COUNT(*) AS n FROM flags").fetchone()["n"] == 0
    conn.close()
    assert not suspended(app, "party")


def test_directory_lists_only_approved_public_unsuspended(app, mailer):
    """The directory is a moderated greylist: public + approved +
    unsuspended, nothing else. Pending events stay reachable by link but
    invisible."""
    create_event(app, event_id="listed", domains=(DOMAIN,))
    create_event(app, event_id="hidden", domains=(DOMAIN,))
    create_event(app, event_id="pending", domains=(DOMAIN,))
    create_event(app, event_id="flagged", domains=(DOMAIN,))
    conn = connect(app)
    conn.execute(
        "UPDATE cohorts SET visibility = 'public' WHERE id IN ('listed', 'pending', 'flagged')"
    )
    conn.execute(
        "UPDATE cohorts SET listing_status = 'approved' WHERE id IN ('listed', 'flagged')"
    )
    conn.execute("UPDATE cohorts SET listing_status = 'pending' WHERE id = 'pending'")
    conn.commit()
    organizers.set_suspended(conn, "flagged", True)
    conn.close()

    page = TestClient(app).get("/events")
    assert "/e/listed" in page.text
    assert "/e/hidden" not in page.text       # private
    assert "/e/pending" not in page.text      # greylisted, not yet approved
    assert "/e/flagged" not in page.text      # suspended
    assert TestClient(app).get("/e/pending").status_code == 200   # link still works
