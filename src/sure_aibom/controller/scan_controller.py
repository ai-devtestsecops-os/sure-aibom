"""scan 명령 핸들러. 인자를 확인해 service/scan_service.py 에 값만 넘기고, 결과를 찍고, BOM 을 쓰고, 종료 코드를 돌려준다."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..formats import FORMAT_NAME, SPEC_BY_FORMAT
from ..log import log, set_verbose
from ..service import scan_service
from ..service.scan_service import count, groups
from .exit_codes import EXIT_TOOL


def cmd_scan(args: argparse.Namespace) -> int:
    """인자와 입력을 확인하고, service 에 스캔을 맡긴 뒤, 받은 BOM 을 쓰고 요약 한 줄을 찍는다. 단계 줄은 service 가 찍는다.
    syft·cdxgen 중 하나라도 실패하면 만든 만큼은 쓰되 종료 코드 2 로 끝낸다 (CI 가 모자란 BOM 을 성공으로 넘기지 않게)."""
    args.spec = args.spec or SPEC_BY_FORMAT[args.format][0]
    if args.spec not in SPEC_BY_FORMAT[args.format]:            # 명령줄만 보면 아는 확인(옵션 조합)은 여기서 한다
        log(f"[sure-aibom] error: --spec {args.spec} is not a {args.format} spec (use {' or '.join(SPEC_BY_FORMAT[args.format])})")
        return EXIT_TOOL
    if args.target.startswith("~"):
        args.target = str(Path(args.target).expanduser())
    errors = scan_service.check_scan(args.target, args.data)    # 실제로 있는지 봐야 하는 확인(경로, --data, 허브 리비전)은 service 가 한다
    for error in errors:
        log(f"[sure-aibom] error: {error}")
    if errors:
        return EXIT_TOOL

    data = f", data from {', '.join(args.data)}" if args.data else ""
    log(f"[sure-aibom] Generating {FORMAT_NAME[(args.format, args.spec)]} for {args.target}{data}")
    set_verbose(getattr(args, "verbose", False))                   # -v: 모듈의 항목별 로그(건너뛴 것, 버린 값, 빈 필드)도 찍는다
    result = scan_service.scan(args.target, args.data, args.format, args.spec)
    if result is None:
        log("[sure-aibom] error: neither syft nor cdxgen produced a BOM")
        return EXIT_TOOL

    _write_json(result.doc, args.output)
    # 단계 줄들을 더하지 않고 다 만든 BOM 을 다시 센다 (병합·별칭 합치기로 줄어든 만큼이 여기 반영된다)
    bom = result.bom
    log(f"[sure-aibom] Wrote {args.output or 'stdout'} ({count(len(bom['components']), 'component')}: "
        f"{groups(bom['components'])}; {count(len(bom['dependencies']), 'dependency', 'dependencies')})")
    if result.failed:
        log(f"[sure-aibom] error: {' and '.join(result.failed)} failed, so the BOM is incomplete")
        return EXIT_TOOL
    return 0


def _write_json(doc: dict, path: str | None) -> None:
    """경로가 있으면 파일로, 없으면 표준출력으로."""
    text = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    if path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
