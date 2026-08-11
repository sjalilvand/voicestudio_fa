"""Artifact staging for inbound mode, where the node cannot initiate a call.

Outbound moves bytes with RPCs the worker starts: it pulls inputs with
DownloadArtifact and pushes results with UploadResult. A node that was dialled
can do neither, so both directions are driven by the panel and the node's job
becomes staging:

  * inputs  — the panel pushes them (PushInput) *before* sending the
    assignment, so by the time the executor asks for one it is already here;
  * results — the node writes them here and names them in TaskResult; the panel
    fetches them afterwards (FetchResult).

Everything lands under one directory that is resolved with the repo's existing
containment helpers. The wire supplies task ids, attempt ids and filenames, and
none of them are trusted: this is the same asymmetry that made B13 a real
arbitrary-write bug on the control-plane side, and it is not going to be
reintroduced from the other end.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from core.path_security import UnsafePath, resolve_within, safe_filename
from worker.protocol.gen import worker_v1_pb2 as pb

logger = logging.getLogger(__name__)

# Staged bytes are deleted once fetched, but a panel that dies mid-job leaves
# them behind. Anything older than this is swept on the next write.
_STALE_SECONDS = 24 * 60 * 60


@dataclass
class _Staged:
    path: str
    sha256: str
    size_bytes: int
    created_at: float


class ArtifactStore:
    """Node-side staging for one listener. Shared across panels."""

    def __init__(self, root: str) -> None:
        self._root = os.path.abspath(root)
        self._lock = threading.Lock()
        self._out: dict[str, _Staged] = {}
        self._in: dict[str, _Staged] = {}
        os.makedirs(self._root, exist_ok=True)

    # ── Placement ─────────────────────────────────────────────────────────

    def _place(self, kind: str, artifact_id: str, filename: str) -> str:
        """Build a path under the root from wire-supplied strings, safely.

        `artifact_id` is minted here rather than taken from the wire, and the
        filename is reduced to a bare portable name before it is joined. The
        `resolve_within` call is the belt to that braces: it also rejects a
        symlink planted inside the root, which validation of the components
        alone cannot see.
        """
        name = safe_filename(filename) if filename else ""
        if not name:
            name = "artifact.bin"
        relative = os.path.join(kind, safe_filename(artifact_id), name)
        return str(resolve_within(self._root, relative))

    def _sweep_locked(self, now: float) -> None:
        for index in (self._out, self._in):
            for artifact_id, staged in list(index.items()):
                if now - staged.created_at <= _STALE_SECONDS:
                    continue
                index.pop(artifact_id, None)
                _remove_quietly(staged.path)

    # ── Results: node writes, panel fetches ───────────────────────────────

    async def publish(
        self, ref: pb.TaskRef, payload: bytes, meta: dict
    ) -> pb.ArtifactRef:
        """Stage a finished result and return the ref that names it."""
        artifact_id = uuid.uuid4().hex
        filename = str(meta.get("filename") or f"{ref.attempt_id}.wav")
        digest = hashlib.sha256(payload).hexdigest()
        path = self._place("out", artifact_id, filename)

        def write() -> None:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(payload)

        await asyncio.to_thread(write)
        now = time.time()
        with self._lock:
            self._sweep_locked(now)
            self._out[artifact_id] = _Staged(
                path=path, sha256=digest, size_bytes=len(payload), created_at=now
            )
        return pb.ArtifactRef(
            artifact_id=artifact_id,
            task_id=ref.task_id,
            attempt_id=ref.attempt_id,
            filename=os.path.basename(path),
            content_type=str(meta.get("content_type") or "audio/wav"),
            size_bytes=len(payload),
            sha256=digest,
        )

    def open_result(self, artifact_id: str) -> Optional[_Staged]:
        with self._lock:
            return self._out.get(artifact_id)

    def result_fetched(self, artifact_id: str) -> None:
        """Drop a result once the panel has it. The panel's ack is the commit
        point, so nothing is deleted on a partial read."""
        with self._lock:
            staged = self._out.pop(artifact_id, None)
        if staged is not None:
            _remove_quietly(staged.path)

    # ── Inputs: panel pushes, node reads ──────────────────────────────────

    def begin_input(self, ref: pb.ArtifactRef) -> str:
        """Reserve a staging path for an incoming push. Returns the path."""
        artifact_id = safe_filename(ref.artifact_id or uuid.uuid4().hex)
        path = self._place("in", artifact_id, ref.filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    def commit_input(self, ref: pb.ArtifactRef, path: str, digest: str, size: int) -> None:
        now = time.time()
        with self._lock:
            self._sweep_locked(now)
            self._in[ref.artifact_id] = _Staged(
                path=path, sha256=digest, size_bytes=size, created_at=now
            )

    async def stage_in(self, ref: pb.ArtifactRef, destination: str) -> None:
        """Hand a previously pushed input to the executor.

        Copied rather than moved: an attempt that is retried asks for the same
        input again, and a move would make the second attempt fail with a
        missing file that no log explains.
        """
        with self._lock:
            staged = self._in.get(ref.artifact_id)
        if staged is None:
            raise RuntimeError(
                f"the control plane did not send input {ref.artifact_id or '(unnamed)'} "
                "before assigning this task"
            )
        await asyncio.to_thread(shutil.copyfile, staged.path, destination)

    def forget_input(self, artifact_id: str) -> None:
        with self._lock:
            staged = self._in.pop(artifact_id, None)
        if staged is not None:
            _remove_quietly(staged.path)

    def purge(self) -> None:
        """Drop everything. Called when the listener stops."""
        with self._lock:
            staged = list(self._out.values()) + list(self._in.values())
            self._out.clear()
            self._in.clear()
        for item in staged:
            _remove_quietly(item.path)


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


__all__ = ["ArtifactStore", "UnsafePath"]
