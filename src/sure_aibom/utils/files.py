"""스캔 대상의 파일을 걸을 때 쓰는 공용 함수 (engine/dataset.py, engine/ai_service.py).

    SKIP_DIRS       걷지 않는 폴더 (설치된 의존성, 캐시, .git)
    inside          심볼릭 링크를 따라간 실제 위치가 루트 안인가
    relative        대상 루트 기준 상대 경로 (링크를 따라가지 않는다)
    notebook_code   노트북(.ipynb)의 코드 셀을 이어 붙인 파이썬 소스
"""
from __future__ import annotations

import json
from pathlib import Path

SKIP_DIRS = frozenset({"node_modules", ".git", "venv", ".venv", "site-packages", "dist-packages", "__pycache__"})


def inside(path: Path, root_resolved: Path) -> bool:
    """심볼릭 링크를 따라간 실제 위치가 root 안인가."""
    try:
        return path.resolve().is_relative_to(root_resolved)
    except OSError:
        return False


def relative(path: Path, root: Path) -> str:
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
