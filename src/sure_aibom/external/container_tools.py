"""이미지 이름을 .tar 로 받는다 (docker, podman, crane).

    이미지 이름 (alpine:3.20, ghcr.io/org/img)   docker, podman, crane 순으로 PATH 에 있는 것으로 .tar 를 받는다

받은 .tar 를 디렉터리로 푸는 것은 engine/image_tar.py 다.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from ..exceptions import RunnerError
from ..utils.host import host_arch
from ._proc import run

PULL_TOOLS = ("docker", "podman", "crane")           # syft 와 같은 순서: 데몬 → 레지스트리


def pull_image(ref: str, workdir: Path) -> tuple[Path, str]:
    """이미지 이름을 workdir/image.tar 로 받는다. (tar 경로, 쓴 도구). docker·podman 은 데몬에 있는 이미지를 save 하고
    없으면 pull 한 뒤 save 한다. crane 은 레지스트리에서 이 머신의 플랫폼으로 받는다. 하나가 실패하면 다음 것을 쓴다."""
    tools = [t for t in PULL_TOOLS if shutil.which(t)]
    if not tools:
        raise RunnerError(f"docker, podman or crane is needed to fetch {ref} (or pass the image as a .tar)")
    tar_path = workdir / "image.tar"
    errors: list[str] = []
    for tool in tools:
        try:
            _pull_with(tool, ref, tar_path)
            return tar_path, tool
        except RunnerError as e:
            errors.append(f"{tool}: {e}")
    raise RunnerError("\n".join([f"could not fetch {ref}", *errors]))


def _pull_with(tool: str, ref: str, tar_path: Path) -> None:
    if tool == "crane":
        _check(run(["crane", "pull", "--platform", f"linux/{host_arch()}", ref, str(tar_path)]), "crane pull")
    else:
        save = [tool, "image", "save", "-o", str(tar_path), ref]
        if run(save).returncode != 0:                        # 데몬에 없으면 받아서 다시
            _check(run([tool, "pull", ref]), f"{tool} pull")
            _check(run(save), f"{tool} image save")
    if not tar_path.exists() or tar_path.stat().st_size == 0:
        raise RunnerError(f"{tool} produced no tar")


def _check(proc, what: str) -> None:
    if proc.returncode != 0:
        lines = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise RunnerError(f"{what} exited with {proc.returncode}" + (f": {lines[-1].strip()}" if lines else ""))
