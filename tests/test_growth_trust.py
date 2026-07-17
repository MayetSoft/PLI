"""iCal feed, QR poster, widget auto-resize, custom domains, outbound
webhooks, transparency page, and SSO attestation."""

import dataclasses
import hashlib
import hmac
import io
import json

from fastapi.testclient import TestClient

from conftest import COHORT, DOMAIN, connect
from pli import rounds, sso, webhooks
from pli.app import create_app
from test_platform import create_event, tick

ALICE = f"alice@{DOMAIN}"


# ---- iCal -------------------------------------------------------------------


def test_calendar_feed(app, mailer):
    create_event(app, event_id="conf")
    resp = TestClient(app).get("/e/conf/calendar.ics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/calendar")
    body = resp.text
    assert "BEGIN:VCALENDAR" in body and body.count("BEGIN:VEVENT") == 2
    assert "declarations open" in body and "reveal" in body

    # Terminal rounds publish an empty calendar; unknown events 404.
    conn = connect(app)
    conn.execute("UPDATE rounds SET status = 'revealed' WHERE cohort_id = 'conf'")
    conn.commit()
    conn.close()
    assert TestClient(app).get("/e/conf/calendar.ics").text.count("BEGIN:VEVENT") == 0
    assert TestClient(app).get("/e/none/calendar.ics").status_code == 404
    assert TestClient(app).get(f"/e/{COHORT}/calendar.ics").status_code == 404


def test_calendar_escapes_label(app, mailer):
    create_event(app, event_id="conf")
    conn = connect(app)
    conn.execute("UPDATE cohorts SET label = 'Comma, semi; slash\\\\' WHERE id = 'conf'")
    conn.commit()
    conn.close()
    body = TestClient(app).get("/e/conf/calendar.ics").text
    assert "Comma\\, semi\\; slash\\\\" in body


# ---- poster -----------------------------------------------------------------


def test_poster(app, mailer):
    create_event(app, event_id="party")
    page = TestClient(app).get("/e/party/poster")
    assert page.status_code == 200
    assert "<svg" in page.text                       # QR inline
    assert "/e/party" in page.text                   # the URL under the code
    assert "Test event" in page.text
    assert TestClient(app).get("/e/none/poster").status_code == 404

    conn = connect(app)
    conn.execute("UPDATE cohorts SET is_suspended = 1 WHERE id = 'party'")
    conn.commit()
    conn.close()
    assert TestClient(app).get("/e/party/poster").status_code == 404


# ---- widget auto-resize -------------------------------------------------------


def test_embed_script_served_and_referenced(app, mailer):
    create_event(app, event_id="conf")
    script = TestClient(app).get("/static/pli-embed.js")
    assert script.status_code == 200
    assert "postMessage" in script.text
    assert "text/javascript" in script.headers["content-type"]
    widget = TestClient(app).get("/e/conf/widget")
    assert "/static/pli-embed.js" in widget.text


# ---- custom domains -----------------------------------------------------------


def test_custom_domain_serves_event_at_root(app, mailer):
    create_event(app, event_id="conf")
    conn = connect(app)
    conn.execute("UPDATE cohorts SET custom_domain = 'pact.conf.example' WHERE id = 'conf'")
    conn.commit()
    conn.close()

    client = TestClient(app)
    home = client.get("/", headers={"host": "pact.conf.example"})
    assert "Test event" in home.text                 # event page at the root

    before = len(mailer.sent)
    client.post("/join", data={"email": ALICE}, headers={"host": "pact.conf.example"})
    assert mailer.sent[-1].to == ALICE and len(mailer.sent) == before + 1

    widget = client.get("/widget", headers={"host": "pact.conf.example"})
    assert "frame-ancestors *" in widget.headers["content-security-policy"]

    # Unknown hosts fall through to the platform; platform paths never rewrite.
    landing = client.get("/", headers={"host": "unrelated.example"})
    assert "A round is open. It closes Friday" in landing.text   # default community
    org = client.get("/org", headers={"host": "pact.conf.example"})
    assert "Organizers" in org.text


