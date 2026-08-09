"""Keep resolved dependencies above reviewed security-fix floors."""

from pathlib import Path
import tomllib

from packaging.version import Version


PYTHON_FLOORS = {
    "gradio": "6.15.1",
    "mako": "1.3.12",
    "mcp": "1.28.1",
    "msgpack": "1.2.1",
    "pillow": "12.3.0",
    "pydantic-settings": "2.14.2",
    "pygments": "2.20.0",
    "python-multipart": "0.0.31",
    "starlette": "1.3.1",
    "transformers": "5.5.0",
    "yt-dlp": "2026.7.4",
}


def test_python_security_floors_are_locked():
    lock = tomllib.loads(Path("uv.lock").read_text(encoding="utf-8"))
    resolved = {
        package["name"].lower(): Version(package["version"])
        for package in lock["package"]
        if package["name"].lower() in PYTHON_FLOORS
    }
    assert resolved.keys() == PYTHON_FLOORS.keys()
    assert {
        name: str(version)
        for name, version in resolved.items()
        if version < Version(PYTHON_FLOORS[name])
    } == {}


def test_quinn_security_floor_is_locked():
    lock = tomllib.loads(
        Path("frontend/src-tauri/Cargo.lock").read_text(encoding="utf-8")
    )
    quinn_proto = next(
        package for package in lock["package"] if package["name"] == "quinn-proto"
    )
    assert Version(quinn_proto["version"]) >= Version("0.11.15")
