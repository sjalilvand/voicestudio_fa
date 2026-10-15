"""The backend's view of the Electron account bridge (account sign-in S0-10)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from services import cloud_account


@pytest.fixture
def bridge():
    calls = []
    answer = {"body": {"signed_in": True, "access_token": "acc", "expires_at": 4_102_444_800_000}}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            calls.append(self.headers.get("Authorization"))
            payload = json.dumps(answer["body"]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    cloud_account._configure(f"http://127.0.0.1:{server.server_port}", "cap")
    yield calls, answer
    server.shutdown()
    cloud_account._configure("", "")


def test_bridge_env_is_removed_from_os_environ(monkeypatch):
    import importlib
    import os

    monkeypatch.setenv("VOICESTUDIO_ACCOUNT_BRIDGE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("VOICESTUDIO_ACCOUNT_BRIDGE_TOKEN", "cap")
    importlib.reload(cloud_account)
    assert "VOICESTUDIO_ACCOUNT_BRIDGE_TOKEN" not in os.environ
    assert "VOICESTUDIO_ACCOUNT_BRIDGE_URL" not in os.environ
    cloud_account._configure("", "")


def test_returns_and_caches_the_token(bridge):
    calls, _ = bridge
    assert cloud_account.access_token() == "acc"
    assert cloud_account.access_token() == "acc"
    assert calls == ["Bearer cap"]


def test_invalidate_forces_a_new_ask(bridge):
    calls, _ = bridge
    cloud_account.access_token()
    cloud_account.invalidate()
    cloud_account.access_token()
    assert len(calls) == 2


def test_signed_out_or_switched_off_is_none(bridge):
    _, answer = bridge
    answer["body"] = {"signed_in": False}
    assert cloud_account.access_token() is None


def test_without_electron_there_is_no_token():
    cloud_account._configure("", "")
    assert cloud_account.access_token() is None


def test_refuses_a_non_loopback_bridge():
    cloud_account._configure("http://example.com:80", "cap")
    assert cloud_account.access_token() is None
    cloud_account._configure("", "")
