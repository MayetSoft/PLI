"""Listing moderation (greylist) and the organizer blacklist."""

from fastapi.testclient import TestClient

from conftest import connect
from pli import organizers
from test_organizers import create_event_http, event_form, org_login


def listing(app, event_id):
    conn = connect(app)
    try:
        return conn.execute(
            "SELECT listing_status FROM cohorts WHERE id = ?", (event_id,)
        ).fetchone()["listing_status"]
    finally:
        conn.close()


def test_public_events_are_greylisted_until_approved(app, mailer):
    org = org_login(app, mailer)
    event_id, form = create_event_http(org, visibility="public")
    assert listing(app, event_id) == "pending"
    assert f"/e/{event_id}" not in TestClient(app).get("/events").text

    conn = connect(app)
    conn.execute("UPDATE cohorts SET listing_status = 'approved' WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()
    assert f"/e/{event_id}" in TestClient(app).get("/events").text

    # Ordinary edits do not re-queue an approved listing…
    org.post(f"/org/events/{event_id}/edit", data={**form, "visibility": "public",
                                                   "label": "Renamed"})
    assert listing(app, event_id) == "approved"
    # …going private delists…
    org.post(f"/org/events/{event_id}/edit", data={**form, "visibility": "private"})
    assert listing(app, event_id) == "unlisted"
    # …and going public again re-queues review.
    org.post(f"/org/events/{event_id}/edit", data={**form, "visibility": "public"})
    assert listing(app, event_id) == "pending"


def test_edit_from_private_to_pending_shows_in_dashboard(app, mailer):
    org = org_login(app, mailer)
    event_id, _ = create_event_http(org, visibility="public")
    assert "listing: pending" in org.get("/org/dashboard").text
    assert event_id  # created fine


def test_blacklist_blocks_organizer_login(app, mailer):
    conn = connect(app)
    organizers.blacklist_add(conn, "Crook@Shady.Example")     # normalised on store
    organizers.blacklist_add(conn, "spamfarm.example")        # whole domain
    assert organizers.is_blacklisted(conn, "crook@shady.example")
    assert organizers.is_blacklisted(conn, "anyone@spamfarm.example")
    assert not organizers.is_blacklisted(conn, "ok@clean.example")
    conn.close()

    before = len(mailer.sent)
    client = TestClient(app)
    r_blocked = client.post("/org/login", data={"email": "crook@shady.example"})
    r_domain = client.post("/org/login", data={"email": "bot@spamfarm.example"})
    assert mailer.sent[before:] == []                          # silence
    r_fine = client.post("/org/login", data={"email": "ok@clean.example"})
    assert len(mailer.sent) - before == 1
    assert r_blocked.content == r_domain.content == r_fine.content   # no oracle

    conn = connect(app)
    organizers.blacklist_remove(conn, "spamfarm.example")
    assert not organizers.is_blacklisted(conn, "bot@spamfarm.example")
    conn.close()


def test_moderation_cli(tmp_path, monkeypatch, capsys):
    import secrets

    from pli import cli

    monkeypatch.setenv("PLI_PEPPER", secrets.token_hex(32))
    monkeypatch.setenv("PLI_DB", str(tmp_path / "mod.db"))
    monkeypatch.setenv("PLI_KEYS_DIR", str(tmp_path / "keys"))
    cli.main(["init-db"])
    from pli import db as db_mod

    conn = db_mod.connect(str(tmp_path / "mod.db"))
    db_mod.create_cohort(conn, "party", "Party", ["x.example"], schedule="custom",
                         min_cohort=2, visibility="public")
    conn.execute("UPDATE cohorts SET listing_status = 'pending' WHERE id = 'party'")
    conn.commit()

    cli.main(["queue"])
    cli.main(["approve", "--id", "party"])
    assert conn.execute("SELECT listing_status FROM cohorts").fetchone()[0] == "approved"
    cli.main(["reject", "--id", "party"])
    assert conn.execute("SELECT listing_status FROM cohorts").fetchone()[0] == "unlisted"

    cli.main(["blacklist-add", "--pattern", "bad.example"])
    cli.main(["blacklist"])
    cli.main(["blacklist-remove", "--pattern", "bad.example"])
    cli.main(["suppress", "--email", "gone@x.example"])
    cli.main(["suppress", "--email", "not-an-email"])
    cli.main(["set-oidc", "--id", "party", "--issuer", "https://idp.example",
              "--client-id", "c", "--client-secret", "s"])
    assert conn.execute("SELECT oidc_issuer FROM cohorts").fetchone()[0] == "https://idp.example"
    cli.main(["set-oidc", "--id", "party", "--issuer", ""])
    assert conn.execute("SELECT oidc_issuer FROM cohorts").fetchone()[0] is None
    out = capsys.readouterr().out
    assert "1 pending" in out and "listing approved" in out
    assert "blacklisted bad.example" in out and "suppressed" in out
    assert "not an email-shaped address" in out
    assert "SSO enabled" in out and "SSO disabled" in out
    conn.close()
