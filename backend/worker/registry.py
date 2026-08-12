"""Persistence for remote workers and their enrollment tokens.

What is durable and what is not is a deliberate split (docs/remote-workers.md):

  **Persisted** — worker identities and their public keys, revocations,
  per-worker configuration, and enrollment tokens. These must survive a restart
  because the control plane is a desktop app that restarts constantly, and a
  revocation that evaporates on quit is not a revocation.

  **Not persisted** — live sessions, heartbeats, latency, capacity snapshots,
  breaker state. All of it is rebuilt from the reconnection itself, and a
  worker is the source of truth for what it is running anyway.

Tables live in ``core/db.py:_BASE_SCHEMA`` with ``CREATE TABLE IF NOT EXISTS``,
so an existing ``omnivoice_data/`` picks them up on next open with no migration
step and no change for users who never enable the feature.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from core.db import db_conn
from worker.clock import resolve
from worker import identity

logger = logging.getLogger("omnivoice.worker")

# Default scheduling preference. Higher wins; equal priorities fall through to
# least-busy, which is the actual default behaviour for a homogeneous setup.
_DEFAULT_PRIORITY = 50


@dataclass
class RemoteWorker:
    """A worker as the control plane knows it between connections."""

    id: str
    name: str
    key_id: str
    public_key: bytes
    enabled: bool = True
    revoked: bool = False
    revoked_at: Optional[float] = None
    priority: int = _DEFAULT_PRIORITY
    endpoint: str = ""
    host: dict = field(default_factory=dict)
    capabilities: list[dict] = field(default_factory=list)
    max_concurrent_tasks: int = 1
    session_epoch: int = 0
    consent_granted_at: Optional[float] = None
    created_at: float = 0.0
    last_seen_at: Optional[float] = None

    @property
    def schedulable(self) -> bool:
        """Eligible for work at all — before any health or capacity check."""
        return self.enabled and not self.revoked and self.consent_granted_at is not None

    def to_dict(self) -> dict:
        """UI shape. The public key is never exposed beyond its short id."""
        return {
            "id": self.id,
            "name": self.name,
            "key_id": self.key_id,
            "enabled": self.enabled,
            "revoked": self.revoked,
            "priority": self.priority,
            "endpoint": self.endpoint,
            "host": self.host,
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "consent_granted": self.consent_granted_at is not None,
            "created_at": self.created_at,
            "last_seen_at": self.last_seen_at,
        }


def _row_to_worker(row) -> RemoteWorker:
    return RemoteWorker(
        id=row["id"],
        name=row["name"],
        key_id=row["key_id"],
        public_key=bytes(row["public_key"]),
        enabled=bool(row["enabled"]),
        revoked=bool(row["revoked"]),
        revoked_at=row["revoked_at"],
        priority=int(row["priority"]),
        endpoint=row["endpoint"] or "",
        host=json.loads(row["host_json"] or "{}"),
        capabilities=json.loads(row["capabilities_json"] or "[]"),
        max_concurrent_tasks=int(row["max_concurrent_tasks"]),
        session_epoch=int(row["session_epoch"]),
        consent_granted_at=row["consent_granted_at"],
        created_at=float(row["created_at"]),
        last_seen_at=row["last_seen_at"],
    )


# ── Enrollment ─────────────────────────────────────────────────────────────


def create_enrollment(
    *,
    endpoint: str,
    cert_fingerprint: str,
    label: str = "",
    ttl_seconds: int = 15 * 60,
    now: Optional[float] = None,
) -> identity.EnrollmentToken:
    """Mint a join token and store only its hash."""
    stamp = resolve(now)
    token = identity.mint_enrollment_token(
        endpoint=endpoint,
        cert_fingerprint=cert_fingerprint,
        ttl_seconds=ttl_seconds,
        now=stamp,
    )
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO remote_worker_enrollments "
            "(token_id, secret_hash, endpoint, cert_fingerprint, label, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                token.token_id,
                token.secret_hash,
                endpoint,
                cert_fingerprint,
                label,
                stamp,
                token.expires_at,
            ),
        )
    return token


def redeem_enrollment(
    token: identity.EnrollmentToken, *, worker_id: str, now: Optional[float] = None
) -> bool:
    """Consume a join token. Returns False if it is unknown, spent, or expired.

    Single-use is enforced here with a conditional UPDATE rather than a
    read-then-write so two workers racing the same token cannot both win.
    """
    stamp = resolve(now)
    with db_conn() as conn:
        row = conn.execute(
            "SELECT secret_hash, expires_at, used_at FROM remote_worker_enrollments WHERE token_id = ?",
            (token.token_id,),
        ).fetchone()
        if row is None:
            return False
        if row["used_at"] is not None:
            return False
        if stamp > float(row["expires_at"]):
            return False
        if not identity.constant_time_equals(row["secret_hash"], token.secret_hash):
            return False
        cur = conn.execute(
            "UPDATE remote_worker_enrollments SET used_at = ?, used_by_worker = ? "
            "WHERE token_id = ? AND used_at IS NULL",
            (stamp, worker_id, token.token_id),
        )
        return cur.rowcount == 1


def purge_expired_enrollments(*, now: Optional[float] = None) -> int:
    stamp = resolve(now)
    with db_conn() as conn:
        cur = conn.execute(
            "DELETE FROM remote_worker_enrollments WHERE used_at IS NULL AND expires_at < ?",
            (stamp,),
        )
        return cur.rowcount


# ── Workers ────────────────────────────────────────────────────────────────


def enroll_worker(
    *,
    name: str,
    public_key: bytes,
    endpoint: str = "",
    host: Optional[dict] = None,
    capabilities: Optional[list[dict]] = None,
    max_concurrent_tasks: int = 1,
    consent_granted: bool = True,
    now: Optional[float] = None,
) -> RemoteWorker:
    """Register a new worker against the public key it generated.

    ``consent_granted`` records the user's explicit yes to sending their audio
    to this machine. It is stored per worker, not globally: agreeing to use
    your own desktop is not agreeing to use someone else's.
    """
    stamp = resolve(now)
    key_id = identity.key_id_for(public_key)
    existing = get_by_key_id(key_id)
    if existing is not None:
        return existing
    worker = RemoteWorker(
        id=uuid.uuid4().hex[:12],
        name=name or key_id,
        key_id=key_id,
        public_key=public_key,
        endpoint=endpoint,
        host=host or {},
        capabilities=capabilities or [],
        max_concurrent_tasks=max(1, int(max_concurrent_tasks)),
        consent_granted_at=stamp if consent_granted else None,
        created_at=stamp,
    )
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO remote_workers "
            "(id, name, key_id, public_key, enabled, revoked, priority, endpoint, host_json, "
            " capabilities_json, max_concurrent_tasks, session_epoch, consent_granted_at, created_at) "
            "VALUES (?, ?, ?, ?, 1, 0, ?, ?, ?, ?, ?, 0, ?, ?)",
            (
                worker.id,
                worker.name,
                worker.key_id,
                worker.public_key,
                worker.priority,
                worker.endpoint,
                json.dumps(worker.host),
                json.dumps(worker.capabilities),
                worker.max_concurrent_tasks,
                worker.consent_granted_at,
                worker.created_at,
            ),
        )
    logger.info("Enrolled remote worker %s (%s)", worker.name, worker.key_id)
    return worker


def get(worker_id: str) -> Optional[RemoteWorker]:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM remote_workers WHERE id = ?", (worker_id,)).fetchone()
    return _row_to_worker(row) if row else None


def get_by_key_id(key_id: str) -> Optional[RemoteWorker]:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM remote_workers WHERE key_id = ?", (key_id,)).fetchone()
    return _row_to_worker(row) if row else None


def list_workers(*, include_revoked: bool = False) -> list[RemoteWorker]:
    sql = "SELECT * FROM remote_workers"
    if not include_revoked:
        sql += " WHERE revoked = 0"
    sql += " ORDER BY priority DESC, created_at ASC"
    with db_conn() as conn:
        rows = conn.execute(sql).fetchall()
    return [_row_to_worker(r) for r in rows]


def begin_session(worker_id: str, *, now: Optional[float] = None) -> int:
    """Bump and return the worker's session epoch.

    Every reconnect gets a new epoch, which is what lets the server drop
    messages from a half-open previous stream — the zombie-session race that
    otherwise delivers two accepts for one assignment.
    """
    stamp = resolve(now)
    with db_conn() as conn:
        conn.execute(
            "UPDATE remote_workers SET session_epoch = session_epoch + 1, last_seen_at = ? WHERE id = ?",
            (stamp, worker_id),
        )
        row = conn.execute(
            "SELECT session_epoch FROM remote_workers WHERE id = ?", (worker_id,)
        ).fetchone()
    return int(row["session_epoch"]) if row else 0


def touch(worker_id: str, *, now: Optional[float] = None) -> None:
    with db_conn() as conn:
        conn.execute(
            "UPDATE remote_workers SET last_seen_at = ? WHERE id = ?", (resolve(now), worker_id)
        )


def update_capabilities(
    worker_id: str,
    *,
    capabilities: list[dict],
    host: Optional[dict] = None,
    max_concurrent_tasks: Optional[int] = None,
) -> None:
    sets = ["capabilities_json = ?"]
    params: list = [json.dumps(capabilities)]
    if host is not None:
        sets.append("host_json = ?")
        params.append(json.dumps(host))
    if max_concurrent_tasks is not None:
        sets.append("max_concurrent_tasks = ?")
        params.append(max(1, int(max_concurrent_tasks)))
    params.append(worker_id)
    with db_conn() as conn:
        conn.execute(f"UPDATE remote_workers SET {', '.join(sets)} WHERE id = ?", params)


def set_enabled(worker_id: str, enabled: bool) -> None:
    with db_conn() as conn:
        conn.execute(
            "UPDATE remote_workers SET enabled = ? WHERE id = ?", (1 if enabled else 0, worker_id)
        )


def set_priority(worker_id: str, priority: int) -> None:
    with db_conn() as conn:
        conn.execute(
            "UPDATE remote_workers SET priority = ? WHERE id = ?",
            (max(0, min(100, int(priority))), worker_id),
        )


def rename(worker_id: str, name: str) -> None:
    with db_conn() as conn:
        conn.execute("UPDATE remote_workers SET name = ? WHERE id = ?", (name, worker_id))


def revoke(worker_id: str, *, now: Optional[float] = None) -> bool:
    """Permanently refuse this worker's key.

    Revocation is a tombstone, not a delete: the row stays so a reconnect with
    the same key is recognised and refused rather than treated as a stranger
    who could simply enroll again.
    """
    stamp = resolve(now)
    with db_conn() as conn:
        cur = conn.execute(
            "UPDATE remote_workers SET revoked = 1, revoked_at = ?, enabled = 0 WHERE id = ?",
            (stamp, worker_id),
        )
    if cur.rowcount:
        logger.info("Remote worker revoked")
    return bool(cur.rowcount)


def is_revoked(key_id: str) -> bool:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT revoked FROM remote_workers WHERE key_id = ?", (key_id,)
        ).fetchone()
    return bool(row and row["revoked"])


def grant_consent(worker_id: str, *, now: Optional[float] = None) -> None:
    with db_conn() as conn:
        conn.execute(
            "UPDATE remote_workers SET consent_granted_at = ? WHERE id = ?",
            (resolve(now), worker_id),
        )


def authenticate(
    *,
    key_id: str,
    public_key: bytes,
    challenge: bytes,
    signature: bytes,
    nonce: bytes,
    session_epoch: int,
) -> Optional[RemoteWorker]:
    """Verify a reconnecting worker's possession of its enrolled key.

    Returns the worker on success, ``None`` on any failure — unknown key,
    revoked worker, key mismatch, or bad signature. The caller must not
    distinguish between these in what it tells the network.
    """
    worker = get_by_key_id(key_id)
    if worker is None or worker.revoked:
        return None
    if not identity.constant_time_equals(
        identity.key_id_for(worker.public_key), identity.key_id_for(public_key)
    ):
        return None
    if worker.public_key != public_key:
        return None
    message = identity.challenge_message(
        challenge=challenge,
        worker_id=worker.id,
        session_epoch=session_epoch,
        nonce=nonce,
    )
    if not identity.verify_signature(public_key, message, signature):
        return None
    return worker


__all__ = [
    "RemoteWorker",
    "authenticate",
    "begin_session",
    "create_enrollment",
    "enroll_worker",
    "get",
    "get_by_key_id",
    "grant_consent",
    "is_revoked",
    "list_workers",
    "purge_expired_enrollments",
    "redeem_enrollment",
    "rename",
    "revoke",
    "set_enabled",
    "set_priority",
    "touch",
    "update_capabilities",
]
