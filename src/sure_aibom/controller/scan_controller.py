"""scan 명령 (참고 구조의 controller). 인자를 확인해 service/scan_service.py 에 값만 넘기고, 단계 줄과 결과를 찍는다."""
from __future__ import annotations

import argparse
from pathlib import Path

from ..formats import FORMAT_NAME, SPEC_BY_FORMAT
from ..service import scan_service
from ..service.scan_service import count, groups
from .output import EXIT_TOOL, emit, log, quiet, stage


def cmd_scan(args: argparse.Namespace) -> int:
    """단계마다 한 줄씩 찍는다. 항목별 내용은 찍지 않고, 사용자가 할 일이 있는 것(건너뜀·실패)만 그 줄에 붙인다.
    syft·cdxgen 중 하나라도 실패하면 만든 만큼은 쓰되 종료 코드 2 로 끝낸다 (CI 가 모자란 BOM 을 성공으로 넘기지 않게)."""
    args.spec = args.spec or SPEC_BY_FORMAT[args.format][0]
    if args.spec not in SPEC_BY_FORMAT[args.format]:
        log(f"[sure-aibom] error: --spec {args.spec} is not a {args.format} spec (use {' or '.join(SPEC_BY_FORMAT[args.format])})")
        return EXIT_TOOL
    if args.target.startswith("~"):
        args.target = str(Path(args.target).expanduser())
    errors = scan_service.check_scan(args.target, args.data)
    for error in errors:
        log(f"[sure-aibom] error: {error}")
    if errors:
        return EXIT_TOOL

    data = f", data from {', '.join(args.data)}" if args.data else ""
    log(f"[sure-aibom] Generating {FORMAT_NAME[(args.format, args.spec)]} for {args.target}{data}")
    detail = log if getattr(args, "verbose", False) else quiet     # -v: 모듈의 항목별 로그(건너뛴 것, 버린 값, 빈 필드)도 찍는다
    result = scan_service.scan(args.target, args.data, args.format, args.spec, stage=stage, log=log, detail=detail)
    if result is None:
        log("[sure-aibom] error: neither syft nor cdxgen produced a BOM")
        return EXIT_TOOL

    emit(result.doc, args.output)
    # 단계 줄들을 더하지 않고 다 만든 BOM 을 다시 센다 (병합·별칭 합치기로 줄어든 만큼이 여기 반영된다)
    bom = result.bom
    log(f"[sure-aibom] Wrote {args.output or 'stdout'} ({count(len(bom['components']), 'component')}: "
        f"{groups(bom['components'])}; {count(len(bom['dependencies']), 'dependency', 'dependencies')})")
    if result.failed:
        log(f"[sure-aibom] error: {' and '.join(result.failed)} failed, so the BOM is incomplete")
        return EXIT_TOOL
    return 0
