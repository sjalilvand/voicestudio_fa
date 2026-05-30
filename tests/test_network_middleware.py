# tests/test_network_middleware.py
from fastapi.testclient import TestClient
from services import network_share as ns


def _app_with_pin(pin="123456"):
    from main import app
    app.state.network_share = ns.ShareState(enabled=True, share_port=3901, pin=pin, lan_addresses=["10.0.0.9"])
    return app


def teardown_function():
    from main import app
    app.state.network_share = ns.ShareState()  # reset → middleware inert


def test_inert_when_no_pin():
    from main import app
    app.state.network_share = ns.ShareState()  # no pin
    c = TestClient(app, client=("10.0.0.5", 1))   # non-loopback
    assert c.get("/health").status_code == 200


def test_loopback_bypasses_pin():
    c = TestClient(_app_with_pin(), client=("127.0.0.1", 1))
    assert c.get("/system/info").status_code == 200  # loopback → ok


def test_non_loopback_without_pin_401_on_api():
    c = TestClient(_app_with_pin(), client=("10.0.0.5", 1))
    r = c.get("/api/voices")  # any non-shell API path
    assert r.status_code in (401,)  # PIN required


def test_non_loopback_with_valid_pin_passes():
    c = TestClient(_app_with_pin("654321"), client=("10.0.0.5", 1))
    r = c.get("/api/voices", headers={"X-OmniVoice-Pin": "654321"})
    assert r.status_code != 401


def test_spa_shell_served_without_pin():
    c = TestClient(_app_with_pin(), client=("10.0.0.5", 1))
    assert c.get("/health").status_code == 200
