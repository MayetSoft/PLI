"""Email normalisation.

Normalisation MUST be a pure function of the address string, applied
identically to declarer (src) and target (dst) — otherwise reciprocity
silently fails. This is where the bug will be; the property tests in
tests/test_normalize.py are the contract.

Rules: lowercase, strip surrounding whitespace, strip +tag suffixes,
apply dot-folding only for Gmail domains (where dots in the local part
are not significant).
"""

from __future__ import annotations

import re

# RFC-shape only. Deliberately no deliverability checks, no MX lookups,
# no "did you mean" — validation beyond shape is an enumeration surface.
RFC_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

GMAIL_DOMAINS = frozenset({"gmail.com", "googlemail.com"})


def is_rfc_shaped(raw: str) -> bool:
    return bool(RFC_SHAPE.match(raw.strip()))


def normalise_email(raw: str) -> str:
    """Return the canonical form of an address, or raise ValueError."""
    email = raw.strip().lower()
    if not RFC_SHAPE.match(email):
        raise ValueError("not an email-shaped string")
    local, _, domain = email.rpartition("@")
    local = local.split("+", 1)[0]
    if domain in GMAIL_DOMAINS:
        local = local.replace(".", "")
        domain = "gmail.com"
    if not local:
        raise ValueError("empty local part after normalisation")
    return f"{local}@{domain}"
