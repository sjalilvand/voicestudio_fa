"""Launch the Docker backend while preserving user-supplied Uvicorn options."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

from services.network_share import backend_port


def _has_option(arguments: Sequence[str], option: str) -> bool:
    """Return whether an option is present in split or ``--name=value`` form."""
    return any(argument == option or argument.startswith(f"{option}=") for argument in arguments)


def uvicorn_arguments(arguments: Sequence[str]) -> list[str]:
    """Build Uvicorn arguments without overriding explicit container options."""
    supplied = list(arguments)
    resolved = ["-m", "uvicorn", "backend.main:app"]
    if not _has_option(supplied, "--host"):
        resolved.extend(["--host", os.environ.get("OMNIVOICE_BIND_HOST", "0.0.0.0")])
    if not _has_option(supplied, "--port"):
        resolved.extend(["--port", str(backend_port())])
    return [*resolved, *supplied]


def main() -> None:
    """Replace this process with Uvicorn so container signals reach the server."""
    os.execv(sys.executable, [sys.executable, *uvicorn_arguments(sys.argv[1:])])


if __name__ == "__main__":
    main()
