"""validate 명령 핸들러. BOM 파일을 읽어 service/validate_service.py 에 넘기고, 결과를 찍고, 종료 코드를 돌려준다."""
from __future__ import annotations

import argparse
import json

from ..formats import FORMAT_NAME, SPEC_BY_FORMAT
from ..service import validate_service
from .exit_codes import EXIT_INVALID, EXIT_TOOL
from .log import log


def cmd_validate(args: argparse.Namespace) -> int:
    doc = _read_json(args.bom)
    if doc is None:
        return EXIT_TOOL
    result = validate_service.validate(doc, args.spec, log=log)
    if result.fmt is None:
        log(f"[sure-aibom] error: not a CycloneDX or SPDX document (no bomFormat or @context): {args.bom}")
        return EXIT_TOOL
    if result.valid is None:
        log(f"[sure-aibom] error: --spec {result.spec} is not a {result.fmt} spec, and {args.bom} is a {result.fmt} document "
            f"(use {' or '.join(SPEC_BY_FORMAT[result.fmt])})")
        return EXIT_TOOL
    name = f"{FORMAT_NAME[(result.fmt, result.spec)]} schema"
    if not result.valid:
        log(f"[sure-aibom] Invalid against the {name} (--spec {result.spec}): {args.bom}")
        return EXIT_INVALID
    log(f"[sure-aibom] Valid against the {name}: {args.bom}")
    return 0


def _read_json(path: str) -> dict | None:
    """읽지 못하면 이유를 찍고 None 을 돌려준다."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log(f"[sure-aibom] error: cannot read {path} ({e})")
        return None
