"""Plans and Stripe: participant behaviour is identical on every plan;
plans gate organizer conveniences only."""

import dataclasses
import hashlib
import hmac
import io
import json

from fastapi.testclient import TestClient

from conftest import connect
from pli import billing
from pli.app import create_app
from test_organizers import create_event_http, event_form, org_login

WHSEC = "whsec_test"


def billing_app(settings, mailer):
    s = dataclasses.replace(
        settings, billing="stripe", stripe_secret="sk_test",
        stripe_price_id="price_1", stripe_webhook_secret=WHSEC,
    )
    application = create_app(settings=s, mailer=mailer)
    from pli import db as db_mod

    conn = db_mod.connect(s.db_path)
    db_mod.init_db(conn)
    conn.close()
    return application


def stripe_sig(body: bytes, secret=WHSEC, timestamp="123"):
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={mac}"


def test_billing_off_means_everyone_is_pro(app, settings, mailer):
    conn = connect(app)
    from pli.organizers import get_or_create_organizer

    org = get_or_create_organizer(conn, "o@x.example")
    assert billing.plan_of(settings, org) == billing.PLANS["pro"]
    assert billing.can_create_event(settings, conn, org) is None
    assert billing.can_request_listing(settings, org) is None
    assert billing.checkout_url(settings, org) is None     # nothing to sell
    conn.close()


def test_free_plan_limits_enforced_over_http(settings, mailer):
    application = billing_app(settings, mailer)
    org = org_login(application, mailer)

    # Public listing is a pro feature.
    resp = org.post("/org/events", data=event_form(visibility="public"))
    assert "pro plan" in resp.text

    # One concurrent event on free.
    event_id, form = create_event_http(org)
    resp = org.post("/org/events", data=event_form())
    assert "free plan runs 1 event at a time" in resp.text

    # Editing an existing private event to public is gated the same way.
    resp = org.post(f"/org/events/{event_id}/edit",
                    data={**form, "visibility": "public"})
    assert "pro plan" in resp.text

    # Upgrading via a (fake-signed) Stripe webhook lifts both limits.
    conn = connect(application)
    organizer_id = conn.execute("SELECT id FROM organizers").fetchone()["id"]
    conn.close()
    body = json.dumps({
        "type": "checkout.session.completed",
        "data": {"object": {"client_reference_id": str(organizer_id), "customer": "cus_1"}},
    }).encode()
    resp = TestClient(application).post(
        "/webhooks/stripe", content=body, headers={"stripe-signature": stripe_sig(body)}
    )
    assert resp.status_code == 200
    create_event_http(org)                                     # second event OK now
    resp = org.post(f"/org/events/{event_id}/edit",
                    data=event_form(visibility="public"), follow_redirects=False)
    assert resp.status_code == 303                             # listing request OK

    # Subscription lapse downgrades by customer id.
    body = json.dumps({
        "type": "customer.subscription.deleted",
        "data": {"object": {"customer": "cus_1"}},
    }).encode()
    TestClient(application).post(
        "/webhooks/stripe", content=body, headers={"stripe-signature": stripe_sig(body)}
    )
    conn = connect(application)
    assert conn.execute("SELECT plan FROM organizers").fetchone()["plan"] == "free"
    conn.close()


def test_stripe_webhook_rejects_bad_signatures(settings, mailer, app):
    application = billing_app(settings, mailer)
    body = b'{"type": "checkout.session.completed"}'
    client = TestClient(application)
    assert client.post("/webhooks/stripe", content=body).status_code == 400
    assert client.post("/webhooks/stripe", content=body,
                       headers={"stripe-signature": "t=1,v1=deadbeef"}).status_code == 400
    assert client.post("/webhooks/stripe", content=body,
                       headers={"stripe-signature": "garbage"}).status_code == 400
    # Unconfigured secret: endpoint always refuses.
    assert TestClient(app).post("/webhooks/stripe", content=body,
                                headers={"stripe-signature": stripe_sig(body)}).status_code == 400


def test_handle_stripe_event_edges(app):
    conn = connect(app)
    assert billing.handle_stripe_event(conn, {"type": "ping"}) == "ignored"
    assert billing.handle_stripe_event(
        conn, {"type": "checkout.session.completed", "data": {"object": {}}}
    ) == "ignored"
    assert billing.handle_stripe_event(
        conn, {"type": "invoice.payment_failed", "data": {"object": {}}}
    ) == "ignored"
    conn.close()


def test_checkout_url_calls_stripe(settings, mailer):
    s = dataclasses.replace(settings, billing="stripe", stripe_secret="sk_test",
                            stripe_price_id="price_1")
    captured = {}

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def opener(request, timeout):
        captured["auth"] = request.get_header("Authorization")
        captured["data"] = request.data.decode()
        return FakeResponse(b'{"url": "https://checkout.stripe.com/c/session"}')

    org = {"id": 7, "email": "o@x.example"}
    url = billing.checkout_url(s, org, opener=opener)
    assert url == "https://checkout.stripe.com/c/session"
    assert captured["auth"] == "Bearer sk_test"
    assert "price_1" in captured["data"] and "client_reference_id=7" in captured["data"]


def test_upgrade_route(settings, mailer):
    application = billing_app(settings, mailer)
    client = TestClient(application)
    assert client.post("/org/upgrade", follow_redirects=False).headers["location"] == "/org"
    org = org_login(application, mailer)
    # Stripe is unreachable in tests: the route lands back on the dashboard.
    resp = org.post("/org/upgrade", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/org/dashboard"
    assert "free plan" in org.get("/org/dashboard").text     # upgrade pitch shown
