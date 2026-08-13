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

import hashlib
import json
import logging
import mimetypes
import os
import re
import shutil
import time
from typing import Iterable, Iterator, Optional

from core.db import db_conn
from core.path_security import UnsafePath, resolve_within, safe_filename
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
        pinned_worker_id=row["pinned_worker_id"],
    )
    task.attempts = sorted(attempts, key=lambda a: a.attempt_number)
    task.finished_at = row["finished_at"]
    task.deadline_at = row["deadline_at"]
    task.error = _load_error(row["error_json"])
    task.result_ref = row["result_ref"]
    task.excluded_workers = set(json.loads(row["excluded_json"] or "[]"))
    return task


# ── Input artifacts ────────────────────────────────────────────────────────
#
# A worker is another machine. Every file-valued parameter — reference audio
# for a clone, a source video for a dub — lives in ``VOICES_DIR`` or a tempdir
# on the *control plane*, so sending its path is sending a string that names
# nothing on the far side. That is why remote cloning could not work: the
# assignment carried ``ref_audio=/Users/…/voices/x.wav`` and the worker either
# failed to open it or, worse, rendered with the default voice.
#
# Staging copies those files into the artifact directory the control plane
# already serves over ``DownloadArtifact``, which refuses anything outside it.
# The copy is named by the SHA-256 of its contents, so cloning the same voice
# a hundred times keeps exactly one copy on disk and lets the worker's own
# cache skip the transfer entirely on every clone after the first.

INPUT_PARAM_KEYS: tuple[str, ...] = (
    "ref_audio",
    "reference_audio",
    "prompt_audio",
    "prompt_wav",
    "source_audio",
    "audio_path",
    "source_video",
    "video_path",
)

# Where staged inputs live under the artifact root, and the key under which a
# task records what was staged for it. The record is what makes the purge
# exact: an input is deletable only when no surviving task still refers to it.
INPUTS_DIRNAME = "inputs"
INPUTS_PARAM_KEY = "inputs"

_HASH_CHUNK_BYTES = 1024 * 1024
_SAFE_EXTENSION = re.compile(r"^\.[A-Za-z0-9]{1,8}$")


class InputStagingError(RuntimeError):
    """A task input could not be staged for transfer to a worker.

    Raised rather than swallowed: a clone whose reference audio silently went
    missing does not fail, it renders someone else's voice.
    """


def artifact_root(*, create_dir: bool = True) -> str:
    """The directory the control plane serves artifacts from.

    Imported lazily: ``worker.service`` owns the layout, and a module-level
    import here would tie the durable store to the lifecycle module that
    starts the gRPC server.
    """
    from worker.service import paths  # noqa: PLC0415 — layout owner, not a dependency

    root = paths()["artifacts"]
    if create_dir:
        os.makedirs(os.path.join(root, INPUTS_DIRNAME), exist_ok=True)
    return root


def _extension(source: str) -> str:
    """The source extension when it is a plain one, else nothing.

    Kept for the worker's benefit — soundfile sniffs content, but an engine
    that shells out to ffmpeg reads the suffix — and sanitised because the
    name is about to become a filesystem path.
    """
    suffix = os.path.splitext(str(source))[1]
    return suffix.lower() if _SAFE_EXTENSION.match(suffix) else ""


def _digest(path: str) -> tuple[str, int]:
    """(sha256, size) read in chunks — a source video is not a bytes object."""
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while True:
            block = handle.read(_HASH_CHUNK_BYTES)
            if not block:
                break
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def stage_input(source: str, *, root: Optional[str] = None, now: Optional[float] = None) -> dict:
    """Copy one input into the artifact store, keyed by its content hash.

    Returns the record that ends up on the task row. ``source`` is kept in it
    so a local fallback still has the original file, and stripped before the
    record reaches the wire.
    """
    stamp = resolve(now)
    base = root or artifact_root()
    try:
        digest, size = _digest(source)
    except OSError as exc:
        raise InputStagingError(f"Could not read the task input {source!r}: {exc}") from exc

    artifact_id = os.path.join(INPUTS_DIRNAME, f"{digest}{_extension(source)}")
    try:
        destination = resolve_within(base, artifact_id)
    except UnsafePath as exc:  # pragma: no cover — the id is ours, hex only
        raise InputStagingError(f"Refusing to stage {source!r} outside the artifact store") from exc

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Same size at a content-addressed name means the same bytes: the only
        # writer is the rename below, so a truncated file cannot exist here.
        if not (destination.is_file() and destination.stat().st_size == size):
            partial = destination.with_name(destination.name + ".part")
            shutil.copyfile(source, partial)
            os.replace(partial, destination)
        # Freshness, not decoration: the purge dates an unreferenced input by
        # its mtime, so re-using a staged voice has to renew it.
        os.utime(destination, (stamp, stamp))
    except OSError as exc:
        raise InputStagingError(f"Could not stage the task input {source!r}: {exc}") from exc

    filename = os.path.basename(str(source)) or f"{digest}{_extension(source)}"
    return {
        "artifact_id": artifact_id,
        "path": str(destination),
        "source": str(source),
        "filename": filename,
        "sha256": digest,
        "size_bytes": size,
        "content_type": mimetypes.guess_type(filename)[0] or "application/octet-stream",
    }


