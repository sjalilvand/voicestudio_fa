"""Per-panel API keys for inbound mode, and the throttle that protects them.

One key per panel, never one key for the node. A single shared key means
revoking one person kicks everybody and forces a re-paste on every machine, so
in practice nobody revokes and the credential outlives the reason it was
issued. Per-key costs nothing extra at issue time and is painful to retrofit,
because a shared key leaves no record of who used it.

Keys are stored hashed. The plaintext exists exactly once, in the response to
the issuing call, and is unrecoverable afterwards — the node cannot show a key
again later, only replace it.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from dataclasses import asdict, dataclass
from typing import Optional

from worker.identity import constant_time_equals, hash_secret

logger = logging.getLogger(__name__)

# Distinguishes an inbound panel key from the `ovw_` enrollment token used by
# outbound mode. They are never interchangeable and the prefix makes a
# pasted-the-wrong-one mistake diagnosable instead of just "invalid".
KEY_PREFIX = "ovnode_"

# 32 bytes. The same size as the enrollment-token secret, and the reason
# `hash_secret` may be a plain SHA-256 rather than a password KDF.
_KEY_BYTES = 32

# Failed-auth throttle. A key is a bearer credential with no second factor, so
# the only thing standing between a LAN attacker and unlimited guesses is this.
# The window is per source address: one panel typing a stale key must not lock
# out a different panel with a good one.
_MAX_FAILURES = 5
_LOCKOUT_SECONDS = 60.0
_FAILURE_WINDOW_SECONDS = 300.0


@dataclass
class PanelKey:
    """One panel's admission credential. The secret itself is not in here."""

    key_id: str
    label: str
    secret_hash: str
    created_at: float
    last_seen_at: float = 0.0
    last_seen_peer: str = ""
    revoked: bool = False
    # The id THIS panel assigned to this node. One per key, not one per node:
    # every panel keeps its own registry, so the same machine is a different
    # worker id to each of them. Persisted because the node signs its challenge
    # over the id, so a node that forgets it can never authenticate again —
    # the inbound equivalent of the worker-id file outbound keeps.
    worker_id: str = ""

    def public(self) -> dict:
        """The shape the UI sees. Deliberately has no field for the secret."""
        data = asdict(self)
        data.pop("secret_hash")
        return data


@dataclass
class _Failures:
    count: int = 0
    first_at: float = 0.0
    locked_until: float = 0.0


@dataclass
class IssuedKey:
    """The one and only time the plaintext exists outside the caller's hands."""

    key: PanelKey
    secret: str


class KeyStore:
    """Thread-safe, file-backed store of per-panel keys.

    Backed by a plain JSON file rather than the settings store because the
    settings store is read by the UI process and synced into places a
    credential hash has no business being.
    """

    def __init__(self, path: str, *, now: Optional[callable] = None) -> None:
        self._path = path
        self._now = now or time.time
        self._lock = threading.Lock()
        self._keys: dict[str, PanelKey] = {}
        self._failures: dict[str, _Failures] = {}
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (FileNotFoundError, PermissionError):
            return
        except (json.JSONDecodeError, UnicodeDecodeError):
            # A corrupt file must not take the node down, but it must also not
            # silently become "no keys configured" — that reads to the user as
            # "my keys vanished" with no cause anywhere.
            logger.error(
                "The inbound key file at %s is unreadable and was ignored. "
                "Existing panels cannot connect until a key is re-issued.",
                self._path,
            )
            return
        for entry in raw.get("keys", []):
            try:
                key = PanelKey(**entry)
            except TypeError:
                continue
            self._keys[key.key_id] = key

    def _save_locked(self) -> None:
        directory = os.path.dirname(os.path.abspath(self._path))
        os.makedirs(directory, exist_ok=True)
        payload = json.dumps(
            {"keys": [asdict(k) for k in self._keys.values()]}, indent=2
        ).encode("utf-8")
        tmp = f"{self._path}.tmp"
        # 0600 from creation, never a world-readable moment — the same idiom
        # `identity.save_worker_key` uses for the Ed25519 private key.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)
        os.replace(tmp, self._path)
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            # Windows and some network filesystems do not honour POSIX modes.
            pass

    # ── Issue and revoke ──────────────────────────────────────────────────

    def issue(self, label: str) -> IssuedKey:
        """Mint a key for one panel. The secret is returned exactly once."""
        secret = KEY_PREFIX + secrets.token_urlsafe(_KEY_BYTES)
        now = self._now()
        key = PanelKey(
            # Derived from the secret's hash, not from a counter: it identifies
            # the key in logs without being a second thing to store, and cannot
            # be used to reconstruct the secret.
            key_id=hash_secret(secret)[:12],
            label=label.strip() or "Panel",
            secret_hash=hash_secret(secret),
            created_at=now,
        )
        with self._lock:
            self._keys[key.key_id] = key
            self._save_locked()
        return IssuedKey(key=key, secret=secret)

    def revoke(self, key_id: str) -> bool:
        """Revoke one panel's key. Others keep working — that is the point."""
        with self._lock:
            key = self._keys.get(key_id)
            if key is None or key.revoked:
                return False
            key.revoked = True
            self._save_locked()
        return True

    def remember_worker_id(self, key_id: str, worker_id: str) -> None:
        """Record the id a panel assigned, so the next reconnect can sign for it."""
        if not worker_id:
            return
        with self._lock:
            key = self._keys.get(key_id)
            if key is None or key.worker_id == worker_id:
                return
            key.worker_id = worker_id
            self._save_locked()

    def worker_id_for(self, key_id: str) -> str:
        with self._lock:
            key = self._keys.get(key_id)
            return key.worker_id if key is not None else ""

    def list_keys(self) -> list[dict]:
        with self._lock:
            return [k.public() for k in sorted(self._keys.values(), key=lambda k: k.created_at)]

    def any_active(self) -> bool:
        with self._lock:
            return any(not k.revoked for k in self._keys.values())

    # ── Authentication ────────────────────────────────────────────────────

    def locked_out(self, peer: str) -> bool:
        with self._lock:
            record = self._failures.get(peer)
            return record is not None and record.locked_until > self._now()

    def authenticate(self, secret: str, *, peer: str = "") -> Optional[PanelKey]:
        """Return the matching live key, or None.

        Compares against every stored key in constant time and does not stop at
        the first match. Short-circuiting would make the reply time a function
        of how many keys are configured and which one matched — a slow oracle,
        but an oracle.
        """
        now = self._now()
        with self._lock:
            record = self._failures.get(peer)
            if record is not None and record.locked_until > now:
                return None

            candidate = hash_secret(secret) if secret else ""
            matched: Optional[PanelKey] = None
            for key in self._keys.values():
                if key.revoked or not candidate:
                    continue
                if constant_time_equals(key.secret_hash, candidate):
                    matched = key

            if matched is None:
                self._record_failure_locked(peer, now)
                return None

            self._failures.pop(peer, None)
            matched.last_seen_at = now
            matched.last_seen_peer = peer
            self._save_locked()
            return matched

    def _record_failure_locked(self, peer: str, now: float) -> None:
        record = self._failures.get(peer)
        if record is None or now - record.first_at > _FAILURE_WINDOW_SECONDS:
            record = _Failures(count=0, first_at=now)
            self._failures[peer] = record
        record.count += 1
        if record.count >= _MAX_FAILURES:
            record.locked_until = now + _LOCKOUT_SECONDS
            logger.warning(
                "Refusing inbound connections from %s for %.0fs after %d failed keys.",
                peer or "an unknown address",
                _LOCKOUT_SECONDS,
                record.count,
            )
