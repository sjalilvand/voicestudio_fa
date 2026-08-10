"""Feature lifecycle, capability discovery, and the management API.

The property that matters most here is the one that is easiest to erode: with
the feature switched off, *nothing* runs. No socket, no certificate, no
background loop. The local-first guarantee is not "we're careful with the
network", it is that a user who never opts in has an app that is unchanged.
"""
from __future__ import annotations

import sqlite3

import pytest

from worker import capabilities, service


@pytest.fixture
def db(tmp_path, monkeypatch):
    from worker import registry as reg

    db_globals = reg.db_conn.__wrapped__.__globals__
    path = str(tmp_path / "userdata.db")
    with sqlite3.connect(path) as conn:
        conn.executescript(db_globals["_BASE_SCHEMA"])
    monkeypatch.setitem(db_globals, "DB_PATH", path)
    return path


# ── The opt-in gate ────────────────────────────────────────────────────────


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("OMNIVOICE_REMOTE_WORKERS", raising=False)
    monkeypatch.setattr(
        service, "remote_workers_enabled", service.remote_workers_enabled
    )
    # No settings row and no env var: the feature is off.
    monkeypatch.setattr("services.settings_store.get_text", lambda *a, **k: None)
    assert service.remote_workers_enabled() is False


@pytest.mark.parametrize("value,expected", [("1", True), ("true", True), ("on", True),
                                            ("0", False), ("false", False), ("", False)])
def test_env_var_controls_the_gate(monkeypatch, value, expected):
    monkeypatch.setenv("OMNIVOICE_REMOTE_WORKERS", value)
    monkeypatch.setattr("services.settings_store.get_text", lambda *a, **k: None)
    assert service.remote_workers_enabled() is expected


def test_env_var_beats_the_stored_setting(monkeypatch):
    """A headless deployment must be able to force the answer."""
    monkeypatch.setenv("OMNIVOICE_REMOTE_WORKERS", "0")
    monkeypatch.setattr("services.settings_store.get_text", lambda *a, **k: "true")
    assert service.remote_workers_enabled() is False


def test_a_broken_settings_store_does_not_enable_the_feature(monkeypatch):
    """Failing closed matters here: failing open would start a listening
    socket for a user who never asked for one."""
    monkeypatch.delenv("OMNIVOICE_REMOTE_WORKERS", raising=False)

    def _boom(*a, **k):
        raise RuntimeError("db is gone")

    monkeypatch.setattr("services.settings_store.get_text", _boom)
    assert service.remote_workers_enabled() is False


@pytest.mark.asyncio
async def test_start_if_enabled_is_a_no_op_when_disabled(monkeypatch):
    monkeypatch.setattr(service, "remote_workers_enabled", lambda: False)
    started = []
    monkeypatch.setattr(
        service.control_plane, "start", lambda **k: started.append(True)
    )

    await service.start_if_enabled()

    assert started == []
    assert service.control_plane.running is False


@pytest.mark.asyncio
async def test_a_failing_start_never_takes_the_app_down(monkeypatch):
    """The user's local workflow does not depend on this feature existing."""
    monkeypatch.setattr(service, "remote_workers_enabled", lambda: True)

    async def _boom(**kwargs):
        raise OSError("port already in use")

    monkeypatch.setattr(service.control_plane, "start", _boom)
    await service.start_if_enabled()  # must not raise


def test_paths_live_under_the_user_data_directory():
    locations = service.paths()
    assert locations["certificate"].startswith(locations["root"])
    assert locations["private_key"].startswith(locations["root"])
    assert locations["artifacts"].startswith(locations["root"])


def test_snapshot_is_inert_when_stopped():
    plane = service.ControlPlane()
    snapshot = plane.snapshot()
    assert snapshot == {"enabled": False, "running": False, "workers": [], "queue_depth": 0}


def test_port_falls_back_when_the_env_var_is_garbage(monkeypatch):
    monkeypatch.setenv("OMNIVOICE_WORKER_PORT", "not-a-port")
    assert service.control_port() == service.DEFAULT_PORT


# ── Capability discovery ───────────────────────────────────────────────────


