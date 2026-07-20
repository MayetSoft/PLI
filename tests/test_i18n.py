"""i18n: negotiation, completeness, and the participant flow in six
languages."""

from fastapi.testclient import TestClient

from pli import i18n


def test_every_key_has_every_language():
    """A missing translation would silently fall back to English; keep
    the catalogue complete by construction."""
    for key, entry in i18n.STRINGS.items():
        assert set(entry) == set(i18n.LANGUAGES), key
        assert all(entry[lang].strip() for lang in i18n.LANGUAGES), key


def test_pick_language_precedence():
    assert i18n.pick_language("de", "fr", "es") == "de"          # query wins
    assert i18n.pick_language(None, "fr", "es") == "fr"          # then cookie
    assert i18n.pick_language(None, None, "es-ES,pt;q=0.8") == "es"
    assert i18n.pick_language(None, None, "pt-BR") == "pt"       # primary tag
    assert i18n.pick_language(None, None, "sco") == "sco"
    assert i18n.pick_language("xx", "yy", "zz, zz-ZZ") == "en"   # garbage → en
    assert i18n.pick_language(None, None, "") == "en"


def test_translate_formats_and_falls_back():
    assert "3" in i18n.translate("fr", "remaining", remaining=3)
    assert i18n.translate("xx", "btn_seal") == i18n.STRINGS["btn_seal"]["en"]


def test_language_negotiation_over_http(app, mailer):
    client = TestClient(app)
    english = client.get("/", headers={"accept-language": ""})
    assert "A round is open" in english.text
    assert 'lang="en"' in english.text

    french = client.get("/?lang=fr")
    assert "Une manche est ouverte" in french.text
    assert 'lang="fr"' in french.text
    assert client.cookies.get("pli_lang") == "fr"     # choice persisted

    remembered = client.get("/")                       # cookie now speaks
    assert "Une manche est ouverte" in remembered.text

    header_only = TestClient(app).get("/", headers={"accept-language": "de-DE,de;q=0.9"})
    assert "Eine Runde ist offen" in header_only.text

    scots = TestClient(app).get("/?lang=sco")
    assert "A round is open. It steeks Friday" in scots.text


def test_tier1_completion_languages(app, mailer):
    """Italian, Dutch, Polish reach the participant flow like the rest."""
    for code in ("it", "nl", "pl"):
        assert code in i18n.LANGUAGES
    assert "Un turno è aperto" in TestClient(app).get("/?lang=it").text
    assert "Er is een ronde open" in TestClient(app).get("/?lang=nl").text
    assert "Runda jest otwarta" in TestClient(app).get("/?lang=pl").text
    # Accept-Language negotiation picks them up too.
    it = TestClient(app).get("/", headers={"accept-language": "it-IT,it;q=0.9"})
    assert 'lang="it"' in it.text


def test_full_participant_flow_in_french(app, mailer):
    from conftest import signup, declare, DOMAIN

    client = TestClient(app)
    joined = client.post("/join?lang=fr", data={"email": f"zoe@{DOMAIN}"})
    assert "Si cette adresse est éligible" in joined.text

    alice = signup(app, mailer, f"alice@{DOMAIN}")
    alice.cookies.set("pli_lang", "fr")
    assert "Il vous en reste 3" in alice.get("/declare").text
    recorded = declare(alice, f"bob@{DOMAIN}")
    assert "Enregistré. Il ne se passera plus rien avant samedi." in recorded.text
