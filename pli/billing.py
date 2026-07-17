"""Plans and Stripe billing.

The monetization rule: charge the organizer, never the participant.
Participant-side behaviour is identical on every plan — no participant
caps, because a "sorry, full" page is a signal and mail costs nothing.
Plans gate organizer conveniences only:

    free: one event with an active round at a time; private events only
    pro:  unlimited concurrent events; may request public listing

With PLI_BILLING=off (the default: dev, self-hosting, launch phase)
nothing is enforced and everyone behaves as pro.

Stripe is the recommended processor for a French SASU: EU entity
support, SCA/PSD2 handled, hosted Checkout (card data never touches this
server — PCI SAQ-A), tax handling via Stripe Tax, subscriptions via
Billing. Integration is deliberately thin: one Checkout redirect out,
one signed webhook in. No card data, no Stripe SDK, no client-side JS.
"""

from __future__ import annotations

import hashlib
import hmac
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


def enforced(settings: Settings) -> bool:
    return settings.billing != "off"


def plan_of(settings: Settings, organizer: sqlite3.Row) -> dict:
    if not enforced(settings):
        return PLANS["pro"]
    return PLANS.get(organizer["plan"], PLANS["free"])


def can_create_event(settings: Settings, conn: sqlite3.Connection, organizer: sqlite3.Row) -> str | None:
    """None if allowed, else a human-readable reason."""
    plan = plan_of(settings, organizer)
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


def can_request_listing(settings: Settings, organizer: sqlite3.Row) -> str | None:
    if plan_of(settings, organizer)["public_listing"]:
        return None
    return "Public listing is part of the pro plan."


def can_use_custom_domain(settings: Settings, organizer: sqlite3.Row) -> str | None:
    # Same gate as listing: white-label is a pro convenience.
    if plan_of(settings, organizer)["public_listing"]:
        return None
    return "Custom domains are part of the pro plan."


def checkout_url(settings: Settings, organizer: sqlite3.Row, opener=None) -> str | None:
    """Create a Stripe Checkout session and return its URL. `opener` is
    injectable for tests; production uses urllib over TLS."""
    if not enforced(settings) or not settings.stripe_secret or not settings.stripe_price_id:
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
