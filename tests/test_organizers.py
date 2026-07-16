"""Self-serve organizers: auth, event CRUD, guardrails, isolation."""

import re
from datetime import timedelta

from fastapi.testclient import TestClient

from conftest import DOMAIN, connect
from pli import rounds
from test_platform import event_signup, event_declare, tick

ORG = "organizer@agency.example"
OTHER_ORG = "rival@agency.example"


def org_login(app, mailer, email=ORG):
    client = TestClient(app)
    client.post("/org/login", data={"email": email})
    mail = next(m for m in reversed(mailer.sent) if m.to == email and "/org/s/" in m.body)
    token = re.search(r"/org/s/([A-Za-z0-9_\-]+)", mail.body).group(1)
    resp = client.get(f"/org/s/{token}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/org/dashboard"
    return client


def event_form(opens_min=-5, closes_min=60, reveal_min=120, **over):
    now = rounds.paris_now()

    def t(minutes):
        return (now + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M")

    form = {
        "label": "DevConf",
        "description": "Business matchmaking at DevConf.",
        "mail_intro": "",
        "visibility": "private",
        "domains": DOMAIN,
        "join_code": "",
        "min_cohort": "2",
        "opens": t(opens_min),
        "closes": t(closes_min),
        "reveal": t(reveal_min),
    }
    form.update(over)
    return form


def create_event_http(client, **over):
    form = event_form(**over)
    resp = client.post("/org/events", data=form, follow_redirects=False)
    assert resp.status_code == 303, resp.text
    event_id = re.fullmatch(r"/org/events/([a-z0-9-]+)/edit", resp.headers["location"]).group(1)
    return event_id, form


def test_full_organizer_lifecycle(app, mailer):
    """Sign in, create, see the share URL, run the round end to end."""
    org = org_login(app, mailer)
    event_id, _ = create_event_http(org, mail_intro="See you at the closing party.")

    dashboard = org.get("/org/dashboard")
    assert f"/e/{event_id}" in dashboard.text          # url to circulate
    assert "0 signed up" in dashboard.text

    page = TestClient(app).get(f"/e/{event_id}")
    assert "Business matchmaking at DevConf." in page.text   # custom page
    assert "Report this event" in page.text

    a = event_signup(app, mailer, event_id, f"alice@{DOMAIN}")
    b = event_signup(app, mailer, event_id, f"bob@{DOMAIN}")
    # The organizer note rides inside the platform template, attributed.
    link_mail = next(m for m in reversed(mailer.sent) if "/s/" in m.body)
    assert "A note from the organizer:" in link_mail.body
    assert "See you at the closing party." in link_mail.body

    assert "2 signed up" in org.get("/org/dashboard").text
    # Count, and nothing but the count: no address appears anywhere.
    assert f"alice@{DOMAIN}" not in org.get("/org/dashboard").text

    event_declare(a, event_id, f"bob@{DOMAIN}")
    event_declare(b, event_id, f"alice@{DOMAIN}")
    sent_before = len(mailer.sent)
    tick(app, mailer, 121)
    match_mails = mailer.sent[sent_before:]
    assert {m.to for m in match_mails} == {f"alice@{DOMAIN}", f"bob@{DOMAIN}"}
    assert all("See you at the closing party." in m.body for m in match_mails)


def test_org_login_is_not_enumerable(app, mailer):
    client = TestClient(app)
    r_new = client.post("/org/login", data={"email": "new@x.example"})
    r_garbage = client.post("/org/login", data={"email": "not-an-email"})
    assert r_new.status_code == r_garbage.status_code
    assert r_new.content == r_garbage.content


def test_org_routes_require_session(app, mailer):
    client = TestClient(app)
    for path in ("/org/dashboard", "/org/events/new", "/org/events/x/edit"):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 303 and resp.headers["location"] == "/org"
    for path, data in (
        ("/org/events", event_form()),
        ("/org/events/x/edit", event_form()),
        ("/org/events/x/cancel", {}),
        ("/org/events/x/round", {}),
    ):
        resp = client.post(path, data=data, follow_redirects=False)
        assert resp.status_code == 303 and resp.headers["location"] == "/org"


def test_create_validation(app, mailer):
    org = org_login(app, mailer)
    # No gate at all.
    resp = org.post("/org/events", data=event_form(domains="", join_code=""))
    assert "email-domain restriction, a join code, or both" in resp.text
    # Reveal before close.
    resp = org.post("/org/events", data=event_form(closes_min=120, reveal_min=60))
    assert "opens &lt; closes" in resp.text or "opens < closes" in resp.text
    # Bad timestamp, bad threshold, bad domain, oversized label.
    resp = org.post("/org/events", data=event_form(opens="whenever", min_cohort="1",
                                                   domains="not a domain", label="x" * 101))
    assert "not a valid date" in resp.text
    assert "threshold must be at least" in resp.text
    assert "not a valid domain" in resp.text
    assert "at most 100 characters" in resp.text


def test_edit_scheduled_round_is_free(app, mailer):
    org = org_login(app, mailer)
    event_id, form = create_event_http(org, opens_min=30, closes_min=90, reveal_min=120)
    form.update(event_form(opens_min=40, closes_min=100, reveal_min=130,
                           label="DevConf renamed", visibility="public", min_cohort="5"))
    resp = org.post(f"/org/events/{event_id}/edit", data=form, follow_redirects=False)
    assert resp.status_code == 303

    conn = connect(app)
    cohort = conn.execute("SELECT * FROM cohorts WHERE id = ?", (event_id,)).fetchone()
    assert cohort["label"] == "DevConf renamed"
    assert cohort["visibility"] == "public"
    assert cohort["min_cohort"] == 5
    conn.close()


def test_edit_open_round_guardrails(app, mailer):
    """Once open: opens is fixed, closes/reveal extend-only, threshold frozen."""
    org = org_login(app, mailer)
    event_id, form = create_event_http(org)   # opens 5 minutes ago → open

    pull_earlier = {**form, "closes": event_form(closes_min=30)["closes"]}
    resp = org.post(f"/org/events/{event_id}/edit", data=pull_earlier)
    assert "never pulled earlier" in resp.text

    move_opens = {**form, "opens": event_form(opens_min=-1)["opens"]}
    resp = org.post(f"/org/events/{event_id}/edit", data=move_opens)
    assert "opening time is in the past and fixed" in resp.text

    change_threshold = {**form, "min_cohort": "3"}
    resp = org.post(f"/org/events/{event_id}/edit", data=change_threshold)
    assert "freezes once the round opens" in resp.text

    extend = {**form, "closes": event_form(closes_min=90)["closes"],
              "reveal": event_form(reveal_min=150)["reveal"]}
    resp = org.post(f"/org/events/{event_id}/edit", data=extend, follow_redirects=False)
    assert resp.status_code == 303


def test_edit_closed_round_only_reveal_extends(app, mailer):
    org = org_login(app, mailer)
    event_id, form = create_event_http(org, min_cohort="2")
    event_signup(app, mailer, event_id, f"alice@{DOMAIN}")
    event_signup(app, mailer, event_id, f"bob@{DOMAIN}")
    tick(app, mailer, 61)   # closes

    earlier_reveal = {**form, "reveal": event_form(reveal_min=90)["reveal"]}
    resp = org.post(f"/org/events/{event_id}/edit", data=earlier_reveal)
    assert "only be pushed later" in resp.text

    later_reveal = {**form, "reveal": event_form(reveal_min=180)["reveal"]}
    resp = org.post(f"/org/events/{event_id}/edit", data=later_reveal, follow_redirects=False)
    assert resp.status_code == 303


def test_cancel_voids_and_new_round_starts_clean(app, mailer):
    org = org_login(app, mailer)
    event_id, _ = create_event_http(org)
    a = event_signup(app, mailer, event_id, f"alice@{DOMAIN}")
    event_declare(a, event_id, f"bob@{DOMAIN}")

    sent_before = len(mailer.sent)
    resp = org.post(f"/org/events/{event_id}/cancel", follow_redirects=False)
    assert resp.status_code == 303
    assert mailer.sent[sent_before:] == []          # cancellation is silent

    conn = connect(app)
    assert conn.execute(
        "SELECT status FROM rounds WHERE cohort_id = ? ORDER BY id DESC LIMIT 1", (event_id,)
    ).fetchone()["status"] == "voided"
    for table in ("declarations", "participants"):
        assert conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"] == 0
    conn.close()

    # Schedule a fresh round on the same event.
    resp = org.post(f"/org/events/{event_id}/round",
                    data={k: event_form(opens_min=10, closes_min=70, reveal_min=100)[k]
                          for k in ("opens", "closes", "reveal")},
                    follow_redirects=False)
    assert resp.status_code == 303
    conn = connect(app)
    assert conn.execute(
        "SELECT status FROM rounds WHERE cohort_id = ? ORDER BY id DESC LIMIT 1", (event_id,)
    ).fetchone()["status"] == "scheduled"
    conn.close()


def test_ownership_is_enforced(app, mailer):
    org = org_login(app, mailer)
    event_id, form = create_event_http(org)
    rival = org_login(app, mailer, OTHER_ORG)
    assert rival.get(f"/org/events/{event_id}/edit").status_code == 404
    assert rival.post(f"/org/events/{event_id}/edit", data=form).status_code == 404
    assert rival.post(f"/org/events/{event_id}/cancel").status_code == 404
    assert rival.post(f"/org/events/{event_id}/round", data=form).status_code == 404


def test_banned_organizer_is_locked_out(app, mailer):
    from pli import organizers as org_mod

    org = org_login(app, mailer)
    event_id, _ = create_event_http(org)

    conn = connect(app)
    n = org_mod.ban_organizer(conn, ORG)
    assert n == 1
    conn.close()

    # Existing session dies, events are suspended, new links are silent.
    resp = org.get("/org/dashboard", follow_redirects=False)
    assert resp.status_code == 303
    assert "paused" in TestClient(app).get(f"/e/{event_id}").text
    sent_before = len(mailer.sent)
    TestClient(app).post("/org/login", data={"email": ORG})
    assert mailer.sent[sent_before:] == []
