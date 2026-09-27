"""Locate NVIDIA's management CLI consistently, including its WSL path."""

from __future__ import annotations

import os
import shutil

_WSL_NVIDIA_SMI = "/usr/lib/wsl/lib/nvidia-smi"


def find_nvidia_smi() -> str | None:
    executable = shutil.which("nvidia-smi")
    if executable:
        return executable
    return _WSL_NVIDIA_SMI if os.path.isfile(_WSL_NVIDIA_SMI) else None
