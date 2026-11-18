"""스캔 대상의 파일을 훑거나 찾을 때 쓰는 공용 함수. engine/dataset.py, engine/ai_service.py, engine/model.py 가 쓴다.

    SKIP_DIRS       건너뛰는 폴더 (설치된 의존성, 캐시, .git)
    is_inside       심볼릭 링크를 따라간 실제 위치가 루트 안인가
    find_file       대상 루트 기준으로 적힌 위치를 실제 파일로 (없거나 대상 밖이면 None)
    relative_path   대상 루트 기준 상대 경로 (링크를 따라가지 않는다)
    notebook_code   노트북(.ipynb)의 코드 셀을 이어 붙인 파이썬 소스
"""
from __future__ import annotations

import json
from pathlib import Path

SKIP_DIRS = frozenset({"node_modules", ".git", "venv", ".venv", "site-packages", "dist-packages", "__pycache__"})


def is_inside(path: Path, root_resolved: Path) -> bool:
    """심볼릭 링크를 따라간 실제 위치가 root 안인가."""
    try:
        return path.resolve().is_relative_to(root_resolved)
    except OSError:
        return False


def find_file(root: Path, root_resolved: Path, location: str) -> Path | None:
    """대상 루트 기준 경로(cdxgen 이 쓰는 모양)를 실제 파일로. 링크를 따라간 뒤에도 대상 안이어야 한다."""
    text = location.replace("\\", "/")
    candidates = [root / text.lstrip("/")]
    if Path(text).is_absolute():
        candidates.insert(0, Path(text))
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            if resolved.is_file() and resolved.is_relative_to(root_resolved):
                return resolved
        except OSError:
            continue
    return None


def relative_path(path: Path, root: Path) -> str:
    """대상 루트 기준 상대 경로. 링크를 따라가지 않으므로 대상 안의 이름이 그대로 나오고, 머신 경로는 나오지 않는다."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path.resolve().relative_to(root.resolve())
    return rel.as_posix() or "."


def notebook_code(text: str) -> str:
    """노트북(.ipynb)의 코드 셀을 이어 붙인 파이썬 소스. `%magic`·`!shell` 줄은 파이썬이 아니라 뺀다."""
    cells = json.loads(text)["cells"]
    lines: list[str] = []
    for cell in cells:
        if not isinstance(cell, dict) or cell.get("cell_type") != "code":
            continue
        source = cell.get("source") or []
        for line in (source if isinstance(source, list) else source.splitlines(True)):
            if not isinstance(line, str):
                continue
            lines.append("\n" if line.lstrip().startswith(("%", "!")) else line)
        if lines and not lines[-1].endswith("\n"):
            lines.append("\n")
    return "".join(lines)
