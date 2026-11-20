"""이 머신의 CPU 종류를 컨테이너 이미지가 쓰는 이름(amd64, arm64)으로 돌려준다. engine/container_tools.py, engine/image_tar.py 가 쓴다."""
from __future__ import annotations

import platform

ARCH_BY_MACHINE = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}


def host_arch() -> str:
    machine = platform.machine().lower()
    return ARCH_BY_MACHINE.get(machine, machine)
