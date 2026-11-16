"""명령들이 같이 쓰는 출력: 종료 코드, 로그 줄과 단계 줄(표준에러), BOM 파일 쓰기와 읽기."""
from __future__ import annotations

import json
import sys
from pathlib import Path

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


def emit(doc: dict, path: str | None) -> None:
    """경로가 있으면 파일로, 없으면 표준출력으로."""
    text = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    if path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def read_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log(f"[sure-aibom] error: cannot read {path} ({e})")
        return None