def test_custom_domain_validation_and_uniqueness(app, mailer):
    from test_organizers import create_event_http, event_form, org_login

    org = org_login(app, mailer)
    event_id, form = create_event_http(org)
    resp = org.post(f"/org/events/{event_id}/edit",
                    data={**form, "custom_domain": "not a host"})
    assert "not a valid host name" in resp.text
    resp = org.post(f"/org/events/{event_id}/edit",
                    data={**form, "custom_domain": "pact.one.example"},
                    follow_redirects=False)
    assert resp.status_code == 303

    event2, form2 = create_event_http(org)
    resp = org.post(f"/org/events/{event2}/edit",
                    data={**form2, "custom_domain": "pact.one.example"})
    assert "already in use" in resp.text
    resp = org.post(f"/org/events/{event2}/edit",
                    data={**form2, "webhook_url": "http://insecure.example/hook"})
    assert "must use https" in resp.text

    # Creating a new event straight onto a taken domain rolls the row back.
    resp = org.post("/org/events", data=event_form(custom_domain="pact.one.example"))
    assert "already in use" in resp.text
    conn = connect(app)
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM cohorts WHERE custom_domain = 'pact.one.example'"
    ).fetchone()["n"] == 1
    conn.close()

    # A valid https webhook mints a signing secret, shown on the edit page.
    resp = org.post(f"/org/events/{event2}/edit",
                    data={**form2, "webhook_url": "https://org.example/hook"},
                    follow_redirects=False)
    assert resp.status_code == 303
    page = org.get(f"/org/events/{event2}/edit").text
    assert "Signature secret" in page


def test_custom_domain_is_pro_when_billing_enforced(settings, mailer):
    from test_billing import billing_app
    from test_organizers import event_form, org_login

    application = billing_app(settings, mailer)
    org = org_login(application, mailer)
    resp = org.post("/org/events", data=event_form(custom_domain="pact.x.example"))
    assert "pro plan" in resp.text


# ---- outbound webhooks ----------------------------------------------------------


def test_webhook_notify_signs_and_posts(app, mailer):
    create_event(app, event_id="conf")
    conn = connect(app)
    conn.execute(
        "UPDATE cohorts SET webhook_url = 'https://org.example/hook',"
        " webhook_secret = 'sekrit' WHERE id = 'conf'"
    )
    conn.commit()

    captured = {}

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = request.data
        captured["sig"] = request.get_header("X-pli-signature")
        return FakeResponse(b"")

    assert webhooks.notify(conn, "conf", 42, "closed", opener=opener) is True
    payload = json.loads(captured["body"])
    assert payload == {"event": "conf", "round": 42, "status": "closed"}
    expected = hmac.new(b"sekrit", captured["body"], hashlib.sha256).hexdigest()
    assert captured["sig"] == expected

    # No URL, bad status, delivery error: all quietly non-events.
    assert webhooks.notify(conn, COHORT, 1, "closed", opener=opener) is False
    assert webhooks.notify(conn, "conf", 1, "not-a-status", opener=opener) is False

    def exploding(request, timeout):
        raise ConnectionError("down")

    assert webhooks.notify(conn, "conf", 1, "revealed", opener=exploding) is True
    conn.close()


def test_tick_fires_webhooks_per_transition(app, mailer):
    create_event(app, event_id="conf", min_cohort=10)   # will void at close
    fired = []
    conn = connect(app)
    rounds.tick(conn, app.state.keystore, mailer,
                now=rounds.paris_now() + rounds.timedelta(minutes=61),
                notify=lambda c, r, s: fired.append((c, s)))
    conn.close()
    assert ("conf", "voided") in fired

    # A raising notifier never blocks the lifecycle.
    create_event(app, event_id="conf2", opens_min=30, closes_min=90, reveal_min=120)
    conn = connect(app)

    def bomb(c, r, s):
        raise RuntimeError("listener broken")

    stats = rounds.tick(conn, app.state.keystore, mailer,
                        now=rounds.paris_now() + rounds.timedelta(minutes=31),
                        notify=bomb)
    conn.close()
    assert stats["opened"] >= 1


