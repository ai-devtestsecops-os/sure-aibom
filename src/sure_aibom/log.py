"""로그 줄과 단계 줄. controller, service, engine, external 이 같이 쓴다. 전부 표준에러로 찍어 표준출력의 BOM 과 섞이지 않는다.

    stage    단계 한 줄. 항상 찍는다. service/scan_service.py 가 쓴다
    log      항상 찍는 줄 (시작과 끝, 오류, 경고, 실패한 단계의 상세). controller, service, engine/validation.py 가 쓴다
    detail   -v 일 때만 찍는 줄 (모듈의 항목별 로그: 건너뛴 것, 버린 값, 빈 필드). engine 과 external/hub.py 가 쓴다

-v 를 줬는지는 controller/scan_controller.py 가 스캔을 시작할 때 set_verbose 로 한 번 알려 준다.
"""
from __future__ import annotations

import sys

STAGE_WIDTH = 36                                   # 단계 이름 뒤 점선까지의 너비
_verbose = False                                   # -v 를 줬는가. set_verbose 만 바꾼다


def set_verbose(on: bool) -> None:
    global _verbose
    _verbose = on


def stage(label: str, result: str = "") -> None:
    dots = "." * max(3, STAGE_WIDTH - len(label))
    _write(f"[sure-aibom] {label} {dots} {result}".rstrip())


def log(msg: str) -> None:
    _write(msg)


def detail(msg: str) -> None:
    if _verbose:
        _write(msg)


def _write(msg: str) -> None:
    print(msg, file=sys.stderr)
