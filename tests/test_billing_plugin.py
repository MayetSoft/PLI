"""The open-core seam: a (closed-source) billing plugin loaded from
PLI_BILLING_PLUGIN. The plugin decides who has paid; the open gates in
pli.billing decide what that means — these tests pin that boundary."""

import dataclasses
import sys
import types

import pytest
from fastapi.testclient import TestClient

from conftest import connect
from pli import billing, db as db_mod
from pli.app import create_app
from test_organizers import event_form, org_login


class FakeProProvider(billing.BillingProvider):
    """What a private entitlements package would ship: plan resolution
    against its own backend, a checkout URL, a webhook. Note what it
    does NOT get: participants, declarations, rounds, keys."""

    def __init__(self, settings):
        self.settings = settings
        self.paid: set[str] = set()

    def enforced(self):
        return True

    def plan_name(self, organizer):
        return "pro" if organizer["email"] in self.paid else "free"

    def checkout_url(self, organizer, opener=None):
        return f"https://pay.plicorp.example/checkout?org={organizer['id']}"

    def handle_webhook(self, conn, headers, body):
        if headers.get("x-pro-secret") != "letmein":
            return 400, "bad signature"
        self.paid.add(body.decode())
        return 202, "activated"


def plugin_app(settings, mailer):
    module = types.ModuleType("pli_pro_fake")
    module.create_provider = FakeProProvider
    sys.modules["pli_pro_fake"] = module
    s = dataclasses.replace(settings, billing_plugin="pli_pro_fake")
    application = create_app(settings=s, mailer=mailer)
    conn = db_mod.connect(s.db_path)
    db_mod.init_db(conn)
    conn.close()
    return application


def test_plugin_provider_drives_the_open_gates(settings, mailer):
    application = plugin_app(settings, mailer)
    provider = application.state.billing
    assert isinstance(provider, FakeProProvider)

    org = org_login(application, mailer)
    # Free according to the plugin: the open gates bite.
    resp = org.post("/org/events", data=event_form(visibility="public"))
    assert "pro plan" in resp.text

    # Upgrade goes wherever the plugin says.
    resp = org.post("/org/upgrade", follow_redirects=False)
    assert resp.headers["location"].startswith("https://pay.plicorp.example/checkout?org=")

    # The generic webhook route dispatches to the plugin.
    client = TestClient(application)
    assert client.post("/webhooks/billing", content=b"x").status_code == 400
    resp = client.post("/webhooks/billing", content=b"organizer@agency.example",
                       headers={"x-pro-secret": "letmein"})
    assert resp.status_code == 202

    # Paid now — the same open gates release.
    resp = org.post("/org/events", data=event_form(visibility="public"),
                    follow_redirects=False)
    assert resp.status_code == 303
    assert "listing: pending" in org.get("/org/dashboard").text


def test_plugin_cannot_widen_what_a_plan_means(settings, mailer):
    """A malicious or buggy plugin returning garbage plan names gets the
    free plan, never an undefined one — PLANS is the closed set and it
    lives in open code."""
    application = plugin_app(settings, mailer)
    provider = application.state.billing
    provider.plan_name = lambda organizer: "ultra-mega-plan"
    conn = connect(application)
    from pli.organizers import get_or_create_organizer

    org = get_or_create_organizer(conn, "x@y.example")
    assert billing.plan_of(provider, org) == billing.PLANS["free"]
    conn.close()


def test_broken_plugin_fails_fast(settings, mailer):
    s = dataclasses.replace(settings, billing_plugin="no_such_module_anywhere")
    with pytest.raises(ModuleNotFoundError):
        create_app(settings=s, mailer=mailer)
