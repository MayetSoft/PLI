import re
import secrets

import pytest
from fastapi.testclient import TestClient

from pli import db as db_mod
from pli import rounds
from pli.app import create_app
from pli.config import Settings
from pli.mailer import RecordingMailer
from pli.normalize import normalise_email

COHORT = "test-cohort"
DOMAIN = "example.edu"


@pytest.fixture
def settings(tmp_path):
    return Settings(
        db_path=str(tmp_path / "pli.db"),
        pepper=secrets.token_bytes(32),
        keys_dir=str(tmp_path / "keys"),
        cohort_id=COHORT,
        base_url="http://testserver",
        mailer="memory",
    )


@pytest.fixture
def mailer():
    return RecordingMailer()


@pytest.fixture
def app(settings, mailer):
    application = create_app(settings=settings, mailer=mailer)
    conn = db_mod.connect(settings.db_path)
    db_mod.init_db(conn)
    db_mod.create_cohort(conn, COHORT, "Test cohort", [DOMAIN], min_cohort=2)
    rounds.open_round(conn, application.state.keystore, COHORT)
    conn.close()
    return application


def connect(app):
    return db_mod.connect(app.state.settings.db_path)


def round_id(app) -> int:
    conn = connect(app)
    try:
        return rounds.latest_round(conn, COHORT)["id"]
    finally:
        conn.close()


def signup(app, mailer, email):
    """POST /join, follow the magic link, return a client holding the
    round-scoped session cookie."""
    client = TestClient(app)
    client.post("/join", data={"email": email})
    norm = normalise_email(email)
    mail = next(m for m in reversed(mailer.sent) if m.to == norm and "/s/" in m.body)
    token = re.search(r"/s/([A-Za-z0-9_\-]+)", mail.body).group(1)
    resp = client.get(f"/s/{token}", follow_redirects=False)
    assert resp.status_code == 303
    return client


def declare(client, *targets):
    return client.post("/declare", data={"targets": list(targets)})


def close_round(app):
    conn = connect(app)
    try:
        rid = rounds.latest_round(conn, COHORT)["id"]
        return rounds.close_round(conn, app.state.keystore, rid)
    finally:
        conn.close()


def reveal_round(app, mailer):
    conn = connect(app)
    try:
        rid = rounds.latest_round(conn, COHORT)["id"]
        return rounds.reveal_round(conn, app.state.keystore, mailer, rid)
    finally:
        conn.close()
