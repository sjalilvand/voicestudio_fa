"""Cloud sync routes: desktop-only, renderer mirror, and switch-off handling."""
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers import cloud_sync as router_module
from core import change_hooks
from core import db as core_db
from core import prefs
from services.cloud_sync.client import CloudOff
from services.cloud_sync.store import SyncStore


class StubService:
    def __init__(self):
        self.calls = []
        self.fail = None

    def _record(self, name, *args):
        self.calls.append((name, *args))
        if self.fail:
            raise self.fail
        return {"enabled": name == "turn_on"}

    def view(self):
        return {"enabled": False}

    async def refresh_server_view(self):
        self.calls.append(("refresh",))

    running = False

    async def turn_on(self, choices):
        return self._record("turn_on", choices)

    async def turn_off(self):
        return self._record("turn_off")

    async def set_choices(self, choices, remove):
        return self._record("set_choices", choices, remove)

    async def start(self):
        self.calls.append(("start",))
        return True

    async def stop(self):
        self.calls.append(("stop",))

    def trigger(self):
        self.calls.append(("trigger",))

    async def confirm_deletes(self):
        return self._record("confirm_deletes")

    async def devices(self):
        self._record("devices")
        return [{"id": "Dv1"}]

    async def revoke(self, device_id):
        return self._record("revoke", device_id)

    async def use_choices_of(self, device_id):
        return self._record("use_choices_of", device_id)


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "_PREFS_PATH", str(tmp_path / "prefs.json"))
    path = str(tmp_path / "omnivoice.db")
    monkeypatch.setattr(core_db, "DB_PATH", path)
    with sqlite3.connect(path) as conn:
        conn.executescript(core_db._BASE_SCHEMA)
    service = StubService()
    monkeypatch.setattr(router_module, "get_service", lambda: service)
    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[router_module.require_admin] = lambda: None
    return TestClient(app, client=("127.0.0.1", 5000)), service


def test_routes_are_refused_off_loopback(tmp_path, monkeypatch):
    monkeypatch.setattr(router_module, "get_service", lambda: StubService())
    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[router_module.require_admin] = lambda: None
    remote = TestClient(app, client=("192.168.1.20", 5000))
    assert remote.get("/api/cloud-sync/status").status_code == 403


def test_turn_on_passes_only_known_choices(api):
    client, service = api
    response = client.post("/api/cloud-sync/on", json={"choices": {"settings": True, "favorites": False}})
    assert response.status_code == 200
    assert service.calls == [("turn_on", {"settings": True, "favorites": False})]


def test_switched_off_answers_409_cloud_off(api):
    client, service = api
    service.fail = CloudOff()
    response = client.post("/api/cloud-sync/on", json={"choices": {}})
    assert response.status_code == 409 and response.json()["detail"] == "cloud_off"


def test_main_can_stop_and_start_the_engine(api):
    client, service = api
    assert client.post("/api/cloud-sync/stop").status_code == 200
    assert client.post("/api/cloud-sync/start").status_code == 200
    assert service.calls == [("stop",), ("start",)]


def test_device_ids_are_validated(api):
    client, service = api
    assert client.post("/api/cloud-sync/devices/not-valid!/revoke").status_code == 422
    assert client.post("/api/cloud-sync/devices/Dv7kQ2mZx9LpR4sT/revoke").status_code == 200


def test_renderer_mirror_round_trip_and_announces_the_change(api):
    client, _ = api
    seen = []
    unhook = change_hooks.subscribe(lambda source, key: seen.append((source, key)))
    try:
        keys = client.get("/api/cloud-sync/local/keys").json()["keys"]
        assert "voicestudio.theme.v2" in keys
        put = client.put("/api/cloud-sync/local", json={"key": "voicestudio.theme.v2", "value": "dark", "raw": True})
        assert put.status_code == 200
    finally:
        unhook()
    assert seen == [("local", "voicestudio.theme.v2")]
    assert SyncStore().get_local("voicestudio.theme.v2") == "dark"
    seq = SyncStore().local_seq()
    SyncStore().set_local("voicestudio.theme.v2", "light", origin="sync")
    pulled = client.get(f"/api/cloud-sync/local?since={seq}").json()
    assert pulled["values"] == [{"key": "voicestudio.theme.v2", "value": "light", "raw": True}]
    assert pulled["seq"] == seq + 1


def test_the_mirror_refuses_keys_that_never_sync(api):
    client, _ = api
    response = client.put("/api/cloud-sync/local", json={"key": "voicestudio.workspace-layout", "value": 1, "raw": False})
    assert response.status_code == 400
