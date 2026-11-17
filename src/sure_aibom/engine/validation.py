"""BOM 문서를 고른 스키마로 검증한다. 형식은 문서에서 알아낸다 (bomFormat 이 있으면 CycloneDX, @context 가 있으면 SPDX).

    CycloneDX   "1.7" 공식 CycloneDX 1.7 (properties 형) · "v0.6" aibom-v0.6 CycloneDX (typed 형)      draft-07
    SPDX        "3.0.1" 공식 SPDX 3.0.1 · "v0.6" aibom-v0.6 SPDX (aibom_* 속성)                        2020-12

스키마는 패키지 안 schemas/ 에 있다. 자동으로 다른 스키마를 시도하지 않는다 — spec 이 형식에 맞지 않으면 schema_for 가 None 이다."""
from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

import jsonschema
from jsonschema.exceptions import best_match
from referencing import Registry, Resource

SCHEMA_DIR = Path(str(files("sure_aibom") / "schemas"))   # 패키지 안. 편집 설치·wheel 설치 어디서든 같은 위치
CDX_SCHEMA = SCHEMA_DIR / "aibom-v0.6-cyclonedx.schema.json"
CDX_OFFICIAL = SCHEMA_DIR / "bom-1.7.schema.json"
SPDX_SCHEMA = SCHEMA_DIR / "aibom-v0.6-spdx.schema.json"
SPDX_OFFICIAL = SCHEMA_DIR / "spdx-3.0.1.schema.json"
CDX_SCHEMA_BY_SPEC = {"1.7": CDX_OFFICIAL, "v0.6": CDX_SCHEMA}
SPDX_SCHEMA_BY_SPEC = {"3.0.1": SPDX_OFFICIAL, "v0.6": SPDX_SCHEMA}
SCHEMA_BY_FORMAT = {"cyclonedx": CDX_SCHEMA_BY_SPEC, "spdx": SPDX_SCHEMA_BY_SPEC}
CDX_SCHEMAS = ("bom-1.7.schema.json", "aibom-v0.6-cyclonedx.schema.json", "cryptography-defs.schema.json", "jsf-0.82.schema.json",
               "spdx.schema.json")                         # CycloneDX 스키마가 $ref 로 서로 가리키는 파일들


@lru_cache(maxsize=8)
def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def detect_format(doc: dict) -> str | None:
    """문서의 형식. CycloneDX 는 bomFormat, SPDX 3 JSON-LD 는 @context 로 안다. 둘 다 아니면 None."""
    if not isinstance(doc, dict):
        return None
    if "bomFormat" in doc:
        return "cyclonedx"
    if "@context" in doc or "@graph" in doc:
        return "spdx"
    return None


def schema_for(fmt: str, spec: str) -> Path | None:
    """형식과 spec 에 맞는 스키마 파일. spec 이 그 형식의 것이 아니면 None."""
    return SCHEMA_BY_FORMAT.get(fmt, {}).get(spec)


def _cdx_errors(doc: dict, schema_path: Path) -> list[str]:
    registry = Registry()
    for name in CDX_SCHEMAS:
        schema = _load(SCHEMA_DIR / name)
        uri = schema.get("$id") or name
        registry = registry.with_resource(uri, Resource.from_contents(schema))
        registry = registry.with_resource(name, Resource.from_contents(schema))
    validator = jsonschema.Draft7Validator(_load(schema_path), registry=registry)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    return [f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors]


@lru_cache(maxsize=256)
def _class_validator(schema_path: Path, cls: str) -> jsonschema.Draft202012Validator:
    """@graph 항목 하나를 그 클래스 정의로만 검사하는 검사기. 스키마 원문은 항목마다 78개 클래스의 anyOf 를 다 대 보라 문서 하나에
    수십 초가 걸리는데, 항목의 type 이 곧 클래스라 그것만 대 보면 같은 결과를 훨씬 빨리 낸다."""
    schema = _load(schema_path)
    wrapper = {"$schema": schema.get("$schema"), "$defs": schema["$defs"], "type": "object",
               "allOf": [{"$ref": f"#/$defs/{cls}"}], "unevaluatedProperties": False}
    return jsonschema.Draft202012Validator(wrapper)


def _spdx_errors(doc: dict, schema_path: Path) -> list[str]:
    schema = _load(schema_path)
    head = jsonschema.Draft202012Validator({
        "type": "object", "required": ["@context", "@graph"],
        "properties": {"@context": schema["properties"]["@context"],
                       "@graph": {"type": "array", "items": {"type": "object", "required": ["type"]}}}})
    out = [f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in sorted(head.iter_errors(doc), key=lambda e: list(e.path))]
    if out:
        return out
    classes = {ref["$ref"].split("/")[-1] for ref in schema["$defs"]["AnyClass"]["anyOf"]}
    for i, item in enumerate(doc["@graph"]):
        cls = item.get("type")
        if cls not in classes:
            out.append(f"@graph/{i}: {cls!r} is not an SPDX class")
            continue
        for e in sorted(_class_validator(schema_path, cls).iter_errors(item), key=lambda e: list(e.path)):
            cause = best_match([e]) if e.context else e
            where = "/".join(["@graph", str(i), *(str(p) for p in cause.absolute_path)])
            message = cause.message if len(cause.message) <= 300 else cause.message[:300] + " …"
            out.append(f"{where}: {message}")
    return out


def _validate_cdx(doc: dict, spec: str, log=print) -> bool:
    """CycloneDX 문서를 spec 이 고른 스키마 하나로만 검사한다. "1.7" 은 공식 CycloneDX 1.7 (properties 형),
    "v0.6" 은 aibom-v0.6 CycloneDX 스키마 (typed 형). 자동으로 다른 쪽을 시도하지 않는다."""
    if spec not in CDX_SCHEMA_BY_SPEC:
        raise ValueError(f"spec 은 {tuple(CDX_SCHEMA_BY_SPEC)} 중 하나여야 한다: {spec!r}")
    errors = _cdx_errors(doc, CDX_SCHEMA_BY_SPEC[spec])
    _report(errors, log)
    return not errors


def _validate_spdx(doc: dict, spec: str, log=print) -> bool:
    """SPDX 3.0.1 JSON-LD 문서를 spec 이 고른 스키마 하나로만 검사한다. "3.0.1" 은 공식 스키마, "v0.6" 은 aibom-v0.6 SPDX 스키마."""
    if spec not in SPDX_SCHEMA_BY_SPEC:
        raise ValueError(f"spec 은 {tuple(SPDX_SCHEMA_BY_SPEC)} 중 하나여야 한다: {spec!r}")
    errors = _spdx_errors(doc, SPDX_SCHEMA_BY_SPEC[spec])
    _report(errors, log)
    return not errors


def validate_doc(doc: dict, fmt: str, spec: str, log=print) -> bool:
    """형식에 맞는 검사기로 넘긴다. schema_for(fmt, spec) 가 None 이면 ValueError."""
    if schema_for(fmt, spec) is None:
        raise ValueError(f"{spec} 은 {fmt} 의 스키마가 아니다")
    return (_validate_cdx if fmt == "cyclonedx" else _validate_spdx)(doc, spec, log)


def _report(messages: list[str], log) -> None:
    for m in messages[:20]:
        log(f"[sure-aibom]   {m}")
    if len(messages) > 20:
        log(f"[sure-aibom]   ... and {len(messages) - 20} more")