def _iter_input_values(params: dict) -> Iterator[tuple[str, Optional[int], str]]:
    """``(key, index, value)`` for every parameter that could name a file."""
    for key in INPUT_PARAM_KEYS:
        value = params.get(key)
        if isinstance(value, str):
            yield key, None, value
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, str):
                    yield key, index, item


def ensure_staged(
    task: Task, *, root: Optional[str] = None, now: Optional[float] = None
) -> list[dict]:
    """Stage every file-valued parameter of *task*, once.

    Idempotent by design — it runs at submission (so the durable row records
    what a later purge must keep) and again at dispatch (so a task built
    without the store, or a scheduler running unpersisted, still gets inputs
    the worker can fetch). Already-staged keys are skipped, so the second call
    does no I/O.
    """
    params = task.params if isinstance(task.params, dict) else {}
    recorded = params.get(INPUTS_PARAM_KEY)
    entries: list[dict] = [e for e in recorded if isinstance(e, dict)] if isinstance(recorded, list) else []
    if root:
        # A task may have been staged when it was submitted under the default
        # store, then dispatched by a servicer configured with another store.
        # Recorded metadata is not proof that this servicer can serve it.
        refreshed: list[dict] = []
        for entry in entries:
            artifact_id = str(entry.get("artifact_id") or "")
            try:
                available = bool(artifact_id and resolve_within(root, artifact_id).is_file())
            except UnsafePath:
                available = False
            if available:
                refreshed.append(entry)
                continue
            source = str(entry.get("source") or "")
            if source and os.path.isfile(source):
                replacement = stage_input(source, root=root, now=now)
                replacement.update(key=entry.get("key"), index=entry.get("index"))
                refreshed.append(replacement)
            else:
                raise InputStagingError(
                    f"The staged task input {artifact_id!r} is unavailable in this artifact store."
                )
        entries = refreshed
        params[INPUTS_PARAM_KEY] = entries
    covered = {(e.get("key"), e.get("index")) for e in entries}

    for key, index, value in _iter_input_values(params):
        if (key, index) in covered or not value:
            continue
        # Not every value of these keys is a file: an engine may take a voice
        # id here. Only what exists on this disk is an input.
        if not os.path.isfile(value):
            continue
        entry = stage_input(value, root=root, now=now)
        entry["key"] = key
        entry["index"] = index
        entries.append(entry)
        covered.add((key, index))

    if entries:
        params[INPUTS_PARAM_KEY] = entries
        task.params = params
    return entries


def _durable_params(params: dict) -> dict:
    """Parameters safe to persist after inputs have been staged.

    The live task keeps original paths for a possible local fallback, but the
    durable row needs only content-addressed artifact ids. In particular, it
    must never retain a user's home path in either the operation parameters or
    the staging metadata.
    """
    durable = json.loads(json.dumps(params))
    entries = durable.get(INPUTS_PARAM_KEY)
    if not isinstance(entries, list):
        return durable
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        index = entry.get("index")
        artifact_id = entry.get("artifact_id")
        if isinstance(key, str) and isinstance(artifact_id, str):
            if index is None:
                durable[key] = artifact_id
            elif isinstance(durable.get(key), list) and isinstance(index, int):
                if 0 <= index < len(durable[key]):
                    durable[key][index] = artifact_id
        entry.pop("source", None)
        entry.pop("path", None)
    return durable


def _referenced_artifacts(conn) -> set[str]:
    """Every staged input still named by a surviving task row."""
    referenced: set[str] = set()
    for row in conn.execute("SELECT params_json FROM remote_tasks").fetchall():
        try:
            params = json.loads(row["params_json"] or "{}")
            entries = params.get(INPUTS_PARAM_KEY) or []
        except (ValueError, AttributeError):
            continue
        for entry in entries:
            if isinstance(entry, dict) and entry.get("artifact_id"):
                referenced.add(str(entry["artifact_id"]))
    return referenced


