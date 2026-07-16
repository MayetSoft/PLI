"""Outbound mail.

Exactly two kinds of mail exist: a magic link to an address that was just
typed into /join, and a match notice to each half of a reciprocal pair.
Nothing else. No close-of-round mail, no "no matches" mail — silence is
the only safe null (HANDOFF.md §2, I5).

Production must use a dedicated domain on a transactional provider with
message retention disabled. Never the shared Postfix infrastructure.
"""

from __future__ import annotations

import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage


@dataclass(frozen=True)
class Mail:
    to: str
    subject: str
    body: str


class Mailer:
    def send(self, mail: Mail) -> None:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass
class RecordingMailer(Mailer):
    """Test double. The invariant tests interrogate .sent."""

    sent: list[Mail] = field(default_factory=list)

    def send(self, mail: Mail) -> None:
        self.sent.append(mail)


class ConsoleMailer(Mailer):
    """Local development only — prints addresses to stdout, which is a log.
    Never run this in production."""

    def send(self, mail: Mail) -> None:
        print(f"--- mail to {mail.to} ---\n{mail.subject}\n\n{mail.body}\n---")


class SMTPMailer(Mailer):
    def __init__(self, host: str, port: int, user: str, password: str, mail_from: str):
        self.host, self.port = host, port
        self.user, self.password = user, password
        self.mail_from = mail_from

    def send(self, mail: Mail) -> None:
        msg = EmailMessage()
        msg["From"] = self.mail_from
        msg["To"] = mail.to
        msg["Subject"] = mail.subject
        msg.set_content(mail.body)
        with smtplib.SMTP(self.host, self.port, timeout=30) as smtp:
            smtp.starttls()
            if self.user:
                smtp.login(self.user, self.password)
            smtp.send_message(msg)


def make_mailer(settings) -> Mailer:
    if settings.mailer == "memory":
        return RecordingMailer()
    if settings.mailer == "smtp":
        return SMTPMailer(
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_user,
            settings.smtp_password,
            settings.mail_from,
        )
    return ConsoleMailer()
