import socket
from unittest.mock import patch
from services import network_share as ns


def _addr(ip):
    class A:  # mimic psutil snicaddr
        family = socket.AF_INET
        address = ip
    return A()


def test_lan_ipv4_filters_loopback_and_linklocal():
    fake = {
        "lo0": [_addr("127.0.0.1")],
        "en0": [_addr("192.168.1.42")],
        "en1": [_addr("169.254.5.5"), _addr("10.0.0.9")],
    }
    with patch("services.network_share.psutil.net_if_addrs", return_value=fake):
        out = ns.lan_ipv4_addresses()
    assert out == ["192.168.1.42", "10.0.0.9"]


def test_gen_pin_is_six_digits():
    pin = ns._gen_pin()
    assert pin.isdigit() and len(pin) == 6


from fastapi.testclient import TestClient


def _loopback_client():
    from main import app
    return TestClient(app, client=("127.0.0.1", 50000))


def test_network_state_endpoint_defaults_disabled():
    c = _loopback_client()
    r = c.get("/system/network/state")
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_network_control_rejects_non_loopback():
    from main import app
    c = TestClient(app, client=("10.0.0.5", 9999))
    assert c.post("/system/network/enable").status_code == 403


def test_system_info_has_sharing_fields():
    c = _loopback_client()
    body = c.get("/system/info").json()
    for k in ("share_enabled", "share_port", "lan_addresses", "pin_required"):
        assert k in body