def purge_artifacts(
    task_ids: Iterable[str], referenced: set[str], *, cutoff: float, root: Optional[str] = None
) -> int:
    """Delete the results of purged tasks and every input nothing points at.

    Both directions, deliberately: results are attempt-scoped and die with
    their task, while a content-hashed input is shared, so it may only go once
    no surviving task refers to it *and* it is older than the same cutoff the
    rows were judged by. Nothing here raises — a purge that fails is a disk
    that stays fuller than we wanted, not a failed request.
    """
    removed = 0
    try:
        base = root or artifact_root(create_dir=False)
    except Exception:  # pragma: no cover — no data dir at all
        logger.debug("No artifact root to purge", exc_info=True)
        return 0
    if not os.path.isdir(base):
        return 0

    for task_id in task_ids:
        try:
            path = resolve_within(base, safe_filename(task_id))
        except UnsafePath:
            continue
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
            removed += 1

    inputs_dir = os.path.join(base, INPUTS_DIRNAME)
    try:
        names = os.listdir(inputs_dir)
    except OSError:
        return removed
    for name in names:
        artifact_id = os.path.join(INPUTS_DIRNAME, name)
        if artifact_id in referenced:
            continue
        path = os.path.join(inputs_dir, name)
        try:
            if not os.path.isfile(path) or os.path.getmtime(path) >= cutoff:
                continue
            os.remove(path)
            removed += 1
        except OSError:
            logger.debug("Could not purge the staged input %s", name, exc_info=True)
    return removed


# ── Writes ─────────────────────────────────────────────────────────────────


def create(task: Task, *, project_id: Optional[str] = None, now: Optional[float] = None) -> Task:
    """Persist a new task.

    Idempotent on ``idempotency_key``: a client that retries its HTTP request
    gets the original task back rather than a second render of the same text.

    ``pinned_worker_id`` deliberately follows core.db's additive schema
    reconciliation instead of alembic: remote recovery also runs in bundled
    installs where alembic may be unavailable, and the nullable column is a
    backward-compatible affinity fact rather than a data transformation.

    Inputs are staged before the row is written, so the durable record names
    the artifacts the task owns. Persisting first would leave a task whose
    reference audio no purge can account for.
    """
    stamp = resolve(now)
    if task.idempotency_key:
        existing = get_by_idempotency_key(task.idempotency_key)
        if existing is not None:
            return existing
    ensure_staged(task, now=stamp)
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO remote_tasks "
            "(id, idempotency_key, operation, engine, model_id, params_json, priority, state, "
            " max_attempts, excluded_json, project_id, created_at, updated_at, deadline_at, pinned_worker_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task.task_id,
                task.idempotency_key,
                task.operation,
                task.engine,
                task.model_id,
                json.dumps(_durable_params(task.params)),
                int(task.priority),
                task.state.value,
                task.max_attempts,
                json.dumps(sorted(task.excluded_workers)),
                project_id,
                stamp,
                stamp,
                task.deadline_at,
                task.pinned_worker_id,
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
            "updated_at=?, deadline_at=?, finished_at=?, pinned_worker_id=? WHERE id=?",
            (
                task.state.value,
                json.dumps(sorted(task.excluded_workers)),
                _dump_error(task.error),
                task.result_ref,
                stamp,
                task.deadline_at,
                task.finished_at,
                task.pinned_worker_id,
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


def purge_finished(
    *,
    older_than_seconds: float = 7 * 24 * 3600,
    now: Optional[float] = None,
    root: Optional[str] = None,
) -> int:
    """Drop old finished tasks — rows *and* the bytes they own.

    Rows only was a leak with no ceiling: every remote render leaves a result
    artifact on disk, and every remote clone leaves a copy of the reference
    audio. Neither was ever deleted, so the feature grew the user's disk for
    as long as they used it.
    """
    cutoff = resolve(now) - older_than_seconds
    terminal = ", ".join(f"'{s.value}'" for s in TaskState if s.terminal)
    with db_conn() as conn:
        doomed = [
            row["id"]
            for row in conn.execute(
                f"SELECT id FROM remote_tasks WHERE state IN ({terminal}) AND finished_at < ?",
                (cutoff,),
            ).fetchall()
        ]
        conn.execute(
            f"DELETE FROM remote_task_attempts WHERE task_id IN "
            f"(SELECT id FROM remote_tasks WHERE state IN ({terminal}) AND finished_at < ?)",
            (cutoff,),
        )
        cur = conn.execute(
            f"DELETE FROM remote_tasks WHERE state IN ({terminal}) AND finished_at < ?", (cutoff,)
        )
        removed = cur.rowcount
        # Read the survivors inside the same transaction that deleted the
        # rows: an input is only unreferenced relative to what is left.
        referenced = _referenced_artifacts(conn)
    # Filesystem work outside the transaction — a slow rmtree must not hold
    # SQLite's write lock against the dispatch loop.
    purge_artifacts(doomed, referenced, cutoff=cutoff, root=root)
    return removed


__all__ = [
    "INPUTS_DIRNAME",
    "INPUTS_PARAM_KEY",
    "INPUT_PARAM_KEYS",
    "InputStagingError",
    "artifact_root",
    "commit_result",
    "create",
    "ensure_staged",
    "get",
    "get_by_idempotency_key",
    "is_committed",
    "list_tasks",
    "load_unfinished",
    "purge_artifacts",
    "purge_finished",
    "save",
    "stage_input",
]
