"""The embeddable join widget: an iframe-only surface with constrained
styling. Same silent join core, same invariants, inside the frame."""

from fastapi.testclient import TestClient

from conftest import COHORT, DOMAIN, connect
from pli import db as db_mod, rounds
from test_platform import create_event

ALICE = f"alice@{DOMAIN}"


def test_widget_renders_and_is_framable(app, mailer):
    create_event(app, event_id="conf")
    resp = TestClient(app).get("/e/conf/widget")
    assert resp.status_code == 200
    assert "frame-ancestors *" in resp.headers["content-security-policy"]
    assert "x-frame-options" not in resp.headers
    assert 'name="email"' in resp.text
    assert "Test event" in resp.text

    # Every other page stays unframable.
    page = TestClient(app).get("/e/conf")
    assert page.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]


def test_widget_style_options_are_strictly_validated(app, mailer):
    create_event(app, event_id="conf")
    client = TestClient(app)

    styled = client.get("/e/conf/widget?theme=dark&accent=7a3b2e&font=sans")
    assert "#7a3b2e" in styled.text
    assert "background: #191918" in styled.text
    assert "sans-serif" in styled.text

    default = client.get("/e/conf/widget")
    assert "#1f4a5f" in default.text and "Georgia" in default.text

    # Injection attempts fall back to defaults and never reach the page.
    evil = client.get(
        "/e/conf/widget?theme=%3Cscript%3E&accent=%7B%7Bx%7D%7D;url(&font=cursive"
    )
    assert "<script>" not in evil.text
    assert "url(" not in evil.text
    assert "cursive" not in evil.text
    assert "#1f4a5f" in evil.text and "Georgia" in evil.text
    short = client.get("/e/conf/widget?accent=fff")     # not 6 hex digits
    assert "--accent: #fff;" not in short.text
    assert "--accent: #1f4a5f" in short.text


def test_widget_join_flow_and_no_enumeration(app, mailer):
    create_event(app, event_id="conf")
    client = TestClient(app)

    before = len(mailer.sent)
    r_eligible = client.post("/e/conf/widget?theme=dark&accent=aabbcc",
                             data={"email": ALICE})
    assert "If that address is eligible" in r_eligible.text
    assert "#aabbcc" in r_eligible.text                 # style survives the POST
    assert [m.to for m in mailer.sent[before:]] == [ALICE]

    r_ineligible = client.post("/e/conf/widget?theme=dark&accent=aabbcc",
                               data={"email": "outsider@elsewhere.example"})
    assert r_eligible.content == r_ineligible.content    # I8 inside the frame
    assert len(mailer.sent) == before + 1


def test_widget_states(app, mailer):
    create_event(app, event_id="later", opens_min=30, closes_min=60, reveal_min=90)
    client = TestClient(app)
    assert "The round opens" in client.get("/e/later/widget").text

    conn = connect(app)
    conn.execute("UPDATE rounds SET status = 'closed' WHERE cohort_id = 'later'")
    conn.commit()
    assert "The round is closed" in client.get("/e/later/widget").text
    conn.execute("UPDATE rounds SET status = 'revealed' WHERE cohort_id = 'later'")
    conn.commit()
    assert "has concluded" in client.get("/e/later/widget").text
    conn.execute("UPDATE rounds SET status = 'voided' WHERE cohort_id = 'later'")
    conn.commit()
    assert "did not reach its threshold" in client.get("/e/later/widget").text
    conn.execute("DELETE FROM rounds WHERE cohort_id = 'later'")
    conn.execute("UPDATE cohorts SET is_suspended = 1 WHERE id = 'later'")
    conn.commit()
    assert "paused pending review" in client.get("/e/later/widget").text
    conn.execute("UPDATE cohorts SET is_suspended = 0 WHERE id = 'later'")
    conn.commit()
    assert "No round is scheduled here yet" in client.get("/e/later/widget").text
    conn.close()


def test_widget_weekly_cohort_and_language(app, mailer):
    conn = connect(app)
    db_mod.create_cohort(conn, "chess", "Chess", [DOMAIN], min_cohort=2)
    rounds.open_round(conn, app.state.keystore, "chess")
    conn.close()
    page = TestClient(app).get("/e/chess/widget?lang=fr")
    assert "votre adresse institutionnelle" in page.text
    assert 'lang="fr"' in page.text
    assert "lang=fr" in page.text                        # carried into the POST url


def test_widget_404s(app, mailer):
    client = TestClient(app)
    assert client.get("/e/no-such/widget").status_code == 404
    assert client.post("/e/no-such/widget", data={"email": ALICE}).status_code == 404
    assert client.get(f"/e/{COHORT}/widget").status_code == 404
    assert client.post(f"/e/{COHORT}/widget", data={"email": ALICE}).status_code == 404


def test_embed_snippet_on_edit_page(app, mailer):
    from test_organizers import org_login, create_event_http

    org = org_login(app, mailer)
    event_id, _ = create_event_http(org)
    page = org.get(f"/org/events/{event_id}/edit").text
    assert f"/e/{event_id}/widget?theme=light" in page
    assert "theme" in page and "accent" in page and "font" in page
