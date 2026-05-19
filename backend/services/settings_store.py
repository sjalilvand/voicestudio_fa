"""Encrypted settings store for OmniVoice — AUTH-02 + threat T-01-01.

Persists small key/value rows in the SQLite `settings` table. The `hf_token`
row is encrypted at rest via Fernet (symmetric AEAD). The Fernet key itself
is derived per-install in `_secret_key.derive_fernet_key()` so a copied
omnivoice.db is not a smoking gun on another machine.

Public API (consumed by `token_resolver.py`):
    get_hf_token() -> Optional[str]
    set_hf_token(token: str) -> None
    clear_hf_token() -> None
"""
from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger("omnivoice.settings_store")

_TOKEN_KEY = "hf_token"


def _fernet():
    """Build a Fernet instance from the derived per-install key.

    Lazy import of cryptography keeps the module importable even if the
    dep ever falls out of the install (graceful warn instead of ImportError
    at module load).
    """
    from cryptography.fernet import Fernet
    from services._secret_key import derive_fernet_key

    return Fernet(derive_fernet_key())


def get_hf_token() -> Optional[str]:
    """Return the decrypted HF token from the settings table, or None.

    On `InvalidToken` (e.g. user migrated omnivoice_data/ across machines so
    machine-id no longer matches the salt used to encrypt), log a warning
    and return None — the caller's cascade (env / HF-CLI) takes over
    naturally. Per Open Question #5 in 01-RESEARCH.md.
    """
    from core.db import db_conn

    try:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (_TOKEN_KEY,)
            ).fetchone()
        if row is None or not row[0]:
            return None
        blob = row[0]
        try:
            from cryptography.fernet import InvalidToken
        except ImportError:  # pragma: no cover — dep should always be present
            logger.error("cryptography unavailable; cannot decrypt HF token")
            return None
        try:
            return _fernet().decrypt(blob.encode("ascii")).decode("utf-8")
        except InvalidToken:
            logger.warning(
                "Stored HF token failed to decrypt — most likely the install "
                "moved across machines or the salt row was tampered with. "
                "Falling back to env/HF-CLI sources."
            )
            return None
    except Exception:
        # SQLite errors must not break the resolver — return None and let
        # the resolver cascade.
        logger.exception("settings_store.get_hf_token: SQLite read failed")
        return None


def set_hf_token(token: str) -> None:
    """Persist an encrypted HF token. The first call also writes the per-install
    salt row inside the same transaction (atomic, no torn state)."""
    if not token:
        # Defense in depth — callers should pass a non-empty string. An empty
        # token in the cascade is the same as "no token" and we should not
        # write a row that round-trips to the empty string.
        clear_hf_token()
        return

    from core.db import db_conn

    # Derive the key first — this lazily generates the salt row on first
    # write, inside its own transaction. Subsequent ops use the cached key.
    cipher = _fernet()
    blob = cipher.encrypt(token.encode("utf-8")).decode("ascii")

    with db_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value, updated_at) "
            "VALUES (?, ?, ?)",
            (_TOKEN_KEY, blob, time.time()),
        )


def clear_hf_token() -> None:
    """Remove the HF token row. The salt row is preserved so a re-save by
    the same user on the same machine produces ciphertext the resolver can
    still decrypt."""
    from core.db import db_conn

    with db_conn() as conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (_TOKEN_KEY,))