def test_cancel_fires_webhook(app, mailer, monkeypatch):
    from test_organizers import create_event_http, org_login

    fired = []
    monkeypatch.setattr(
        "pli.app.webhooks.notify",
        lambda conn, c, r, s, opener=None: fired.append((c, s)) or True,
    )
    org = org_login(app, mailer)
    event_id, _ = create_event_http(org)
    org.post(f"/org/events/{event_id}/cancel")
    assert fired == [(event_id, "voided")]


# ---- transparency ---------------------------------------------------------------


def test_transparency_page(settings, mailer, app):
    unconfigured = TestClient(app).get("/transparency")
    assert "not configured" in unconfigured.text

    s = dataclasses.replace(
        settings, build_commit="abc123", image_digest="sha256:feed",
        canary_updated="2026-07-01", transparency_requests="0",
        company_name="Plicorp SASU",
    )
    page = TestClient(create_app(settings=s, mailer=mailer)).get("/transparency")
    assert "abc123" in page.text and "sha256:feed" in page.text
    assert "2026-07-01" in page.text and "Plicorp SASU" in page.text
    # Linked from every footer.
    assert "/transparency" in TestClient(app).get("/").text


# ---- SSO attestation --------------------------------------------------------------


DISCOVERY = {
    "authorization_endpoint": "https://idp.example/authorize",
    "token_endpoint": "https://idp.example/token",
    "userinfo_endpoint": "https://idp.example/userinfo",
}


def fake_idp(email="member@etu.example", verified=True, fail=None):
    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def opener(request, timeout):
        url = request.full_url
        if fail == "network":
            raise ConnectionError("down")
        if "openid-configuration" in url:
            return FakeResponse(json.dumps(DISCOVERY).encode())
        if url.startswith("https://idp.example/token"):
            return FakeResponse(json.dumps({"access_token": "tok"}).encode())
        info = {"email": email}
        if verified is not None:
            info["email_verified"] = verified
        return FakeResponse(json.dumps(info).encode())

    return opener


def sso_cohort(app, event_id="uni"):
    create_event(app, event_id=event_id)
    conn = connect(app)
    conn.execute(
        "UPDATE cohorts SET oidc_issuer = 'https://idp.example',"
        " oidc_client_id = 'pli-client', oidc_client_secret = 's3' WHERE id = ?",
        (event_id,),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM cohorts WHERE id = ?", (event_id,)).fetchone()
    conn.close()
    return row


def test_sso_unit_flow(app):
    cohort = sso_cohort(app)
    pepper = app.state.settings.pepper

    url = sso.auth_url(cohort, pepper, "https://pli.example/oidc/callback", opener=fake_idp())
    assert url.startswith("https://idp.example/authorize?")
    assert "client_id=pli-client" in url and "state=" in url

    state = sso.sign_state(pepper, "uni")
    assert sso.verify_state(pepper, state) == "uni"
    assert sso.verify_state(pepper, "garbage") is None
    assert sso.verify_state(b"x" * 32, state) is None
    stale = sso.sign_state(pepper, "uni", now=0)
    assert sso.verify_state(pepper, stale) is None

    assert sso.fetch_verified_email(
        cohort, "code", "https://cb", opener=fake_idp()
    ) == "member@etu.example"
    assert sso.fetch_verified_email(
        cohort, "code", "https://cb", opener=fake_idp(verified=False)
    ) is None
    assert sso.fetch_verified_email(
        cohort, "code", "https://cb", opener=fake_idp(email="")
    ) is None
    assert sso.fetch_verified_email(
        cohort, "code", "https://cb", opener=fake_idp(fail="network")
    ) is None


def test_sso_http_flow(app, mailer, monkeypatch):
    sso_cohort(app)
    monkeypatch.setattr("pli.sso.urllib.request.urlopen", fake_idp())

    client = TestClient(app)
    redirect = client.get("/e/uni/sso", follow_redirects=False)
    assert redirect.status_code == 303
    assert redirect.headers["location"].startswith("https://idp.example/authorize")

    state = sso.sign_state(app.state.settings.pepper, "uni")
    landed = client.get(f"/oidc/callback?code=abc&state={state}", follow_redirects=False)
    assert landed.status_code == 303
    assert landed.headers["location"] == "/e/uni/declare"

    # Member is now a participant, sealed like anyone else; no mail was sent.
    conn = connect(app)
    round_row = rounds.current_open_round(conn, "uni")
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM participants WHERE round_id = ?", (round_row["id"],)
    ).fetchone()["n"]
    conn.close()
    assert n == 1
    assert all("member@etu.example" != m.to for m in mailer.sent)

    # And the session actually works.
    assert "You may name up to three people" in client.get("/e/uni/declare").text


