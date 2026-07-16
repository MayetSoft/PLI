import secrets

import pytest

from pli.crypto import KeyStore, handle, new_round_key, seal, unseal


def test_seal_unseal_round_trip():
    key = new_round_key()
    for plaintext in ("alice@example.edu", "élodie@etu.uca.fr", "x@y.z"):
        assert unseal(key, seal(key, plaintext)) == plaintext


def test_seal_is_randomised():
    key = new_round_key()
    assert seal(key, "a@b.cd") != seal(key, "a@b.cd")


def test_unseal_wrong_key_fails():
    blob = seal(new_round_key(), "a@b.cd")
    with pytest.raises(Exception):
        unseal(new_round_key(), blob)


def test_handle_deterministic_and_pepper_bound():
    p1, p2 = secrets.token_bytes(32), secrets.token_bytes(32)
    assert handle(p1, "a@b.cd") == handle(p1, "a@b.cd")
    assert handle(p1, "a@b.cd") != handle(p2, "a@b.cd")
    assert handle(p1, "a@b.cd") != handle(p1, "x@b.cd")
    assert len(handle(p1, "a@b.cd")) == 32


def test_keystore_lifecycle(tmp_path):
    ks = KeyStore(str(tmp_path / "keys"))
    key = ks.create(1)
    assert ks.create(1) == key          # idempotent within the round
    assert ks.load(1) == key
    ks.destroy(1)
    assert ks.load(1) is None
    ks.destroy(1)                       # destroying twice is fine
