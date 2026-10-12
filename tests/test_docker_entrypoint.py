"""Docker startup preserves its stable defaults and explicit Uvicorn options."""


def test_docker_entrypoint_uses_the_resolved_backend_port(monkeypatch) -> None:
    """The default launch and backend health resolver share OMNIVOICE_PORT."""
    from docker_entrypoint import uvicorn_arguments

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


def test_docker_entrypoint_preserves_explicit_uvicorn_options(monkeypatch, tmp_path) -> None:
    """Options supplied after the image replace defaults and pass through intact."""
    import docker_entrypoint

    monkeypatch.setenv("OMNIVOICE_PORT", "3900")
    supplied = ["--host=127.0.0.1", "--port", "8080", "--workers", "2"]
    arguments = docker_entrypoint.uvicorn_arguments(supplied)
    assert arguments == ["-m", "uvicorn", "backend.main:app", *supplied]
    assert docker_entrypoint.effective_port(supplied) == 8080

    port_file = tmp_path / "backend-port"
    port_file.write_text("8080", encoding="ascii")
    response = type("Response", (), {"close": lambda self: None})()
    opened = []
    monkeypatch.setattr(
        docker_entrypoint,
        "urlopen",
        lambda url, timeout: opened.append((url, timeout)) or response,
    )
    docker_entrypoint.healthcheck(port_file)
    assert opened == [("http://127.0.0.1:8080/health", 4)]
