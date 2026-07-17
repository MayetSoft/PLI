"""Plans, entitlements, and the billing provider boundary.

The monetization rule: charge the organizer, never the participant.
Participant-side behaviour is identical on every plan — no participant
caps, because a "sorry, full" page is a signal and mail costs nothing.
Plans gate organizer conveniences only:

    free: one event with an active round at a time; private events only
    pro:  unlimited concurrent events; public listing; custom domain

THE OPEN-CORE BOUNDARY. This platform's trust model rests on the source
being public, so the split is deliberate and narrow:

- A billing *provider* (possibly closed-source, loaded from
  PLI_BILLING_PLUGIN) answers exactly one question — "what plan is this
  organizer on?" — plus the plumbing to change the answer (a checkout
  URL out, a payment webhook in).
- The open core decides what a plan *means*: every gate lives in this
  file, in public code. A provider receives organizer rows and webhook
  bytes; it has no access to participants, declarations, rounds, or
  keys, and nothing it returns can widen what a plan may touch.

With PLI_BILLING=off and no plugin (the default: dev, self-hosting,
launch phase) nothing is enforced and everyone behaves as pro.

The built-in Stripe provider is kept here, open, as the reference
implementation and for self-hosters: EU entity support, SCA/PSD2
handled, hosted Checkout (card data never touches this server —
PCI SAQ-A), subscriptions via Billing. One redirect out, one signed
webhook in. No card data, no SDK, no client-side JS.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import sqlite3
import urllib.parse
import urllib.request

from .config import Settings

PLANS = {
    "free": {"concurrent_events": 1, "public_listing": False},
    "pro": {"concurrent_events": None, "public_listing": True},
}

STRIPE_API = "https://api.stripe.com/v1/checkout/sessions"


class BillingProvider:
    """The provider contract. Subclass in a plugin package and expose
    `create_provider(settings) -> BillingProvider`."""

    def enforced(self) -> bool:
        return False

    def plan_name(self, organizer: sqlite3.Row) -> str:
        return "pro"

    def checkout_url(self, organizer: sqlite3.Row, opener=None) -> str | None:
        return None

    def handle_webhook(self, conn: sqlite3.Connection, headers: dict, body: bytes) -> tuple[int, str]:
        return 400, "billing is not enabled"


class NullBilling(BillingProvider):
    """PLI_BILLING=off — everything free, nothing enforced."""


class StripeBilling(BillingProvider):
    """Open reference provider (see module docstring)."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def enforced(self) -> bool:
        return True

    def plan_name(self, organizer: sqlite3.Row) -> str:
        return organizer["plan"] if organizer["plan"] in PLANS else "free"

    def checkout_url(self, organizer: sqlite3.Row, opener=None) -> str | None:
        settings = self.settings
        if not settings.stripe_secret or not settings.stripe_price_id:
            return None
        payload = urllib.parse.urlencode({
            "mode": "subscription",
            "line_items[0][price]": settings.stripe_price_id,
            "line_items[0][quantity]": "1",
            "client_reference_id": str(organizer["id"]),
            "customer_email": organizer["email"],
            "success_url": f"{settings.base_url}/org/dashboard",
            "cancel_url": f"{settings.base_url}/org/dashboard",
        }).encode()
        request = urllib.request.Request(
            STRIPE_API,
            data=payload,
            headers={"Authorization": f"Bearer {settings.stripe_secret}"},
            method="POST",
        )
        opener = opener or urllib.request.urlopen
        with opener(request, timeout=30) as response:
            session = json.loads(response.read().decode())
        return session.get("url")

    def handle_webhook(self, conn: sqlite3.Connection, headers: dict, body: bytes) -> tuple[int, str]:
        signature = headers.get("stripe-signature", "")
        if not self.settings.stripe_webhook_secret or not verify_stripe_signature(
            self.settings.stripe_webhook_secret, signature, body
        ):
            return 400, "bad signature"
        handle_stripe_event(conn, json.loads(body))
        return 200, "ok"


def load_provider(settings: Settings) -> BillingProvider:
    """Resolve the active provider. A plugin (PLI_BILLING_PLUGIN, a
    module exposing create_provider) wins; then the open Stripe
    reference (PLI_BILLING=stripe); then off. A broken plugin fails
    fast at startup rather than silently un-gating anything."""
    if settings.billing_plugin:
        module = importlib.import_module(settings.billing_plugin)
        return module.create_provider(settings)
    if settings.billing == "stripe":
        return StripeBilling(settings)
    return NullBilling()


# ---- entitlement gates: open code, always -----------------------------------


def plan_of(provider: BillingProvider, organizer: sqlite3.Row) -> dict:
    if not provider.enforced():
        return PLANS["pro"]
    return PLANS.get(provider.plan_name(organizer), PLANS["free"])


def can_create_event(
    provider: BillingProvider, conn: sqlite3.Connection, organizer: sqlite3.Row
) -> str | None:
    """None if allowed, else a human-readable reason."""
    plan = plan_of(provider, organizer)
    limit = plan["concurrent_events"]
    if limit is None:
        return None
    active = conn.execute(
        "SELECT COUNT(DISTINCT c.id) AS n FROM cohorts c"
        " JOIN rounds r ON r.cohort_id = c.id"
        " WHERE c.organizer_id = ? AND r.status IN ('scheduled', 'open', 'closed')",
        (organizer["id"],),
    ).fetchone()["n"]
    if active >= limit:
        return (
            f"The free plan runs {limit} event at a time. "
            "Upgrade to run several, or wait for the current round to finish."
        )
    return None


def can_request_listing(provider: BillingProvider, organizer: sqlite3.Row) -> str | None:
    if plan_of(provider, organizer)["public_listing"]:
        return None
    return "Public listing is part of the pro plan."


def can_use_custom_domain(provider: BillingProvider, organizer: sqlite3.Row) -> str | None:
    # Same gate as listing: white-label is a pro convenience.
    if plan_of(provider, organizer)["public_listing"]:
        return None
    return "Custom domains are part of the pro plan."


# ---- Stripe primitives (open, unit-tested, reused by the reference provider) --


def verify_stripe_signature(secret: str, header: str, body: bytes) -> bool:
    """Stripe-Signature: t=<ts>,v1=<hmac-sha256 of "<ts>.<body>">."""
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        signed = f"{parts['t']}.".encode() + body
        expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, parts["v1"])
    except Exception:
        return False


def handle_stripe_event(conn: sqlite3.Connection, event: dict) -> str:
    """Apply a verified Stripe event. Returns what happened (for tests;
    nothing is logged in production)."""
    kind = event.get("type", "")
    obj = event.get("data", {}).get("object", {})
    if kind == "checkout.session.completed":
        organizer_id = obj.get("client_reference_id")
        customer = obj.get("customer", "")
        if organizer_id:
            with conn:
                conn.execute(
                    "UPDATE organizers SET plan = 'pro', stripe_customer = ? WHERE id = ?",
                    (customer, int(organizer_id)),
                )
            return "upgraded"
    elif kind in ("customer.subscription.deleted", "invoice.payment_failed"):
        customer = obj.get("customer", "")
        if customer:
            with conn:
                conn.execute(
                    "UPDATE organizers SET plan = 'free' WHERE stripe_customer = ?",
                    (customer,),
                )
            return "downgraded"
    return "ignored"
