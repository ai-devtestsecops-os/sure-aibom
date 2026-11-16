"""validate 의 흐름 (참고 구조의 service). 형식 알아내기 → spec 고르기 → 스키마 검증.

BOM 파일을 읽고 결과를 찍는 것은 controller/validate.py 다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..engine.validate import detect_format, schema_for, validate_doc
from ..formats import SPEC_BY_FORMAT


@dataclass
class Validation:
    fmt: str | None        # cyclonedx · spdx. 문서에서 알아내지 못하면 None
    spec: str | None       # 검증에 쓴 spec (주지 않았으면 그 형식의 기본)
    valid: bool | None     # None 이면 검증하지 못했다 (형식을 모르거나 spec 이 그 형식의 것이 아니다)


def _quiet(msg: str) -> None:
    """찍지 않는다."""


def validate(doc: dict, spec: str | None, log: Callable[[str], None] = _quiet) -> Validation:
    """문서를 스키마로 검증한다. 형식은 문서에서 알아내고(bomFormat 이 있으면 CycloneDX, @context 가 있으면 SPDX),
    spec 을 주지 않으면 CycloneDX 문서는 1.7, SPDX 문서는 3.0.1 로 본다. 어긋난 곳은 log 로 알린다."""
    fmt = detect_format(doc)
    if fmt is None:
        return Validation(None, spec, None)
    spec = spec or SPEC_BY_FORMAT[fmt][0]
    if schema_for(fmt, spec) is None:
        return Validation(fmt, spec, None)
    return Validation(fmt, spec, validate_doc(doc, fmt, spec, log=log))
