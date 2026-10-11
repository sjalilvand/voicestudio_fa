"""The OSS identity and active default ports have one editable manifest."""

from __future__ import annotations

import json
import re
from pathlib import Path

from core.app_config import (
    APP_ID,
    DEFAULT_BACKEND_PORT,
    DEFAULT_ELECTRON_DEV_PORT,
    DEFAULT_WEB_PORT,
    PRODUCT_NAME,
)


ROOT = Path(__file__).parents[1]


def test_python_runtime_reads_the_central_app_config() -> None:
    config = json.loads((ROOT / "config/app.json").read_text(encoding="utf-8"))
    assert PRODUCT_NAME == config["productName"]
    assert APP_ID == config["appId"]
    assert (
        DEFAULT_BACKEND_PORT,
        DEFAULT_WEB_PORT,
        DEFAULT_ELECTRON_DEV_PORT,
    ) == (
        config["ports"]["backend"],
        config["ports"]["web"],
        config["ports"]["electronDev"],
    )


def test_active_launchers_do_not_mirror_default_port_literals() -> None:
    active_files = (
        "electron/electron.vite.config.ts",
        "electron/vite.web.config.ts",
        "electron/src/main/backend.ts",
        "electron/src/main/dev-backend-proxy.ts",
        "electron/src/shared/utils/apiBase.ts",
        "scripts/dev-backend.mjs",
        "scripts/clear-dev-ports.mjs",
    )
    for relative in active_files:
        source = (ROOT / relative).read_text(encoding="utf-8")
        source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
        source = re.sub(r"//.*", "", source)
        for port in (3900, 3901, 3902, 3903):
            assert str(port) not in source, f"{relative} mirrors port {port}"
