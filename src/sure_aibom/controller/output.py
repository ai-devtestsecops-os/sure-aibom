"""명령들이 같이 쓰는 출력: 종료 코드, 로그 줄과 단계 줄(표준에러)."""
from __future__ import annotations

import sys

EXIT_TOOL = 2      # 실행 오류 (잘못된 인자·입력, 도구 없음·실패)
EXIT_INVALID = 3   # 스키마 불일치 (1 은 파이썬이 처리 못 한 예외로 죽을 때 내므로 비워 둔다)
STAGE_WIDTH = 36                                   # 단계 이름 뒤 점선까지의 너비


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def quiet(msg: str) -> None:
    """모듈의 항목별 로그는 -v 없이는 찍지 않는다 (단계마다 한 줄만 찍는다)."""


def stage(label: str, result: str = "") -> None:
    dots = "." * max(3, STAGE_WIDTH - len(label))
    log(f"[sure-aibom] {label} {dots} {result}".rstrip())
