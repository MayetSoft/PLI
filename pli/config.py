"""Runtime settings. Everything secret arrives via environment variables.

The pepper is 32 random bytes, hex-encoded, in PLI_PEPPER. It must never be
written to the database, the image, or git.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    db_path: str
    pepper: bytes
    keys_dir: str
    cohort_id: str
    base_url: str = "http://localhost:8000"
    secure_cookies: bool = False
    mailer: str = "console"  # console | smtp | memory
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    mail_from: str = "pli@localhost"
    # Inbound webhooks. The mail token is a shared secret in the URL path;
    # the Stripe secret verifies the Stripe-Signature header.
    mail_webhook_token: str = ""
    # Billing: "off" (everything free — dev, self-host, launch phase) or
    # "stripe" (plan enforcement on, checkout via Stripe).
    billing: str = "off"
    stripe_secret: str = ""
    stripe_price_id: str = ""
    stripe_webhook_secret: str = ""
    # Legal identity of the operator (a French SASU), rendered into the
    # privacy policy, terms, and DPA pages. Placeholders until set.
    company_name: str = "[COMPANY NAME] SASU"
    company_address: str = "[REGISTERED ADDRESS]"
    company_siren: str = "[SIREN]"
    company_contact: str = "[CONTACT EMAIL]"
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Settings":
        pepper_hex = os.environ.get("PLI_PEPPER", "")
        if len(pepper_hex) != 64:
            raise RuntimeError(
                "PLI_PEPPER must be 32 random bytes, hex-encoded (64 chars). "
                "Generate with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        return cls(
            db_path=os.environ.get("PLI_DB", "data/pli.db"),
            pepper=bytes.fromhex(pepper_hex),
            keys_dir=os.environ.get("PLI_KEYS_DIR", "data/keys"),
            cohort_id=os.environ.get("PLI_COHORT_ID", ""),
            base_url=os.environ.get("PLI_BASE_URL", "http://localhost:8000").rstrip("/"),
            secure_cookies=os.environ.get("PLI_SECURE_COOKIES", "0") == "1",
            mailer=os.environ.get("PLI_MAILER", "console"),
            smtp_host=os.environ.get("PLI_SMTP_HOST", ""),
            smtp_port=int(os.environ.get("PLI_SMTP_PORT", "587")),
            smtp_user=os.environ.get("PLI_SMTP_USER", ""),
            smtp_password=os.environ.get("PLI_SMTP_PASSWORD", ""),
            mail_from=os.environ.get("PLI_MAIL_FROM", "pli@localhost"),
            mail_webhook_token=os.environ.get("PLI_MAIL_WEBHOOK_TOKEN", ""),
            billing=os.environ.get("PLI_BILLING", "off"),
            stripe_secret=os.environ.get("PLI_STRIPE_SECRET", ""),
            stripe_price_id=os.environ.get("PLI_STRIPE_PRICE_ID", ""),
            stripe_webhook_secret=os.environ.get("PLI_STRIPE_WEBHOOK_SECRET", ""),
            company_name=os.environ.get("PLI_COMPANY_NAME", "[COMPANY NAME] SASU"),
            company_address=os.environ.get("PLI_COMPANY_ADDRESS", "[REGISTERED ADDRESS]"),
            company_siren=os.environ.get("PLI_COMPANY_SIREN", "[SIREN]"),
            company_contact=os.environ.get("PLI_COMPANY_CONTACT", "[CONTACT EMAIL]"),
        )
