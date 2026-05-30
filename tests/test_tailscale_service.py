# tests/test_tailscale_service.py
import json
from unittest.mock import patch, MagicMock
from services import tailscale as ts


def test_status_absent_cli_is_graceful():
    with patch("services.tailscale.shutil.which", return_value=None):
        s = ts.status()
    assert s["installed"] is False and s["running"] is False


def test_status_parses_json():
    payload = {"BackendState": "Running", "Self": {"DNSName": "box.tail1234.ts.net.", "TailscaleIPs": ["100.64.0.1"]}}
    with patch("services.tailscale.shutil.which", return_value="/usr/bin/tailscale"), \
         patch("services.tailscale.subprocess.run", return_value=MagicMock(returncode=0, stdout=json.dumps(payload))):
        s = ts.status()
    assert s["installed"] and s["running"]
    assert s["magic_dns_name"] == "box.tail1234.ts.net"
    assert s["tailnet_ips"] == ["100.64.0.1"]
