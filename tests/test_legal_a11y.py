"""Legal pages and the accessibility contract of the participant UI."""

import dataclasses

from fastapi.testclient import TestClient

from pli.app import create_app


def test_legal_pages_en_and_fr(app, mailer):
    client = TestClient(app)
    for page in ("privacy", "terms", "dpa"):
        english = client.get(f"/legal/{page}?lang=en")
        assert english.status_code == 200
        french = client.get(f"/legal/{page}?lang=fr")
        assert french.status_code == 200
        assert english.content != french.content
    assert client.get("/legal/nonsense").status_code == 404
    # German readers get the English controlled document.
    de = TestClient(app).get("/legal/privacy", headers={"accept-language": "de"})
    assert "Privacy policy" in de.text


def test_legal_pages_render_company_identity(settings, mailer):
    s = dataclasses.replace(
        settings, company_name="Plicorp SASU", company_address="1 rue du Pli, Paris",
        company_siren="123 456 789", company_contact="privacy@plicorp.example",
    )
    client = TestClient(create_app(settings=s, mailer=mailer))
    page = client.get("/legal/privacy").text
    assert "Plicorp SASU" in page and "123 456 789" in page
    assert "privacy@plicorp.example" in page
    fr = client.get("/legal/dpa?lang=fr").text
    assert "Plicorp SASU" in fr


def test_accessibility_contract(app, mailer):
    from conftest import DOMAIN, signup

    page = TestClient(app).get("/")
    assert 'lang="en"' in page.text
    assert 'class="skip"' in page.text and 'id="main"' in page.text
    assert '<label' in page.text                       # join form is labelled
    assert 'aria-label="Language"' in page.text

    alice = signup(app, mailer, f"alice@{DOMAIN}")
    declare_page = alice.get("/declare").text
    assert declare_page.count("<label") >= 3           # every target input labelled
    assert 'for="target-0"' in declare_page and 'id="target-0"' in declare_page
