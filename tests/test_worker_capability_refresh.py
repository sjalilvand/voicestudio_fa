import json

import pytest

from worker.identity import WorkerKeypair
from worker.protocol.gen import worker_v1_pb2 as pb
from worker.transport.client import WorkerClient, WorkerConfig
from worker.transport.server import WorkerServicer


def _client(probe):
    return WorkerClient(
        WorkerConfig(endpoint="unused", cert_fingerprint="", certificate_pem=b"",
                     keypair=WorkerKeypair.generate()),
        execute=lambda _assignment: None,
        capability_probe=probe,
    )


@pytest.mark.asyncio
async def test_refresh_sends_capability_update():
    client = _client(lambda: [{
        "engine": "omnivoice", "model_id": "omnivoice:default",
        "operations": ["tts"], "supported": True, "installed": True,
        "downloaded": True, "repo_ids": ["k2-fsa/OmniVoice"],
    }])
    await client.refresh_capabilities()
    frame = await client._outbox.get()
    assert frame.WhichOneof("payload") == "capabilities"
    assert frame.capabilities.capabilities[0].downloaded is True


@pytest.mark.asyncio
async def test_prewarm_resolves_catalog_repo_and_refreshes(monkeypatch):
    loaded = []
    client = _client(lambda: [{
        "engine": "omnivoice", "model_id": "omnivoice:default",
        "operations": ["tts"], "supported": True, "installed": True,
        "downloaded": True, "repo_ids": ["k2-fsa/OmniVoice"],
    }])
    client.config.capabilities = client._capability_probe()
    monkeypatch.setattr(
        "worker.executor.TaskExecutor._load_backend", lambda engine: loaded.append(engine)
    )
    await client._on_prewarm(pb.PrewarmRequest(
        model_id="omnivoice:default", download_if_missing=False,
    ))
    assert loaded == ["omnivoice"]
    assert (await client._outbox.get()).WhichOneof("payload") == "capabilities"


@pytest.mark.asyncio
async def test_remote_download_reuses_installer_and_pipes_fake_progress(monkeypatch):
    """Offline producer: no Hub access, while exercising the real listener path."""
    from api.routers.setup import download as setup_download
    from utils import hf_progress

    calls = []

    async def fake_install(req):
        calls.append((req.repo_id, req.target))
        hf_progress.emit({
            "repo_id": req.repo_id, "phase": "aggregate",
            "bytes_done": 5, "total_bytes": 10,
        })
        hf_progress.emit({"repo_id": req.repo_id, "phase": "install_done"})
        return {"status": "install_started"}

    monkeypatch.setattr(setup_download, "install_model", fake_install)
    monkeypatch.setattr(
        "worker.executor.TaskExecutor._load_backend", lambda _engine: None
    )
    client = _client(lambda: [{
        "engine": "omnivoice", "model_id": "omnivoice:default",
        "operations": ["tts"], "supported": True, "installed": True,
        "downloaded": False, "repo_ids": ["k2-fsa/OmniVoice"],
    }])
    client.config.capabilities = client._capability_probe()

    await client._on_prewarm(pb.PrewarmRequest(
        model_id="omnivoice:default", download_if_missing=True,
    ))

    assert calls == [("k2-fsa/OmniVoice", "local")]
    first = await client._outbox.get()
    second = await client._outbox.get()
    assert first.WhichOneof("payload") == "download_progress"
    assert '"phase":"aggregate"' in first.download_progress.event_json
    assert second.WhichOneof("payload") == "download_progress"


@pytest.mark.asyncio
async def test_control_plane_stamps_authenticated_target_on_progress():
    from utils import hf_progress

    events = []
    listener_id = hf_progress.register_listener(events.append)
    try:
        session = type("Session", (), {"worker_id": "gpu2"})()
        await WorkerServicer._handle(
            object.__new__(WorkerServicer),
            session,
            pb.WorkerMessage(download_progress=pb.DownloadProgress(
                event_json=json.dumps({
                    "repo_id": "k2-fsa/OmniVoice", "target": "forged",
                    "phase": "aggregate", "bytes_done": 5, "total_bytes": 10,
                })
            )),
        )
    finally:
        hf_progress.unregister_listener(listener_id)
    assert events[-1]["target"] == "gpu2"
