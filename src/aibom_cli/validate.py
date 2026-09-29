"""CycloneDX 문서를 고른 스키마(공식 1.7 또는 aibom-v0.6)로 검증한다. 스키마는 패키지 안 schemas/ 에 있다 (draft-07)."""
from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

import jsonschema
from referencing import Registry, Resource

SCHEMA_DIR = Path(str(files("aibom_cli") / "schemas"))   # 패키지 안. 편집 설치·wheel 설치 어디서든 같은 위치
CDX_SCHEMA = SCHEMA_DIR / "aibom-v0.6-cyclonedx.schema.json"
CDX_OFFICIAL = SCHEMA_DIR / "bom-1.7.schema.json"
CDX_SCHEMA_BY_SPEC = {"1.7": CDX_OFFICIAL, "v0.6": CDX_SCHEMA}     # validate --spec 의 선택지


@lru_cache(maxsize=4)
def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _cdx_errors(doc: dict, schema_path: Path) -> list[str]:
    registry = Registry()
    for f in SCHEMA_DIR.glob("*.json"):
        schema = _load(f)
        uri = schema.get("$id") or f.name
        registry = registry.with_resource(uri, Resource.from_contents(schema))
        registry = registry.with_resource(f.name, Resource.from_contents(schema))
    validator = jsonschema.Draft7Validator(_load(schema_path), registry=registry)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    return [f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors]


def validate_cdx(doc: dict, spec: str, log=print) -> bool:
    """CycloneDX 문서를 spec 이 고른 스키마 하나로만 검사한다. "1.7" 은 공식 CycloneDX 1.7 (properties 형),
    "v0.6" 은 aibom-v0.6 CycloneDX 스키마 (typed 형). 자동으로 다른 쪽을 시도하지 않는다."""
    if spec not in CDX_SCHEMA_BY_SPEC:
        raise ValueError(f"spec 은 {tuple(CDX_SCHEMA_BY_SPEC)} 중 하나여야 한다: {spec!r}")
    errors = _cdx_errors(doc, CDX_SCHEMA_BY_SPEC[spec])
    _report(errors, log)
    return not errors


def _report(messages: list[str], log) -> None:
    for m in messages[:20]:
        log(f"[aibom-cli]   {m}")
    if len(messages) > 20:
        log(f"[aibom-cli]   ... and {len(messages) - 20} more")
