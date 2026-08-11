import pytest

from worker.identity import WorkerKeypair
from worker.protocol.gen import worker_v1_pb2 as pb
from worker.transport.client import WorkerClient, WorkerConfig


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
        model_id="k2-fsa/OmniVoice", download_if_missing=True,
    ))
    assert loaded == ["omnivoice"]
    assert (await client._outbox.get()).WhichOneof("payload") == "capabilities"
