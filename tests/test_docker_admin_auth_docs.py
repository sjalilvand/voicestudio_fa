"""Docker quick starts must preserve the server-mode admin credential."""

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "relative_path",
    ["docs/install/docker.md", "deploy/dockerhub-overview.md"],
)
def test_every_studio_docker_run_passes_the_admin_key(relative_path):
    text = (ROOT / relative_path).read_text(encoding="utf-8")
    commands = [
        block
        for block in re.findall(r"```bash\n(.*?)```", text, flags=re.DOTALL)
        if "docker run" in block and "omnivoice-studio:" in block
    ]

    assert commands
    for command in commands:
        assert '-e OMNIVOICE_API_KEY="$OMNIVOICE_API_KEY"' in command


def test_every_compose_studio_service_receives_the_admin_key():
    text = (ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8")
    studio_half = text.split("worker-gpu:", 1)[0]

    assert studio_half.count("OMNIVOICE_API_KEY=${OMNIVOICE_API_KEY:-}") == 3


def test_wsl_rocm_command_carries_the_complete_dxg_bridge():
    text = (ROOT / "docs/install/docker.md").read_text(encoding="utf-8")
    section = text.split("### AMD GPU on WSL2", 1)[1].split("###", 1)[0]

    for required in (
        "--device /dev/dxg",
        "/usr/lib/wsl/lib/libdxcore.so:/usr/lib/libdxcore.so",
        "/opt/rocm/lib/librocdxg.so:/usr/lib/librocdxg.so",
        "/opt/rocm/share/rocdxg/dids.conf:/usr/share/rocdxg/dids.conf",
        "HSA_ENABLE_DXG_DETECTION=1",
        "--cap-add SYS_PTRACE",
        "--security-opt seccomp=unconfined",
    ):
        assert required in section
