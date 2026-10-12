"""Launch the Docker backend while preserving user-supplied Uvicorn options."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from http.client import HTTPConnection
from pathlib import Path

from services.network_share import backend_port

_PID_ONE_ENVIRON = Path("/proc/1/environ")
_DEFAULT_DOCKER_HOST = "0.0.0.0"  # nosec B104: containers must accept published traffic.


def _has_option(arguments: Sequence[str], option: str) -> bool:
    """Return whether an option is present in split or ``--name=value`` form."""
    return any(argument == option or argument.startswith(f"{option}=") for argument in arguments)


def effective_port(arguments: Sequence[str]) -> int:
    """Resolve an explicit Uvicorn port before falling back to app configuration."""
    for index, argument in enumerate(arguments):
        if argument.startswith("--port="):
            return int(argument.partition("=")[2])
        if argument == "--port" and index + 1 < len(arguments):
            return int(arguments[index + 1])
    return backend_port()


def uvicorn_arguments(arguments: Sequence[str], port: int | None = None) -> list[str]:
    """Build Uvicorn arguments without overriding explicit container options."""
    supplied = list(arguments)
    resolved = ["-m", "uvicorn", "backend.main:app"]
    if not _has_option(supplied, "--host"):
        resolved.extend(["--host", os.environ.get("OMNIVOICE_BIND_HOST", _DEFAULT_DOCKER_HOST)])
    if not _has_option(supplied, "--port"):
        resolved.extend(["--port", str(port if port is not None else effective_port(supplied))])
    return [*resolved, *supplied]


def serving_port(environ_file: Path = _PID_ONE_ENVIRON) -> int:
    """Read the effective port inherited by the container's serving process."""
    try:
        entries = environ_file.read_bytes().split(b"\0")
        raw = next(
            entry.partition(b"=")[2]
            for entry in entries
            if entry.startswith(b"OMNIVOICE_PORT=")
        )
        return int(raw)
    except (OSError, StopIteration, ValueError):
        return backend_port()


def healthcheck(environ_file: Path = _PID_ONE_ENVIRON) -> None:
    """Probe the exact loopback port used by the serving container process."""
    connection = HTTPConnection("127.0.0.1", serving_port(environ_file), timeout=4)
    try:
        connection.request("GET", "/health")
        response = connection.getresponse()
        if response.status >= 400:
            raise RuntimeError(f"backend health check returned HTTP {response.status}")
    finally:
        connection.close()


def main() -> None:
    """Replace this process with Uvicorn so container signals reach the server."""
    supplied = sys.argv[1:]
    if supplied == ["--health-check"]:
        healthcheck()
        return
    port = effective_port(supplied)
    os.environ["OMNIVOICE_PORT"] = str(port)
    os.execv(sys.executable, [sys.executable, *uvicorn_arguments(supplied, port)])


if __name__ == "__main__":
    main()
