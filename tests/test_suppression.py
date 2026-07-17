"""Suppression list and the mail webhook: a bounced or complaining
address is never mailed again — not a magic link, not even a match."""

import dataclasses

from fastapi.testclient import TestClient

from conftest import DOMAIN, close_round, connect, declare, reveal_round, signup
from pli import rounds, suppression
from pli.app import create_app

ALICE = f"alice@{DOMAIN}"
BOB = f"bob@{DOMAIN}"


def test_suppress_and_membership(app):
    conn = connect(app)
    pepper = app.state.settings.pepper
    assert suppression.suppress(conn, pepper, f"  {ALICE.upper()} ", "bounce")
    assert suppression.is_suppressed(conn, pepper, ALICE)          # normalised
    assert not suppression.is_suppressed(conn, pepper, BOB)
    assert suppression.suppress(conn, pepper, BOB, "not-a-reason")  # → manual
    assert not suppression.suppress(conn, pepper, "garbage", "bounce")
    assert not suppression.suppress(conn, pepper, "+t@x.example", "bounce")
    conn.close()


def test_suppressed_address_gets_no_magic_link(app, mailer):
    conn = connect(app)
    suppression.suppress(conn, app.state.settings.pepper, ALICE, "complaint")
    conn.close()
    before = len(mailer.sent)
    resp = TestClient(app).post("/join", data={"email": ALICE})
    assert "If that address is eligible" in resp.text   # response unchanged
    assert len(mailer.sent) == before

    before = len(mailer.sent)
    TestClient(app).post("/org/login", data={"email": ALICE})
    assert len(mailer.sent) == before


def test_reveal_skips_suppressed_half_of_a_pair(app, mailer):
    alice = signup(app, mailer, ALICE)
    bob = signup(app, mailer, BOB)
    declare(alice, BOB)
    declare(bob, ALICE)
    conn = connect(app)
    suppression.suppress(conn, app.state.settings.pepper, ALICE, "bounce")
    rid = rounds.latest_round(conn, "test-cohort")["id"]
    close_round(app)
    before = len(mailer.sent)
    rounds.reveal_round(conn, app.state.keystore, mailer, rid,
                        pepper=app.state.settings.pepper)
    conn.close()
    assert [m.to for m in mailer.sent[before:]] == [BOB]


def webhook_app(settings, mailer):
    s = dataclasses.replace(settings, mail_webhook_token="hook-token")
    return create_app(settings=s, mailer=mailer)


def test_mail_webhook(app, settings, mailer):
    application = webhook_app(settings, mailer)
    client = TestClient(application)
    pepper = settings.pepper

    assert client.post("/webhooks/mail/wrong", json={}).status_code == 404
    # Unconfigured token: the endpoint does not exist in practice.
    assert TestClient(app).post("/webhooks/mail/", json={}).status_code in (404, 307)
    assert TestClient(app).post("/webhooks/mail/anything", json={}).status_code == 404

    # Postmark shapes.
    client.post("/webhooks/mail/hook-token",
                json={"RecordType": "Bounce", "Email": ALICE})
    client.post("/webhooks/mail/hook-token",
                json={"RecordType": "SpamComplaint", "Recipient": BOB})
    # Generic shape.
    client.post("/webhooks/mail/hook-token",
                json={"type": "bounce", "email": f"carol@{DOMAIN}"})
    # Noise: unknown kind, bad json — accepted and ignored.
    client.post("/webhooks/mail/hook-token", json={"RecordType": "Delivery", "Email": ALICE})
    resp = client.post("/webhooks/mail/hook-token", content=b"not json")
    assert resp.status_code == 200

    conn = connect(app)
    assert suppression.is_suppressed(conn, pepper, ALICE)
    assert suppression.is_suppressed(conn, pepper, BOB)
    assert suppression.is_suppressed(conn, pepper, f"carol@{DOMAIN}")
    assert conn.execute("SELECT COUNT(*) AS n FROM suppressions").fetchone()["n"] == 3
    conn.close()
