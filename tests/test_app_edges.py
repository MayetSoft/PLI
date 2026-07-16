"""HTTP-surface edge coverage: every silent branch stays silent, every
odd session is rejected, every path off the happy path behaves."""

import re
import secrets

from fastapi.testclient import TestClient

from conftest import COHORT, DOMAIN, connect, declare, signup
from pli import auth, db as db_mod, rounds
from pli.crypto import handle
from test_platform import create_event, event_signup

ALICE = f"alice@{DOMAIN}"


def test_lifespan_initializes_db(app):
    with TestClient(app):
        pass


def test_join_silent_branches(app, mailer):
    client = TestClient(app)
    sent = lambda: len(mailer.sent)  # noqa: E731

    # Per-address limit: the 4th request for the same address sends nothing.
    before = sent()
    for _ in range(4):
        client.post("/join", data={"email": ALICE})
    assert sent() - before == 3

    # Per-IP limit: the 6th join overall from this IP sends nothing.
    before = sent()
    client.post("/join", data={"email": f"bob@{DOMAIN}"})   # 5th this hour
    client.post("/join", data={"email": f"carol@{DOMAIN}"})  # 6th: rate-limited
    assert sent() - before == 1

    # The response never varies while any of that happens.
    r1 = client.post("/join", data={"email": ALICE})
    r2 = client.post("/join", data={"email": "zz@zz.example"})
    assert r1.content == r2.content


def test_join_with_no_open_round_is_silent(app, mailer):
    conn = connect(app)
    conn.execute("UPDATE rounds SET status = 'closed'")
    conn.commit()
    conn.close()
    before = len(mailer.sent)
    resp = TestClient(app).post("/join", data={"email": ALICE})
    assert "If that address is eligible" in resp.text
    assert len(mailer.sent) == before


def test_join_with_destroyed_round_key_is_silent(app, mailer):
    conn = connect(app)
    rid = rounds.latest_round(conn, COHORT)["id"]
    conn.close()
    app.state.keystore.destroy(rid)
    before = len(mailer.sent)
    resp = TestClient(app).post("/join", data={"email": ALICE})
    assert "If that address is eligible" in resp.text
    assert len(mailer.sent) == before


def test_declare_without_session_redirects(app, mailer):
    client = TestClient(app)
    assert client.get("/declare", follow_redirects=False).status_code == 303
    assert client.post("/declare", data={"targets": ALICE}, follow_redirects=False).status_code == 303
    # A cookie that is not even a valid signature.
    client.cookies.set("pli_session", "garbage")
    assert client.get("/declare", follow_redirects=False).status_code == 303


def test_join_internal_error_is_silent(app, mailer):
    """An address that passes the shape check but blows up normalisation
    must produce the same page and no mail."""
    before = len(mailer.sent)
    resp = TestClient(app).post("/join", data={"email": "+tag@x.example"})
    assert "If that address is eligible" in resp.text
    assert len(mailer.sent) == before


def test_declare_rejects_foreign_and_stale_sessions(app, mailer):
    create_event(app, event_id="conf")
    weekly = signup(app, mailer, ALICE)
    event_client = event_signup(app, mailer, "conf", f"bob@{DOMAIN}")

    # A weekly session presented on an event path is not a session there.
    weekly_cookie = weekly.cookies["pli_session"]
    stray = TestClient(app)
    stray.cookies.set("pli_s_conf", weekly_cookie)
    assert stray.get("/e/conf/declare", follow_redirects=False).status_code == 303

    # And vice versa: an event session is nothing at the root.
    stray = TestClient(app)
    stray.cookies.set("pli_session", event_client.cookies["pli_s_conf"])
    assert stray.get("/declare", follow_redirects=False).status_code == 303

    # A signed session for a non-participant handle is rejected.
    conn = connect(app)
    rid = rounds.latest_round(conn, COHORT)["id"]
    conn.close()
    forged = TestClient(app)
    forged.cookies.set(
        "pli_session",
        auth.sign_session(app.state.settings.pepper, rid, secrets.token_bytes(32)),
    )
    assert forged.get("/declare", follow_redirects=False).status_code == 303

    # A session for a round that has since terminated is rejected.
    conn = connect(app)
    conn.execute("UPDATE rounds SET status = 'revealed' WHERE id = ?", (rid,))
    conn.commit()
    conn.close()
    assert weekly.get("/declare", follow_redirects=False).status_code == 303


def test_declare_skips_malformed_targets_same_response(app, mailer):
    alice = signup(app, mailer, ALICE)
    ok = declare(alice, f"bob@{DOMAIN}")
    weird = declare(alice, "not-an-email", "+tagonly@x.example", "")
    assert ok.content == weird.content
    conn = connect(app)
    assert conn.execute("SELECT COUNT(*) AS n FROM declarations").fetchone()["n"] == 1
    conn.close()


def test_signin_edge_cases(app, mailer):
    client = TestClient(app)
    assert "no longer valid" in client.get("/s/garbage-token").text

    # A valid link whose round closed before it was clicked.
    client.post("/join", data={"email": ALICE})
    mail = next(m for m in reversed(mailer.sent) if "/s/" in m.body)
    token = re.search(r"/s/([A-Za-z0-9_\-]+)", mail.body).group(1)
    conn = connect(app)
    conn.execute("UPDATE rounds SET status = 'closed'")
    conn.commit()
    conn.close()
    assert "no longer valid" in client.get(f"/s/{token}").text


