"""The public face: landing page, /about, and root behaviour with and
without a default community configured."""

import secrets

from fastapi.testclient import TestClient

from pli import db as db_mod
from pli.app import create_app
from pli.config import Settings
from pli.mailer import RecordingMailer


def bare_app(tmp_path):
    """A platform instance with no default community configured."""
    settings = Settings(
        db_path=str(tmp_path / "bare.db"),
        pepper=secrets.token_bytes(32),
        keys_dir=str(tmp_path / "bare-keys"),
        cohort_id="",
        mailer="memory",
    )
    application = create_app(settings=settings, mailer=RecordingMailer())
    conn = db_mod.connect(settings.db_path)
    db_mod.init_db(conn)
    conn.close()
    return application


def test_root_is_landing_without_default_community(tmp_path):
    client = TestClient(bare_app(tmp_path))
    page = client.get("/")
    assert "sealed-envelope" in page.text
    assert "Organizer sign-in" in page.text
    assert "Browse public events" in page.text


def test_root_is_community_when_configured_and_about_always_exists(app, mailer):
    client = TestClient(app)
    assert "A round is open" in client.get("/").text          # default untouched
    about = client.get("/about")
    assert "sealed-envelope" in about.text


def test_join_on_unconfigured_platform_is_silent(tmp_path):
    application = bare_app(tmp_path)
    client = TestClient(application)
    sent_before = len(application.state.mailer.sent)
    resp = client.post("/join", data={"email": "a@b.example"})
    assert "If that address is eligible" in resp.text
    assert application.state.mailer.sent[sent_before:] == []
    # Declare paths with no community configured just go home.
    assert client.get("/declare", follow_redirects=False).status_code == 303
    assert client.post("/declare", data={"targets": "a@b.example"},
                       follow_redirects=False).status_code == 303


def test_security_headers(app, mailer):
    resp = TestClient(app).get("/")
    assert "default-src 'self'" in resp.headers["content-security-policy"]
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "no-referrer"