def test_discovery_survives_a_broken_engine_layer(monkeypatch):
    """One engine that cannot introspect must not hide the others — the same
    guarantee list_backends() already makes locally."""
    monkeypatch.setattr(
        "services.tts_backend.list_backends", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    assert capabilities.discover() == []


def test_discovery_reports_the_four_states(monkeypatch):
    monkeypatch.setattr(
        "services.tts_backend.list_backends",
        lambda: [
            {
                "id": "indextts",
                "display_name": "IndexTTS-2",
                "available": True,
                "supports_cloning": True,
                "routing_status": "accelerated",
                "gpu_compat": ["cuda"],
                "effective_device": "cuda",
                "min_vram_gb": 6.0,
            }
        ],
    )
    found = capabilities.discover()

    assert len(found) == 1
    entry = found[0]
    for field in ("supported", "installed", "downloaded", "resident"):
        assert field in entry, f"{field} must be reported separately"
    assert entry["min_memory_bytes"] == int(6 * 1024**3)
    assert "clone" in entry["operations"]


def test_cpu_fallback_is_reported_because_capability_is_not_acceleration(monkeypatch):
    monkeypatch.setattr(
        "services.tts_backend.list_backends",
        lambda: [
            {
                "id": "slow",
                "available": True,
                "routing_status": "cpu_fallback",
                "gpu_compat": ["cpu"],
                "effective_device": "cpu",
            }
        ],
    )
    assert capabilities.discover()[0]["cpu_fallback"] is True


def test_unavailable_engines_are_omitted_by_default(monkeypatch):
    monkeypatch.setattr(
        "services.tts_backend.list_backends",
        lambda: [{"id": "broken", "available": False, "gpu_compat": []}],
    )
    assert capabilities.discover() == []
    assert len(capabilities.discover(include_unavailable=True)) == 1


def test_engines_that_cannot_clone_do_not_advertise_it(monkeypatch):
    """`supports_cloning` is None when it depends on the loaded model; treating
    that as "yes" produces a task that fails at the last moment."""
    monkeypatch.setattr(
        "services.tts_backend.list_backends",
        lambda: [{"id": "e", "available": True, "supports_cloning": None, "gpu_compat": ["cuda"]}],
    )
    assert capabilities.discover()[0]["operations"] == ["tts"]


def test_default_concurrency_is_one():
    """Matching the local GPU queue's deliberate single lane."""
    assert capabilities.max_concurrent_tasks([]) == 1
    assert capabilities.max_concurrent_tasks([{"derived_concurrency": 4}, {"derived_concurrency": 1}]) == 1


# ── Management API ─────────────────────────────────────────────────────────


def _app():
    from fastapi import FastAPI

    from api.routers import workers as workers_router

    app = FastAPI()
    app.include_router(workers_router.router)
    return app


@pytest.fixture
def client(db):
    """A client that satisfies the loopback gate.

    The gate is real and is exercised separately below; overriding it here
    keeps every other test about the endpoint's own behaviour.
    """
    from fastapi.testclient import TestClient

    from api.dependencies import require_loopback

    app = _app()
    app.dependency_overrides[require_loopback] = lambda: None
    return TestClient(app)


def test_management_endpoints_are_loopback_only(db):
    """These mint join tokens and revoke machines, so a non-loopback origin
    must be refused outright rather than merely discouraged."""
    from fastapi.testclient import TestClient

    unguarded = TestClient(_app())
    assert unguarded.get("/workers").status_code == 403
    assert unguarded.post("/workers/enrollments", json={}).status_code == 403
    assert unguarded.delete("/workers/anything").status_code == 403


def test_listing_workers_is_safe_when_the_feature_is_off(client):
    response = client.get("/workers")
    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_minting_a_token_requires_the_feature_to_be_running(client):
    response = client.post("/workers/enrollments", json={})
    assert response.status_code == 409
    assert "Settings" in response.json()["detail"]


def test_updating_an_unknown_worker_is_a_404(client):
    assert client.patch("/workers/nope", json={"name": "x"}).status_code == 404
    assert client.delete("/workers/nope").status_code == 404
    assert client.post("/workers/nope/consent").status_code == 404


def test_worker_updates_round_trip(client, db):
    from worker import registry
    from worker.identity import WorkerKeypair

    worker = registry.enroll_worker(name="box", public_key=WorkerKeypair.generate().public_bytes())

    response = client.patch(
        f"/workers/{worker.id}", json={"name": "Desktop", "priority": 90, "enabled": False}
    )

    assert response.status_code == 200
    reloaded = registry.get(worker.id)
    assert reloaded.name == "Desktop"
    assert reloaded.priority == 90
    assert reloaded.enabled is False


def test_priority_is_clamped_by_the_schema(client, db):
    from worker import registry
    from worker.identity import WorkerKeypair

    worker = registry.enroll_worker(name="box", public_key=WorkerKeypair.generate().public_bytes())
    assert client.patch(f"/workers/{worker.id}", json={"priority": 500}).status_code == 422


def test_removing_a_worker_revokes_its_key(client, db):
    """Remove must mean revoke, not hide: a hidden row would let the same key
    reconnect as though it were a stranger."""
    from worker import registry
    from worker.identity import WorkerKeypair

    keypair = WorkerKeypair.generate()
    worker = registry.enroll_worker(name="box", public_key=keypair.public_bytes())

    assert client.delete(f"/workers/{worker.id}").status_code == 200
    assert registry.is_revoked(keypair.key_id) is True


def test_consent_is_recorded_explicitly(client, db):
    from worker import registry
    from worker.identity import WorkerKeypair

    worker = registry.enroll_worker(
        name="box", public_key=WorkerKeypair.generate().public_bytes(), consent_granted=False
    )
    assert registry.get(worker.id).schedulable is False

    assert client.post(f"/workers/{worker.id}/consent").status_code == 200
    assert registry.get(worker.id).schedulable is True


def test_task_listing_is_empty_when_stopped(client):
    body = client.get("/workers/tasks").json()
    assert body == {"tasks": [], "queue_depth": 0}


@pytest.mark.asyncio
async def test_enrollment_advertises_the_port_actually_bound(db, monkeypatch, tmp_path):
    """A token carries the endpoint a worker will dial. Advertising the
    configured port while listening on another hands workers an address
    nothing answers on — found by running the thing on a non-default port.
    """
    monkeypatch.setattr(
        service,
        "paths",
        lambda: {
            "root": str(tmp_path),
            "certificate": str(tmp_path / "cp.crt"),
            "private_key": str(tmp_path / "cp.key"),
            "worker_key": str(tmp_path / "w.key"),
            "artifacts": str(tmp_path / "artifacts"),
        },
    )
    monkeypatch.delenv("OMNIVOICE_WORKER_PORT", raising=False)
    monkeypatch.delenv("OMNIVOICE_WORKER_ENDPOINT_HOST", raising=False)

    plane = service.ControlPlane()
    await plane.start(port=7601)
    try:
        assert plane.default_endpoint().endswith(":7601")
        assert plane.create_enrollment().endpoint.endswith(":7601")
    finally:
        await plane.stop()


def test_endpoint_falls_back_to_the_configured_port_when_stopped(monkeypatch):
    monkeypatch.delenv("OMNIVOICE_WORKER_PORT", raising=False)
    assert service.ControlPlane().default_endpoint().endswith(f":{service.DEFAULT_PORT}")
