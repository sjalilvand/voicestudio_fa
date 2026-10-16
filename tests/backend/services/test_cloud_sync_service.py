"""Sync service lifecycle: off means nothing runs, stop is immediate, turning on pulls first."""
import asyncio
import sqlite3

import pytest

from core import db as core_db
from core import prefs
from services.cloud_sync.service import CloudSyncService
from services.cloud_sync.store import SyncStore

from .cloud_sync_fake import FakeSyncServer

ORG = "Or5tG7hJ9kL1zX3c"
INFO = {"access_token": "acc", "organization_id": ORG, "sync_api": "https://appapi.voicestudio.sh/v1/sync"}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "_PREFS_PATH", str(tmp_path / "prefs.json"))
    path = str(tmp_path / "omnivoice.db")
    monkeypatch.setattr(core_db, "DB_PATH", path)
    with sqlite3.connect(path) as conn:
        conn.executescript(core_db._BASE_SCHEMA)
    server = FakeSyncServer()
    session = {"value": dict(INFO)}
    made = []

    def factory(info):
        made.append(info)
        return server

    service = CloudSyncService(session=lambda: session["value"], client_factory=factory, stream=False)
    return service, server, session, made


async def until(condition, timeout=2.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition never became true")
        await asyncio.sleep(0.01)


def test_signed_out_or_switched_off_starts_nothing(setup):
    service, server, session, made = setup
    session["value"] = None

    async def body():
        assert await service.start() is False

    asyncio.run(body())
    assert made == [] and server.calls == []


def test_sync_not_turned_on_here_starts_nothing(setup):
    service, server, _, _ = setup

    async def body():
        assert await service.start() is False

    asyncio.run(body())
    assert server.calls == []


def test_turning_on_registers_the_device_and_syncs_with_a_pull_first(setup):
    service, server, _, _ = setup
    prefs.set_("generation_history_cap", 30)

    async def body():
        view = await service.turn_on({"settings": True, "shortcuts": False, "favorites": False})
        await until(lambda: server.values("settings", "history") is not None)
        await service.stop()
        return view

    view = asyncio.run(body())
    names = [c[0] for c in server.calls]
    assert names[0] == "register_device"
    assert names.index("changes") < names.index("put")
    assert view["enabled"] is True and view["choices"] == {"settings": True, "shortcuts": False, "favorites": False}
    device_id = SyncStore().state(ORG).device_id
    assert server.values("device-preferences", device_id)["choices"]["settings"] is True


def test_stop_is_immediate_and_later_changes_are_not_queued(setup):
    service, server, _, _ = setup

    async def body():
        await service.turn_on({"settings": True})
        await until(lambda: any(c[0] == "put" for c in server.calls))
        await service.stop()
        assert not service.running
        calls = len(server.calls)
        prefs.set_("generation_history_cap", 99)
        await asyncio.sleep(0.05)
        return calls

    calls = asyncio.run(body())
    assert len(server.calls) == calls
    assert SyncStore().outbox(ORG) == []


def test_turning_off_keeps_the_device_and_turning_back_on_reuses_it(setup):
    service, server, _, _ = setup

    async def body():
        await service.turn_on({"settings": True})
        first = SyncStore().state(ORG).device_id
        view = await service.turn_off()
        assert view["enabled"] is False and SyncStore().state(ORG).device_id == first
        await service.turn_on({"settings": True})
        await service.stop()
        return first

    first = asyncio.run(body())
    assert [c[0] for c in server.calls].count("register_device") == 1
    assert SyncStore().state(ORG).device_id == first


def test_also_remove_from_the_cloud_deletes_that_collection_after_switching_it_off(setup):
    service, server, _, _ = setup
    server.put_remote("favorites", "gallery", {"arch-a": {"added_at": "2026-10-16T09:00:00Z"}})

    async def body():
        await service.turn_on({"settings": True, "favorites": True})
        await until(lambda: SyncStore().item(ORG, "favorites", "gallery") is not None)
        await service.set_choices({"settings": True, "favorites": False}, ["favorites"])
        await until(lambda: server.items[("favorites", "gallery")]["deleted"])
        await service.stop()

    asyncio.run(body())
    assert server.items[("favorites", "gallery")]["deleted"] is True


def test_setting_up_again_after_removal_registers_a_new_device(setup):
    service, server, _, _ = setup

    async def body():
        await service.turn_on({"settings": True})
        first = SyncStore().state(ORG).device_id
        await service.turn_on({"settings": True}, new_device=True)
        await service.stop()
        return first

    first = asyncio.run(body())
    assert [c[0] for c in server.calls].count("register_device") == 2
    assert SyncStore().state(ORG).device_id != first


def test_turning_sync_on_gives_every_voice_a_sync_id(setup):
    service, _, _, _ = setup
    with sqlite3.connect(core_db.DB_PATH) as conn:
        conn.execute("INSERT INTO voice_profiles (id, name, created_at) VALUES ('ab12cd34', 'Mine', 1)")

    async def body():
        await service.turn_on({"settings": True})
        await service.stop()

    asyncio.run(body())
    with sqlite3.connect(core_db.DB_PATH) as conn:
        sync_id = conn.execute("SELECT sync_id FROM voice_profiles WHERE id='ab12cd34'").fetchone()[0]
    assert sync_id and len(sync_id) == 16
