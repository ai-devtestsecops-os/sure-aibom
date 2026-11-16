"""validate 명령 (참고 구조의 controller). BOM 파일을 읽어 service/validate.py 에 넘기고 결과를 찍는다."""
from __future__ import annotations

import argparse

from ..formats import FORMAT_NAME, SPEC_BY_FORMAT
from ..service import validate as validate_service
from .output import EXIT_INVALID, EXIT_TOOL, log, read_json


def cmd_validate(args: argparse.Namespace) -> int:
    doc = read_json(args.bom)
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