def test_sso_rejections(app, mailer, monkeypatch):
    sso_cohort(app)
    client = TestClient(app)
    pepper = app.state.settings.pepper

    assert client.get("/e/no-such/sso").status_code == 404
    create_event(app, event_id="plain")                    # no SSO configured
    assert client.get("/e/plain/sso").status_code == 404

    # Issuer down at the redirect step.
    monkeypatch.setattr("pli.sso.urllib.request.urlopen", fake_idp(fail="network"))
    assert "no longer valid" in client.get("/e/uni/sso").text

    # Callback with bad state / missing code / unverified email.
    assert "no longer valid" in client.get("/oidc/callback?code=x&state=bad").text
    good_state = sso.sign_state(pepper, "uni")
    assert "no longer valid" in client.get(f"/oidc/callback?state={good_state}").text
    monkeypatch.setattr("pli.sso.urllib.request.urlopen", fake_idp(verified=False))
    good_state = sso.sign_state(pepper, "uni")
    assert "no longer valid" in client.get(f"/oidc/callback?code=x&state={good_state}").text

    # Round no longer open at callback time.
    monkeypatch.setattr("pli.sso.urllib.request.urlopen", fake_idp())
    conn = connect(app)
    conn.execute("UPDATE rounds SET status = 'closed' WHERE cohort_id = 'uni'")
    conn.commit()
    conn.close()
    good_state = sso.sign_state(pepper, "uni")
    assert "no longer valid" in client.get(f"/oidc/callback?code=x&state={good_state}").text
    conn = connect(app)
    conn.execute("UPDATE rounds SET status = 'open' WHERE cohort_id = 'uni'")
    conn.commit()
    rid = rounds.current_open_round(conn, "uni")["id"]
    conn.close()

    # Round key destroyed mid-round: the round is doomed, sign-in refuses.
    app.state.keystore.destroy(rid)
    good_state = sso.sign_state(pepper, "uni")
    assert "no longer valid" in client.get(f"/oidc/callback?code=x&state={good_state}").text
    app.state.keystore.create(rid)

    # State for a cohort that vanished, or a suppressed member.
    ghost_state = sso.sign_state(pepper, "gone-cohort")
    assert "no longer valid" in client.get(f"/oidc/callback?code=x&state={ghost_state}").text
    from pli import suppression

    conn = connect(app)
    suppression.suppress(conn, pepper, "member@etu.example", "complaint")
    conn.close()
    monkeypatch.setattr("pli.sso.urllib.request.urlopen", fake_idp())
    good_state = sso.sign_state(pepper, "uni")
    assert "no longer valid" in client.get(f"/oidc/callback?code=x&state={good_state}").text
