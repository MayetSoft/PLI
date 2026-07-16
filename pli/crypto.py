"""Crypto helpers. Be honest about what this buys (HANDOFF.md §6).

handle  = HMAC-SHA256(pepper, normalised_email)   — opaque identifier
contact = AES-256-GCM(round_key, email)           — only path back to an address

This protects a database dump. It does NOT protect against the operator,
who holds the pepper. State that plainly; never claim more.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_LEN = 12
KEY_LEN = 32


def handle(pepper: bytes, normalised_email: str) -> bytes:
    return hmac.new(pepper, normalised_email.encode("utf-8"), hashlib.sha256).digest()


def new_round_key() -> bytes:
    return secrets.token_bytes(KEY_LEN)


def seal(round_key: bytes, plaintext: str) -> bytes:
    nonce = secrets.token_bytes(NONCE_LEN)
    return nonce + AESGCM(round_key).encrypt(nonce, plaintext.encode("utf-8"), None)


def unseal(round_key: bytes, blob: bytes) -> str:
    return AESGCM(round_key).decrypt(bytes(blob[:NONCE_LEN]), bytes(blob[NONCE_LEN:]), None).decode("utf-8")


class KeyStore:
    """Per-round keys, one file each, outside the database.

    Never in the DB, never in git, destroyed after reveal. File-backed
    (0600) rather than memory-only so a mid-round restart does not void
    the round; the directory must never be backed up.
    """

    def __init__(self, keys_dir: str):
        self.dir = Path(keys_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.dir, 0o700)

    def _path(self, round_id: int) -> Path:
        return self.dir / f"round-{round_id}.key"

    def create(self, round_id: int) -> bytes:
        path = self._path(round_id)
        if path.exists():
            return path.read_bytes()
        key = new_round_key()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(key)
        return key

    def load(self, round_id: int) -> bytes | None:
        path = self._path(round_id)
        if not path.exists():
            return None
        return path.read_bytes()

    def destroy(self, round_id: int) -> None:
        path = self._path(round_id)
        if path.exists():
            # Overwrite before unlink; best-effort against journaling FS.
            with open(path, "r+b") as fh:
                fh.write(b"\x00" * KEY_LEN)
                fh.flush()
                os.fsync(fh.fileno())
            path.unlink()
