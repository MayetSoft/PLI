"""Institutional SSO attestation (OIDC authorization-code flow).

For cohorts where email-domain matching is too coarse (shared mailboxes,
multi-domain universities), the operator can configure an OIDC issuer per
cohort. The flow asserts exactly one bit — *this person is a member of
the institution* — plus the verified address needed for the match mail.

We deliberately keep nothing from the identity provider: no subject
identifier, no name, no session with the issuer. The email is treated
exactly as if the participant had typed it into /join, i.e. it becomes a
keyed hash and a sealed contact blob, gone at the reveal. Configuration
is operator-CLI only: client secrets and issuer trust are negotiated
with institutions, not self-served.

Token validation strategy: rather than validating id_token JWTs locally
(JWKS caching, algorithm pinning — a large, sharp surface), we exchange
the code and then ask the issuer's own userinfo endpoint over TLS. For
this one-bit purpose, the issuer answering for its own token is
authoritative.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request

STATE_TTL = 600  # seconds


def _get_json(url: str, opener=None, data: bytes | None = None, headers: dict | None = None):
    request = urllib.request.Request(url, data=data, headers=headers or {})
    opener = opener or urllib.request.urlopen
    with opener(request, timeout=15) as response:
        return json.loads(response.read().decode())


def discover(issuer: str, opener=None) -> dict:
    return _get_json(issuer.rstrip("/") + "/.well-known/openid-configuration", opener)


def sign_state(pepper: bytes, cohort_id: str, now: float | None = None) -> str:
    expires = int((time.time() if now is None else now) + STATE_TTL)
    payload = f"{cohort_id}.{expires}".encode()
    signature = hmac.new(pepper, b"oidc-state:" + payload, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(payload).decode() + "." + signature


def verify_state(pepper: bytes, state: str, now: float | None = None) -> str | None:
    """Returns the cohort id, or None."""
    try:
        payload_b64, signature = state.rsplit(".", 1)
        payload = base64.urlsafe_b64decode(payload_b64.encode())
        expected = hmac.new(pepper, b"oidc-state:" + payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        cohort_id, expires = payload.decode().rsplit(".", 1)
        if int(expires) < (time.time() if now is None else now):
            return None
        return cohort_id
    except Exception:
        return None


def auth_url(cohort, pepper: bytes, redirect_uri: str, opener=None) -> str:
    config = discover(cohort["oidc_issuer"], opener)
    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": cohort["oidc_client_id"],
        "redirect_uri": redirect_uri,
        "scope": "openid email",
        "state": sign_state(pepper, cohort["id"]),
    })
    return f"{config['authorization_endpoint']}?{params}"


def fetch_verified_email(cohort, code: str, redirect_uri: str, opener=None) -> str | None:
    """Exchange the code, ask userinfo, return a verified email or None.
    Nothing from the exchange is retained by the caller beyond the email."""
    try:
        config = discover(cohort["oidc_issuer"], opener)
        token = _get_json(
            config["token_endpoint"],
            opener,
            data=urllib.parse.urlencode({
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": cohort["oidc_client_id"],
                "client_secret": cohort["oidc_client_secret"] or "",
            }).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        userinfo = _get_json(
            config["userinfo_endpoint"],
            opener,
            headers={"Authorization": f"Bearer {token['access_token']}"},
        )
        email = userinfo.get("email", "")
        if not email or userinfo.get("email_verified") is False:
            return None
        return email
    except Exception:
        return None
