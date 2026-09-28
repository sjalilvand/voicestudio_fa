"""All skills use the same transport; no paid credentials or model downloads."""
import json
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def registry(monkeypatch, clean_llm_env):
    from services import llm_providers, settings_store
    values = {}
    monkeypatch.setattr(settings_store, "get_text", lambda key, default=None: values.get(key, default))
    monkeypatch.setattr(settings_store, "set_text", lambda key, value: values.__setitem__(key, value))
    monkeypatch.setattr(settings_store, "get_secret", lambda key: values.get(key))
    monkeypatch.setattr(settings_store, "set_secret", lambda key, value: values.__setitem__(key, value))
    monkeypatch.setattr(settings_store, "list_secret_names", lambda: [k for k in values if k.startswith("llm_key.")])
    return llm_providers


def test_cli_never_auto_activates_or_needs_an_api_key(registry, monkeypatch):
    monkeypatch.setenv("VOICESTUDIO_LLM_AGENTS", '["codex"]')
    assert registry.is_configured(registry.get_provider("codex-cli"))
    assert not registry.is_configured(registry.get_provider("pi-cli"))
    assert registry.active_provider_id() is None
    assert registry.describe(registry.get_provider("codex-cli"))["supports_model_listing"] is False


@pytest.mark.parametrize("provider,model,expected", [
    ("anthropic", "claude-test", "anthropic/claude-test"),
    ("sdk", "deepseek/chat-test", "deepseek/chat-test"),
    ("bedrock", "us.anthropic.test", "bedrock/us.anthropic.test"),
    ("vertex", "gemini-test", "vertex_ai/gemini-test"),
])
def test_sdk_passes_messages_and_credentials_per_request(registry, monkeypatch, provider, model, expected):
    from services.llm_transport import create_client
    calls = []
    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=lambda **kw: calls.append(kw) or "response"))
    registry.save_key(provider, "test-secret")
    registry.save_overrides(provider, model=model, account_id="project-test")
    messages = [{"role": "system", "content": "Translate"}, {"role": "user", "content": "Hello"}]
    response = create_client(registry.get_provider(provider)).chat.completions.create(
        model=model, messages=messages, timeout=12, stream=True)
    assert response == "response"
    assert calls[0]["model"] == expected
    assert calls[0]["messages"] == messages
    assert calls[0]["num_retries"] == 0
    assert calls[0]["stream"] is True
    key_field = "aws_bearer_token_bedrock" if provider == "bedrock" else "api_key"
    assert calls[0][key_field] == "test-secret"
    if provider == "vertex":
        assert calls[0]["vertex_project"] == "project-test"


def test_native_anthropic_sdk_http_round_trip(registry, monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from services.llm_backend import OpenAICompatBackend
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            requests.append((self.path, self.headers.get("x-api-key"), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            body = json.dumps({"id": "msg_test", "type": "message", "role": "assistant", "model": "claude-sonnet-4-6",
                "content": [{"type": "text", "text": "Bonjour"}], "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 2}}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        registry.save_key("anthropic", "fixture-key")
        registry.save_overrides("anthropic", base_url=f"http://127.0.0.1:{server.server_port}")
        backend = OpenAICompatBackend(provider=registry.get_provider("anthropic"))
        assert backend.chat(system="Translate into French", user="Hello", timeout=5) == "Bonjour"
        assert requests[0][0].endswith("/messages")
        assert requests[0][1] == "fixture-key"
        assert requests[0][2]["messages"][-1]["content"] == [{"type": "text", "text": "Hello"}]
        from api.routers.settings import test_llm_provider
        assert test_llm_provider("anthropic")["ok"] is True
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_cli_refuses_non_loopback_bridge(registry, monkeypatch):
    from services.llm_cli import completion
    monkeypatch.setenv("VOICESTUDIO_LLM_AGENT_URL", "https://example.com")
    monkeypatch.setenv("VOICESTUDIO_LLM_AGENT_TOKEN", "private")
    with pytest.raises(RuntimeError, match="Electron"):
        completion(registry.get_provider("codex-cli"), model="", messages=[])


@pytest.mark.parametrize("provider", ["vertex", "bedrock"])
def test_native_cloud_overrides_validate_urls_without_fake_keys(registry, monkeypatch, provider):
    monkeypatch.setenv("AWS_PROFILE", "fixture")
    registry.save_overrides(provider, model="test-model", base_url="file:///credentials", account_id="project")
    assert registry.resolve_api_key(registry.get_provider(provider)) is None
    assert "HTTP(S)" in registry.configuration_error(registry.get_provider(provider))


def test_generic_sdk_accepts_provider_environment_credentials(registry, monkeypatch):
    registry.save_overrides("sdk", model="openai/gpt-test")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture")
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    assert registry.configuration_error(registry.get_provider("sdk")) is None
