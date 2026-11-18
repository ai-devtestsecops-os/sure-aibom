"""명령들이 같이 쓰는 로그: 로그 줄과 단계 줄. 전부 표준에러로 찍어 표준출력의 BOM 과 섞이지 않는다."""
from __future__ import annotations

import sys

STAGE_WIDTH = 36                                   # 단계 이름 뒤 점선까지의 너비


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def quiet(msg: str) -> None:
    """모듈의 항목별 로그는 -v 없이는 찍지 않는다 (단계마다 한 줄만 찍는다)."""


def stage(label: str, result: str = "") -> None:
    dots = "." * max(3, STAGE_WIDTH - len(label))
    log(f"[sure-aibom] {label} {dots} {result}".rstrip())
