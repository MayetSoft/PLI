"""Organizer REST API: token-scoped, same guardrails as the web console."""

from fastapi.testclient import TestClient

from conftest import DOMAIN, connect
from pli import organizers
from test_organizers import event_form, org_login


def api_client(app, mailer):
    org = org_login(app, mailer)
    resp = org.post("/org/api-token")
    token = resp.text.split("<code>")[1].split("</code>")[0]
    assert token.startswith("pli_")
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {token}"
    return client, org, token


def test_token_lifecycle_and_auth(app, mailer):
    api, org, token = api_client(app, mailer)
    assert api.get("/api/v1/events").json() == {"events": []}

    # No/garbage/rotated tokens are 401.
    assert TestClient(app).get("/api/v1/events").status_code == 401
    bad = TestClient(app)
    bad.headers["Authorization"] = "Bearer pli_wrong"
    assert bad.get("/api/v1/events").status_code == 401
    org.post("/org/api-token")                          # rotation revokes
    assert api.get("/api/v1/events").status_code == 401

    # A banned organizer's token dies with the account.
    api2, _, _ = api_client(app, mailer)
    conn = connect(app)
    organizers.ban_organizer(conn, "organizer@agency.example")
    conn.close()
    assert api2.get("/api/v1/events").status_code == 401


def test_event_crud_over_api(app, mailer):
    api, _, _ = api_client(app, mailer)

    created = api.post("/api/v1/events", json=event_form(label="API Conf"))
    assert created.status_code == 201, created.text
    event = created.json()["event"]
    event_id = event["id"]
    assert event["label"] == "API Conf"
    assert event["round"]["status"] == "open"
    assert event["participants"] == 0
    assert event["share_url"].endswith(f"/e/{event_id}")

    listed = api.get("/api/v1/events").json()["events"]
    assert [e["id"] for e in listed] == [event_id]
    assert api.get(f"/api/v1/events/{event_id}").json()["event"]["id"] == event_id

    # PATCH with the same guardrails as the form.
    patched = api.patch(f"/api/v1/events/{event_id}",
                        json={**event_form(), "label": "API Conf v2"})
    assert patched.json()["event"]["label"] == "API Conf v2"
    bad = api.patch(f"/api/v1/events/{event_id}",
                    json={**event_form(), "min_cohort": "50"})
    assert bad.status_code == 422
    assert any("freezes" in e for e in bad.json()["errors"])

    # Cancel, then schedule a new round.
    assert api.post(f"/api/v1/events/{event_id}/cancel").json() == {"cancelled": True}
    assert api.post(f"/api/v1/events/{event_id}/cancel").json() == {"cancelled": False}
    fresh = api.post(f"/api/v1/events/{event_id}/rounds",
                     json={k: event_form(opens_min=10, closes_min=60, reveal_min=90)[k]
                           for k in ("opens", "closes", "reveal")})
    assert fresh.status_code == 201
    assert fresh.json()["event"]["round"]["status"] == "scheduled"
    conflict = api.post(f"/api/v1/events/{event_id}/rounds", json={})
    assert conflict.status_code == 422


def test_api_validation_and_isolation(app, mailer):
    api, _, _ = api_client(app, mailer)
    bad = api.post("/api/v1/events", json=event_form(domains="", join_code=""))
    assert bad.status_code == 422

    not_json = api.post("/api/v1/events", content=b"not json",
                        headers={"content-type": "application/json"})
    assert not_json.status_code == 422       # empty form → validation errors

    array = api.post("/api/v1/events", json=["a", "list"])
    assert array.status_code == 422

    created = api.post("/api/v1/events", json=event_form()).json()["event"]
    from test_organizers import OTHER_ORG

    org2 = org_login(app, mailer, OTHER_ORG)
    resp2 = org2.post("/org/api-token")
    token2 = resp2.text.split("<code>")[1].split("</code>")[0]
    rival = TestClient(app)
    rival.headers["Authorization"] = f"Bearer {token2}"
    assert rival.get(f"/api/v1/events/{created['id']}").status_code == 404
    assert rival.patch(f"/api/v1/events/{created['id']}", json={}).status_code == 404
    assert rival.post(f"/api/v1/events/{created['id']}/cancel").status_code == 404
    assert rival.post(f"/api/v1/events/{created['id']}/rounds", json={}).status_code == 404


def test_api_unauthenticated_everywhere(app, mailer):
    client = TestClient(app)
    assert client.post("/api/v1/events", json={}).status_code == 401
    assert client.get("/api/v1/events/x").status_code == 401
    assert client.post("/org/api-token", follow_redirects=False).headers["location"] == "/org"


def test_api_billing_gates(settings, mailer):
    from test_billing import billing_app

    application = billing_app(settings, mailer)
    org = org_login(application, mailer)
    resp = org.post("/org/api-token")
    token = resp.text.split("<code>")[1].split("</code>")[0]
    api = TestClient(application)
    api.headers["Authorization"] = f"Bearer {token}"

    gated = api.post("/api/v1/events", json=event_form(visibility="public",
                                                       custom_domain="pact.api.example"))
    assert gated.status_code == 422
    assert sum("pro plan" in e for e in gated.json()["errors"]) == 2

    created = api.post("/api/v1/events", json=event_form())
    assert created.status_code == 201
    event_id = created.json()["event"]["id"]
    patched = api.patch(f"/api/v1/events/{event_id}",
                        json={**event_form(), "visibility": "public"})
    assert patched.status_code == 422
    patched = api.patch(f"/api/v1/events/{event_id}",
                        json={**event_form(), "custom_domain": "pact.api.example"})
    assert patched.status_code == 422


def test_api_never_exposes_participants(app, mailer):
    """The API returns a count and a status — never a roster, on any
    plan, through any endpoint."""
    from test_platform import event_signup

    api, _, _ = api_client(app, mailer)
    event = api.post("/api/v1/events", json=event_form()).json()["event"]
    event_signup(app, mailer, event["id"], f"alice@{DOMAIN}")

    detail = api.get(f"/api/v1/events/{event['id']}").json()["event"]
    assert detail["participants"] == 1
    assert f"alice@{DOMAIN}" not in api.get(f"/api/v1/events/{event['id']}").text
