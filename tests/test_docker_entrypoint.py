"""Docker startup preserves its stable defaults and explicit Uvicorn options."""

from docker_entrypoint import uvicorn_arguments


def test_docker_entrypoint_uses_the_resolved_backend_port(monkeypatch) -> None:
    """The default launch and backend health resolver share OMNIVOICE_PORT."""
    monkeypatch.setenv("OMNIVOICE_PORT", "4080")
    assert uvicorn_arguments([]) == [
        "-m",
        "uvicorn",
        "backend.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "4080",
    ]


def test_docker_entrypoint_preserves_explicit_uvicorn_options(monkeypatch) -> None:
    """Options supplied after the image replace defaults and pass through intact."""
    monkeypatch.setenv("OMNIVOICE_PORT", "3900")
    supplied = ["--host=127.0.0.1", "--port", "8080", "--workers", "2"]
    arguments = uvicorn_arguments(supplied)
    assert arguments == ["-m", "uvicorn", "backend.main:app", *supplied]
