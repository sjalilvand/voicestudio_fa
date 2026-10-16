"""The Cloud sync loop: pull, apply with a three-way merge, push the outbox.

vssaas desktop-app-guide §6-7. One round at a time; every request goes
through the client, which raises ``CloudOff`` when the user switched sync off.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

import httpx

from core import change_hooks
from services.cloud_sync import allowlist
from services.cloud_sync.client import CloudOff, SyncApiError
from services.cloud_sync.merge import canonical, merge_item
from services.cloud_sync.store import BaseItem, OutboxRow, SyncStore

logger = logging.getLogger("omnivoice.cloud_sync")

#: Highest ``schema_version`` this app understands, per collection.
SUPPORTED = {"settings": 1, "shortcuts": 1, "favorites": 1, "device-preferences": 1}
DEVICE_PREFERENCES = "device-preferences"
MAX_CONFLICT_ROUNDS = 3
BATCH_THRESHOLD = 10
BATCH_MAX = 100
MASS_DELETE_COUNT = 20
MASS_DELETE_SHARE = 0.25
_FATAL = {"device_revoked", "account_suspended"}

DEFAULT_CHOICES = {
    "settings": True, "shortcuts": True, "favorites": True, "voices": False, "voice_consent": False,
    "takes": "off", "projects": False, "dub_projects": False, "dub_media": False, "dictation_history": False,
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _values(item: Optional[dict | BaseItem]) -> Optional[dict]:
    """The ``values`` of a server item or base; ``None`` for a tombstone or nothing."""
    if item is None:
        return None
    if isinstance(item, BaseItem):
        return None if item.deleted or item.content is None else dict(item.content.get("values") or {})
    if item.get("deleted") or item.get("content") is None:
        return None
    return dict(item["content"].get("values") or {})


@dataclass
class Status:
    conflicts: list[dict] = field(default_factory=list)
    needs_update: set[str] = field(default_factory=set)
    paused: dict[str, str] = field(default_factory=dict)
    storage_full: bool = False
    read_only: bool = False
    offline: bool = False
    stopped: Optional[str] = None
    pending_mass_delete: Optional[dict] = None
    last_sync_at: Optional[str] = None


class _StopRound(Exception):
    pass


class SyncEngine:
    def __init__(self, store: SyncStore, client: Any, organization_id: str, *,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 on_local_change: Optional[Callable[[], None]] = None) -> None:
        self.store = store
        self.client = client
        self.org = organization_id
        self.sleep = sleep
        self.status = Status()
        self.page_size = 500
        self._lock = asyncio.Lock()
        self._deletes_confirmed = False
        self._on_local_change = on_local_change
        #: Collections just switched off with "Also remove from the cloud": their deletes still go out.
        self.draining: set[str] = set()

    # ── wiring ─────────────────────────────────────────────────────────
    def attach_hooks(self) -> Callable[[], None]:
        def on_change(source: str, key: str) -> None:
            item = allowlist.item_for(source, key)
            if item is not None:
                self.local_changed(item.collection, item.item_id)

        return change_hooks.subscribe(on_change)

    def local_changed(self, collection: str, item_id: str) -> None:
        self.store.queue(self.org, collection, item_id, "put")
        if self._on_local_change:
            self._on_local_change()

    def confirm_deletes(self) -> None:
        self._deletes_confirmed = True
        self.status.pending_mass_delete = None

    def chosen(self) -> set[str]:
        state = self.store.state(self.org)
        choices = state.choices if state else {}
        picked = {name for name, collections in allowlist.CHOICE_COLLECTIONS.items() if choices.get(name)}
        return {c for name in picked for c in allowlist.CHOICE_COLLECTIONS[name]} | {DEVICE_PREFERENCES}

    def full_choices(self) -> dict:
        state = self.store.state(self.org)
        return {**DEFAULT_CHOICES, **{k: v for k, v in (state.choices if state else {}).items() if k in DEFAULT_CHOICES}}

    async def publish_choices(self) -> None:
        state = self.store.state(self.org)
        if state and state.device_id:
            self.store.queue(self.org, DEVICE_PREFERENCES, state.device_id, "put")

    # ── one round ──────────────────────────────────────────────────────
    async def run_once(self) -> None:
        async with self._lock:
            if self.status.stopped:
                return
            state = self.store.state(self.org)
            if state is None or not state.enabled:
                return
            first = state.last_full_sync_at is None
            try:
                if first:
                    self._seed_local_items()
                await self._pull()
                await self._push()
                if first:
                    self.store.save_state(self.org, last_full_sync_at=_now())
                self.status.last_sync_at = _now()
            except (CloudOff, _StopRound):
                pass
            except SyncApiError as error:
                self._fatal_or_offline(error)
            except httpx.HTTPError:
                self.status.offline = True

    async def pull(self) -> None:
        async with self._lock:
            try:
                await self._pull()
            except (CloudOff, _StopRound):
                pass

    async def push(self) -> None:
        async with self._lock:
            try:
                await self._push()
            except (CloudOff, _StopRound):
                pass
            except httpx.HTTPError:
                self.status.offline = True

    # ── pull ───────────────────────────────────────────────────────────
    def _seed_local_items(self) -> None:
        """First sync (or sync turned back on): queue local items that differ from the base."""
        chosen = self.chosen()
        for item in allowlist.ITEMS:
            if item.collection not in chosen:
                continue
            local = item.read()
            base = self.store.item(self.org, item.collection, item.item_id)
            if not local and base is None:
                continue
            if base is None or canonical(local) != canonical(_values(base) or {}):
                self.store.queue(self.org, item.collection, item.item_id, "put")

    async def _pull(self, *, resync: bool = False) -> set[tuple[str, str]]:
        state = self.store.state(self.org)
        cursor = 0 if resync else (state.cursor if state else 0)
        seen: set[tuple[str, str]] = set()
        collections = sorted(self.chosen())
        while True:
            try:
                page = await self.client.changes(since=cursor, collections=collections, limit=self.page_size)
            except SyncApiError as error:
                if error.code == "sync_cursor_expired" and not resync:
                    await self._full_resync()
                    return seen
                raise
            applied = []
            for remote in page.get("changes") or []:
                seen.add((remote["collection"], remote["item_id"]))
                if self._apply_remote(remote):
                    applied.append(remote)
            cursor = int(page.get("cursor") or cursor)
            self.store.save_page(self.org, applied, cursor)
            self.status.offline = False
            if not page.get("has_more"):
                return seen

    async def _full_resync(self) -> None:
        self.store.save_state(self.org, cursor=0)
        seen = await self._pull(resync=True)
        for collection in self.chosen():
            for base in self.store.items(self.org, collection):
                if (base.collection, base.item_id) in seen:
                    continue
                definition = allowlist.item(base.collection, base.item_id)
                if self.store.outbox_row(self.org, base.collection, base.item_id):
                    # Changed here since the last sync: push it as a new item.
                    self.store.forget_item(self.org, base.collection, base.item_id)
                    continue
                if definition is not None:
                    with change_hooks.from_sync():
                        definition.write({})  # deleted elsewhere
                self.store.forget_item(self.org, base.collection, base.item_id)

    def _apply_remote(self, remote: dict) -> bool:
        """Apply one pulled item; ``True`` means it becomes the new merge base."""
        collection, item_id = remote["collection"], remote["item_id"]
        base = self.store.item(self.org, collection, item_id)
        if base and base.revision >= int(remote["revision"]):
            return False  # already have it, or our own echo
        if int(remote.get("schema_version") or 1) > SUPPORTED.get(collection, 1):
            self.status.needs_update.add(collection)
            return False
        definition = allowlist.item(collection, item_id)
        if definition is None:
            return True  # another device's preferences, or a group this version does not know
        remote_values = _values(remote)
        row = self.store.outbox_row(self.org, collection, item_id)
        if row is None:
            self._write(definition, remote_values)
            return True
        local = None if row.op == "delete" else definition.read()
        merged = merge_item(_values(base), local, remote_values)
        self._note_conflicts(collection, item_id, merged.conflicts)
        self._write(definition, merged.values)
        if merged.values is None:
            if remote_values is None:
                self.store.drop_outbox(row.id)
            else:
                self.store.queue(self.org, collection, item_id, "delete")
        elif remote_values is not None and canonical(merged.values) == canonical(remote_values):
            self.store.drop_outbox(row.id)  # nothing left to push
        else:
            self.store.queue(self.org, collection, item_id, "put")
        return True

    def _write(self, definition: allowlist.Item, values: Optional[dict]) -> None:
        with change_hooks.from_sync():
            definition.write(values or {})

    def _note_conflicts(self, collection: str, item_id: str, keys: list[str]) -> None:
        if keys:
            self.status.conflicts.append({"collection": collection, "item_id": item_id, "keys": keys, "at": _now()})
            del self.status.conflicts[:-20]

    # ── push ───────────────────────────────────────────────────────────
    def _local_values(self, row: OutboxRow) -> Optional[dict]:
        if row.op == "delete":
            return None
        if row.collection == DEVICE_PREFERENCES:
            return {"choices": self.full_choices()}
        definition = allowlist.item(row.collection, row.item_id)
        return definition.read() if definition else None

    def _guard_mass_delete(self, rows: list[OutboxRow]) -> list[OutboxRow]:
        deletes = [r for r in rows if r.op == "delete"]
        if not deletes or self._deletes_confirmed:
            return rows
        by_collection: dict[str, int] = {}
        for row in deletes:
            by_collection[row.collection] = by_collection.get(row.collection, 0) + 1
        too_many = len(deletes) > MASS_DELETE_COUNT or any(
            count > MASS_DELETE_SHARE * max(1, len(self.store.items(self.org, c)))
            for c, count in by_collection.items()
        )
        if not too_many:
            return rows
        self.status.pending_mass_delete = {"count": len(deletes)}
        return [r for r in rows if r.op != "delete"]

    async def _push(self) -> None:
        if self.status.stopped or self.status.read_only:
            return
        chosen = self.chosen()
        rows = [r for r in self.store.outbox(self.org)
                if (r.collection in chosen or (r.collection in self.draining and r.op == "delete"))
                and r.collection not in self.status.paused]
        rows = self._guard_mass_delete(rows)
        skip: set[str] = set()
        if len(rows) > BATCH_THRESHOLD and await self._push_batch(rows[:BATCH_MAX]):
            rows = rows[BATCH_MAX:]
        for row in rows:
            if row.collection in skip:
                continue
            outcome = await self._push_row(row)
            if outcome == "skip_collection":
                skip.add(row.collection)
        self._deletes_confirmed = False

    def _operation(self, row: OutboxRow) -> Optional[dict]:
        base = self.store.item(self.org, row.collection, row.item_id)
        if_match = base.revision if base else 0
        if row.op == "delete":
            if base is None or base.deleted:
                return None
            return {"op": "delete", "collection": row.collection, "item_id": row.item_id, "if_match": if_match}
        content = dict(base.content) if base and base.content else {}
        content["values"] = self._local_values(row) or {}
        return {"op": "put", "collection": row.collection, "item_id": row.item_id, "if_match": if_match,
                "schema_version": SUPPORTED.get(row.collection, 1), "content": content, "blobs": []}

    async def _push_batch(self, rows: list[OutboxRow]) -> bool:
        operations, used = [], []
        for row in rows:
            op = self._operation(row)
            if op is None:
                self.store.drop_outbox(row.id)
                continue
            operations.append(op)
            used.append(row)
        if not operations:
            return True
        try:
            result = await self.client.batch(operations, used[0].idempotency_key)
        except SyncApiError as error:
            if error.status >= 500 or error.code in _FATAL:
                self._fatal_or_offline(error)
                raise _StopRound() from error
            return False  # a conflict or limit in one operation: fall back to one by one
        for row, item in zip(used, result.get("results") or []):
            self.store.save_item(self.org, item)
            self.store.drop_outbox(row.id)
        self.status.offline = False
        return True

    async def _push_row(self, row: OutboxRow, attempt: int = 0) -> str:
        op = self._operation(row)
        if op is None:
            self.store.drop_outbox(row.id)
            return "done"
        try:
            if op["op"] == "put":
                result = await self.client.put_item(row.collection, row.item_id, op["if_match"],
                                                    op["schema_version"], op["content"], row.idempotency_key)
            else:
                result = await self.client.delete_item(row.collection, row.item_id, op["if_match"],
                                                       row.idempotency_key)
        except SyncApiError as error:
            return await self._push_failed(row, error, attempt)
        self.store.save_item(self.org, result)
        self.store.drop_outbox(row.id)
        self.status.offline = False
        return "done"

    async def _push_failed(self, row: OutboxRow, error: SyncApiError, attempt: int) -> str:
        code = error.code
        if code == "revision_conflict":
            if attempt >= MAX_CONFLICT_ROUNDS:
                self.store.mark_attempt(row.id, code)
                return "skip_collection"
            current = error.details.get("current")
            fresh = self._merge_after_conflict(row, current)
            if fresh is None:
                return "done"
            return await self._push_row(fresh, attempt + 1)
        if error.status == 429:
            if attempt >= 1:
                raise _StopRound()
            await self.sleep(min(error.retry_after or 1.0, 60.0))
            return await self._push_row(row, attempt + 1)
        if code == "storage_quota_exceeded":
            self.status.storage_full = True
            return "skip_collection"
        if code in ("not_entitled", "collection_disabled"):
            self.status.paused[row.collection] = code
            return "skip_collection"
        if code == "forbidden":
            self.status.read_only = True
            raise _StopRound()
        if code in _FATAL or error.status == 401:
            self._fatal_or_offline(error)
            raise _StopRound()
        if error.status >= 500 or code.startswith("http_5"):
            self.status.offline = True
            raise _StopRound()
        self.store.mark_attempt(row.id, code)  # a bug-shaped refusal: keep the row, move on
        logger.warning("cloud sync refused %s/%s: %s", row.collection, row.item_id, code)
        return "done"

    def _merge_after_conflict(self, row: OutboxRow, current: Optional[dict]) -> Optional[OutboxRow]:
        base = self.store.item(self.org, row.collection, row.item_id)
        local = self._local_values(row)
        remote_values = _values(current)
        merged = merge_item(_values(base), local, remote_values)
        self._note_conflicts(row.collection, row.item_id, merged.conflicts)
        definition = allowlist.item(row.collection, row.item_id)
        if definition is not None:
            self._write(definition, merged.values)
        if current:
            self.store.save_item(self.org, current)
        else:
            self.store.forget_item(self.org, row.collection, row.item_id)
        if merged.values is None and (current is None or current.get("deleted")):
            self.store.drop_outbox(row.id)
            return None
        self.store.renew_key(row.id)
        fresh = self.store.queue(self.org, row.collection, row.item_id, "delete" if merged.values is None else "put")
        return fresh

    def _fatal_or_offline(self, error: SyncApiError) -> None:
        if error.code in _FATAL:
            self.status.stopped = error.code
        elif error.status == 401:
            pass  # the next round asks main for a fresh token
        elif error.code == "forbidden":
            self.status.read_only = True
        elif error.code in ("not_entitled", "collection_disabled"):
            pass
        else:
            self.status.offline = True