def test_weekly_cohort_served_under_event_path(app, mailer):
    conn = connect(app)
    db_mod.create_cohort(conn, "chess", "Chess", [DOMAIN], min_cohort=2)
    rounds.open_round(conn, app.state.keystore, "chess")
    conn.close()
    page = TestClient(app).get("/e/chess")
    assert "A round is open. It closes Friday at 23:59, Paris time." in page.text


def test_default_cohort_not_reachable_under_event_paths(app, mailer):
    client = TestClient(app)
    assert client.post(f"/e/{COHORT}/join", data={"email": ALICE}).status_code == 404
    assert client.get(f"/e/{COHORT}/declare").status_code == 404
    assert client.post(f"/e/{COHORT}/declare", data={"targets": ALICE}).status_code == 404
    assert client.post("/e/---/join", data={"email": ALICE}).status_code == 404
    assert client.get("/e/---/report").status_code == 404


def test_event_page_states(app, mailer):
    """Voided-with-nothing-scheduled and never-had-a-round pages."""
    create_event(app, event_id="conf")
    conn = connect(app)
    conn.execute("UPDATE rounds SET status = 'revealed' WHERE cohort_id = 'conf'")
    db_mod.create_cohort(conn, "empty", "Empty", [DOMAIN], min_cohort=2, schedule="custom")
    conn.commit()
    conn.close()
    client = TestClient(app)
    assert "has concluded" in client.get("/e/conf").text
    assert "No round is scheduled here yet" in client.get("/e/empty").text


def test_report_rate_limit(app, mailer):
    create_event(app, event_id="party")
    client = TestClient(app)
    for _ in range(6):
        resp = client.post("/e/party/report", data={"reason": "spam"})
        assert "Thank you" in resp.text        # response never varies
    conn = connect(app)
    n = conn.execute("SELECT COUNT(*) AS n FROM flags").fetchone()["n"]
    conn.close()
    assert n == 1   # one reporter, one flag, however hard they mash


def test_org_login_silent_branches(app, mailer):
    client = TestClient(app)
    assert client.get("/org").status_code == 200          # login page when signed out
    # Shape failure and an address whose normalisation raises.
    before = len(mailer.sent)
    client.post("/org/login", data={"email": "not-an-email"})
    client.post("/org/login", data={"email": "+tag@x.example"})
    assert len(mailer.sent) == before
    # Per-IP limit: 5/hour, and the two failures above already counted.
    for name in ("a", "b", "c", "d"):
        client.post("/org/login", data={"email": f"{name}@x.example"})
    assert len(mailer.sent) - before == 3                 # the 6th request was silent


def test_org_login_address_limit(app, mailer):
    client = TestClient(app)
    for _ in range(4):
        client.post("/org/login", data={"email": "busy@x.example"})
    assert len([m for m in mailer.sent if m.to == "busy@x.example"]) == 3


def test_org_edge_cases(app, mailer):
    from test_organizers import org_login, create_event_http

    assert "no longer valid" in TestClient(app).get("/org/s/garbage").text

    # A garbage organizer cookie is just "not signed in".
    stray = TestClient(app)
    stray.cookies.set("pli_org", "garbage")
    assert stray.get("/org/dashboard", follow_redirects=False).headers["location"] == "/org"

    org = org_login(app, mailer)
    assert org.get("/org", follow_redirects=False).headers["location"] == "/org/dashboard"
    assert org.get("/org/events/new").status_code == 200
    assert "No events yet" in org.get("/org/dashboard").text

    event_id, form = create_event_http(org)
    # Editing while suspended shows the pause notice.
    conn = connect(app)
    conn.execute("UPDATE cohorts SET is_suspended = 1 WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()
    assert "paused pending review" in org.get(f"/org/events/{event_id}/edit").text

    # New-round form errors re-render the edit page.
    resp = org.post(f"/org/events/{event_id}/round", data={"opens": "x", "closes": "x", "reveal": "x"})
    assert "already scheduled or running" in resp.text
    org.post(f"/org/events/{event_id}/cancel")
    resp = org.post(f"/org/events/{event_id}/round", data={"opens": "x", "closes": "x", "reveal": "x"})
    assert "not a valid date" in resp.text

    # A dashboard row for an event with no round at all.
    conn = connect(app)
    conn.execute("DELETE FROM rounds WHERE cohort_id = ?", (event_id,))
    conn.commit()
    conn.close()
    assert "No round yet" in org.get("/org/dashboard").text

    # Logout kills the session.
    resp = org.post("/org/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert org.get("/org/dashboard", follow_redirects=False).headers["location"] == "/org"

    # A banned organizer's magic link dies at redemption.
    conn = connect(app)
    from pli import organizers as org_mod
    org_mod.get_or_create_organizer(conn, "outlaw@x.example")
    org_mod.ban_organizer(conn, "outlaw@x.example")
    token = auth.issue_org_link(conn, "outlaw@x.example")
    conn.close()
    assert "no longer valid" in TestClient(app).get(f"/org/s/{token}").text
