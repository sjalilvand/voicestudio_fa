"""Short-lived VoiceStudio Cloud access tokens from Electron main.

The refresh token never leaves Electron main. Main answers {"signed_in": false}
whenever account features or sync are switched off, or the backend is remote,
so "no token" here means "make no Cloud call". The capability is removed from
os.environ at import so engine and tool subprocesses never inherit it.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from typing import Optional
from urllib.parse import urlsplit

_lock = threading.Lock()
_url = os.environ.pop("VOICESTUDIO_ACCOUNT_BRIDGE_URL", "")
_capability = os.environ.pop("VOICESTUDIO_ACCOUNT_BRIDGE_TOKEN", "")
_cached: Optional[tuple[str, float]] = None


def _configure(url: str, capability: str) -> None:
    """Test seam."""
    global _url, _capability, _cached
    with _lock:
        _url, _capability, _cached = url, capability, None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def access_token() -> Optional[str]:
    global _cached
    with _lock:
        if _cached and _cached[1] - time.time() * 1000 > 30_000:
            return _cached[0]
        target = urlsplit(_url)
        if target.scheme != "http" or target.hostname != "127.0.0.1" or not _capability:
            return None
        request = urllib.request.Request(
            _url + "/token", headers={"Authorization": "Bearer " + _capability}
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        try:
            with opener.open(request, timeout=10) as response:
                body = json.loads(response.read(65_536))
        except (OSError, ValueError):
            return None
        if not body.get("signed_in") or not isinstance(body.get("access_token"), str):
            _cached = None
            return None
        _cached = (body["access_token"], float(body.get("expires_at", 0)))
        return _cached[0]


def invalidate() -> None:
    global _cached
    with _lock:
        _cached = None
