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
        )
