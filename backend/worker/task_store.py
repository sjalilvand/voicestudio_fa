"""Durable task state for remote work.

The local ``core/job_store.py`` marks every in-flight job failed on startup,
because a local job died with the process that was running it. Remote tasks
invert that: the control plane is a desktop app the user quits at will, and the
GPU on the other machine keeps rendering regardless. So restart must *recover*
in-flight tasks, not bury them.

The one ordering rule that makes at-least-once delivery safe:

    persist the result, THEN send RESULT_ACK

If the acknowledgement goes first and the server dies before writing, the
worker has been told it may drop its copy — and a forty-minute dub is gone with
no error anywhere. ``commit_result`` writes inside the same transaction that
flips the task to completed, so the ack can only follow a durable fact.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Iterable, Optional

from core.db import db_conn
from worker.clock import resolve
from worker.errors import ErrorClass, WorkerError
from worker.lifecycle import Attempt, AttemptState, PriorityClass, Task, TaskState

logger = logging.getLogger("omnivoice.worker")


def _dump_error(error: Optional[WorkerError]) -> Optional[str]:
    return json.dumps(error.to_dict()) if error else None


def _load_error(raw: Optional[str]) -> Optional[WorkerError]:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return WorkerError(
            error_class=ErrorClass(data["error_class"]),
            code=data.get("code", "UNKNOWN"),
            message=data.get("message", ""),
            hint=data.get("hint", ""),
        )
    except Exception:
        return None


def _row_to_attempt(row) -> Attempt:
    attempt = Attempt(
        attempt_id=row["id"],
        task_id=row["task_id"],
        worker_id=row["worker_id"],
        session_epoch=int(row["session_epoch"]),
        attempt_number=int(row["attempt_number"]),
        state=AttemptState(row["state"]),
        created_at=float(row["created_at"]),
    )
    attempt.accepted_at = row["accepted_at"]
    attempt.started_at = row["started_at"]
    attempt.finished_at = row["finished_at"]
    attempt.lease_expires_at = row["lease_expires_at"]
    attempt.grace_expires_at = row["grace_expires_at"]
    attempt.progress = float(row["progress"])
    attempt.stage = row["stage"] or ""
    attempt.error = _load_error(row["error_json"])
    return attempt


def _row_to_task(row, attempts: list[Attempt]) -> Task:
    task = Task(
        task_id=row["id"],
        operation=row["operation"],
        engine=row["engine"] or "",
        model_id=row["model_id"] or "",
        params=json.loads(row["params_json"] or "{}"),
        priority=PriorityClass(int(row["priority"])),
        idempotency_key=row["idempotency_key"],
        state=TaskState(row["state"]),
        max_attempts=int(row["max_attempts"]),
        created_at=float(row["created_at"]),
    )
    task.attempts = sorted(attempts, key=lambda a: a.attempt_number)
    task.finished_at = row["finished_at"]
    task.deadline_at = row["deadline_at"]
    task.error = _load_error(row["error_json"])
    task.result_ref = row["result_ref"]
    task.excluded_workers = set(json.loads(row["excluded_json"] or "[]"))
    return task


# ── Writes ─────────────────────────────────────────────────────────────────


def create(task: Task, *, project_id: Optional[str] = None, now: Optional[float] = None) -> Task:
    """Persist a new task.

    Idempotent on ``idempotency_key``: a client that retries its HTTP request
    gets the original task back rather than a second render of the same text.
    """
    stamp = resolve(now)
    if task.idempotency_key:
        existing = get_by_idempotency_key(task.idempotency_key)
        if existing is not None:
            return existing
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO remote_tasks "
            "(id, idempotency_key, operation, engine, model_id, params_json, priority, state, "
            " max_attempts, excluded_json, project_id, created_at, updated_at, deadline_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task.task_id,
                task.idempotency_key,
                task.operation,
                task.engine,
                task.model_id,
                json.dumps(task.params),
                int(task.priority),
                task.state.value,
                task.max_attempts,
                json.dumps(sorted(task.excluded_workers)),
                project_id,
                stamp,
                stamp,
                task.deadline_at,
            ),
        )
    return task


def _upsert_attempts(conn, task: Task) -> None:
    """Write every attempt, inserting the ones we have not seen before.

    Upsert rather than UPDATE in both writers: a blind UPDATE silently drops an
    attempt whose row does not exist yet, which loses the audit trail for the
    exact case that matters — a task whose first persisted state is its
    completion.
    """
    for attempt in task.attempts:
        conn.execute(
            "INSERT INTO remote_task_attempts "
            "(id, task_id, worker_id, session_epoch, attempt_number, state, progress, stage, "
            " error_json, created_at, accepted_at, started_at, finished_at, lease_expires_at, "
            " grace_expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET state=excluded.state, progress=excluded.progress, "
            " stage=excluded.stage, error_json=excluded.error_json, accepted_at=excluded.accepted_at, "
            " started_at=excluded.started_at, finished_at=excluded.finished_at, "
            " lease_expires_at=excluded.lease_expires_at, grace_expires_at=excluded.grace_expires_at",
            (
                attempt.attempt_id,
                attempt.task_id,
                attempt.worker_id,
                attempt.session_epoch,
                attempt.attempt_number,
                attempt.state.value,
                attempt.progress,
                attempt.stage,
                _dump_error(attempt.error),
                attempt.created_at,
                attempt.accepted_at,
                attempt.started_at,
                attempt.finished_at,
                attempt.lease_expires_at,
                attempt.grace_expires_at,
            ),
        )


def save(task: Task, *, now: Optional[float] = None) -> None:
    """Write the whole task + attempt graph.

    Deliberately a full rewrite rather than a diff: the graph is tiny, and a
    partial update is how a state machine and its persistence drift apart.
    """
    stamp = resolve(now)
    with db_conn() as conn:
        conn.execute(
            "UPDATE remote_tasks SET state=?, excluded_json=?, error_json=?, result_ref=?, "
            "updated_at=?, deadline_at=?, finished_at=? WHERE id=?",
            (
                task.state.value,
                json.dumps(sorted(task.excluded_workers)),
                _dump_error(task.error),
                task.result_ref,
                stamp,
                task.deadline_at,
                task.finished_at,
                task.task_id,
            ),
        )
        _upsert_attempts(conn, task)


def commit_result(
    task: Task, *, result_json: Optional[dict] = None, now: Optional[float] = None
) -> None:
    """Durably record a completed task. Must return before RESULT_ACK is sent.

    Everything lands in one transaction, so there is no window in which the
    task looks complete but its result reference is missing.
    """
    stamp = resolve(now)
    with db_conn() as conn:
        conn.execute(
            "UPDATE remote_tasks SET state=?, result_ref=?, result_json=?, updated_at=?, "
            "finished_at=?, error_json=NULL WHERE id=?",
            (
                task.state.value,
                task.result_ref,
                json.dumps(result_json or {}),
                stamp,
                task.finished_at or stamp,
                task.task_id,
            ),
        )
        _upsert_attempts(conn, task)


def is_committed(task_id: str) -> bool:
    """Has this task already been durably committed?

    The guard for a redelivered result after a control-plane restart: the
    in-memory task graph is gone, but the fact is on disk.
    """
    with db_conn() as conn:
        row = conn.execute(
            "SELECT state, result_ref FROM remote_tasks WHERE id = ?", (task_id,)
        ).fetchone()
    return bool(row and row["state"] == TaskState.COMPLETED.value)


# ── Reads ──────────────────────────────────────────────────────────────────


def _attempts_for(conn, task_id: str) -> list[Attempt]:
    rows = conn.execute(
        "SELECT * FROM remote_task_attempts WHERE task_id = ? ORDER BY attempt_number ASC",
        (task_id,),
    ).fetchall()
    return [_row_to_attempt(r) for r in rows]


def get(task_id: str) -> Optional[Task]:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM remote_tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return _row_to_task(row, _attempts_for(conn, task_id))


def get_by_idempotency_key(key: str) -> Optional[Task]:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM remote_tasks WHERE idempotency_key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_task(row, _attempts_for(conn, row["id"]))


def load_unfinished() -> list[Task]:
    """Every task that was still live when the control plane stopped.

    Called at startup. These are NOT failed — the workers holding them may
    still be rendering, and reconciliation decides each one's fate once the
    workers reconnect.
    """
    live = ", ".join(f"'{s.value}'" for s in TaskState if not s.terminal)
    with db_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM remote_tasks WHERE state IN ({live}) ORDER BY priority ASC, created_at ASC"
        ).fetchall()
        return [_row_to_task(r, _attempts_for(conn, r["id"])) for r in rows]


def list_tasks(*, states: Optional[Iterable[TaskState]] = None, limit: int = 100) -> list[Task]:
    sql = "SELECT * FROM remote_tasks"
    params: list = []
    if states:
        placeholders = ", ".join("?" for _ in states)
        sql += f" WHERE state IN ({placeholders})"
        params.extend(s.value for s in states)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with db_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_task(r, _attempts_for(conn, r["id"])) for r in rows]


def purge_finished(*, older_than_seconds: float = 7 * 24 * 3600, now: Optional[float] = None) -> int:
    cutoff = resolve(now) - older_than_seconds
    terminal = ", ".join(f"'{s.value}'" for s in TaskState if s.terminal)
    with db_conn() as conn:
        conn.execute(
            f"DELETE FROM remote_task_attempts WHERE task_id IN "
            f"(SELECT id FROM remote_tasks WHERE state IN ({terminal}) AND finished_at < ?)",
            (cutoff,),
        )
        cur = conn.execute(
            f"DELETE FROM remote_tasks WHERE state IN ({terminal}) AND finished_at < ?", (cutoff,)
        )
        return cur.rowcount


__all__ = [
    "commit_result",
    "create",
    "get",
    "get_by_idempotency_key",
    "is_committed",
    "list_tasks",
    "load_unfinished",
    "purge_finished",
    "save",
]
