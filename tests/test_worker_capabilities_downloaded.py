from worker import capabilities


def test_downloaded_uses_shared_cache_helpers(monkeypatch):
    monkeypatch.setattr(capabilities, "repo_ids_for", lambda _entry: ["org/model"])
    monkeypatch.setattr(capabilities, "_resident_engine_ids", lambda: set())
    monkeypatch.setattr("core.device_caps.detect_host_caps", lambda: None)
    monkeypatch.setattr("services.tts_backend.list_backends", lambda: [{
        "id": "omnivoice", "available": True, "routing_status": "accelerated"
    }])
    monkeypatch.setattr("api.routers.setup.models.is_cached", lambda _repo: False)

    row = capabilities.discover(include_unavailable=True)[0]

    assert row["downloaded"] is False
    assert row["repo_ids"] == ["org/model"]


def test_download_probe_fails_open_when_cache_is_inconclusive(monkeypatch):
    monkeypatch.setattr("api.routers.setup.models.is_cached", lambda _repo: (_ for _ in ()).throw(OSError()))
    assert capabilities._downloaded(["user/managed-model"]) is True


def test_unavailable_engine_is_reported_when_requested(monkeypatch):
    monkeypatch.setattr(capabilities, "repo_ids_for", lambda _entry: [])
    monkeypatch.setattr(capabilities, "_resident_engine_ids", lambda: set())
    monkeypatch.setattr("core.device_caps.detect_host_caps", lambda: None)
    monkeypatch.setattr("services.tts_backend.list_backends", lambda: [{
        "id": "indextts2", "available": False, "routing_status": "accelerated"
    }])
    assert capabilities.discover() == []
    assert capabilities.discover(include_unavailable=True)[0]["engine"] == "indextts2"
