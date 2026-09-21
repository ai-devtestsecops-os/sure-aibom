"""aibom-v0.6 스키마로 출력을 검증한다. jsonschema 가 없으면 건너뛴다."""
from __future__ import annotations

import json
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"
CDX_SCHEMA = SCHEMA_DIR / "aibom-v0.6-cyclonedx.schema.json"
SPDX_SCHEMA = SCHEMA_DIR / "aibom-v0.6-spdx.schema.json"


def validate_cdx(doc: dict, log=print) -> bool:
    try:
        import jsonschema
        from referencing import Registry, Resource
    except ImportError:
        log("[validate] jsonschema/referencing 미설치 — 검증 생략 (pip install 'aibom-cli[validate]')")
        return True

    registry = Registry()
    for f in SCHEMA_DIR.glob("*.json"):
        with f.open(encoding="utf-8") as fh:
            schema = json.load(fh)
        uri = schema.get("$id") or f.name
        registry = registry.with_resource(uri, Resource.from_contents(schema))
        registry = registry.with_resource(f.name, Resource.from_contents(schema))

    with CDX_SCHEMA.open(encoding="utf-8") as fh:
        root = json.load(fh)
    validator = jsonschema.Draft7Validator(root, registry=registry)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    for e in errors[:20]:
        log(f"[validate] {'/'.join(str(p) for p in e.path)}: {e.message}")
    if len(errors) > 20:
        log(f"[validate] … 외 {len(errors) - 20}건")
    return not errors
