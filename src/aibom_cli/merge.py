"""CycloneDX 문서 여러 개를 하나로 병합한다.

병합 키 (aibom_cli_plan.md §4):
    소프트웨어  purl
    모델        pkg:huggingface/ns/name@rev → 없으면 hashes → 없으면 (type, name, version)
    데이터셋    pkg:huggingface/datasets/… (cdxgen 만 생산)

같은 키의 컴포넌트가 여러 문서에 있으면 먼저 온 것을 기준으로 두고, 없는 필드만 뒤 것에서 채운다.
bom-ref 는 병합 키로 다시 부여하고 dependencies[] 의 참조를 따라 바꾼다.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Iterable

SPEC_VERSION = "1.7"


def identity(component: dict) -> str:
    """컴포넌트의 병합 키."""
    purl = component.get("purl")
    if purl:
        return purl
    hashes = component.get("hashes") or []
    for h in hashes:
        if h.get("alg") in ("SHA-256", "SHA-512", "SHA-1") and h.get("content"):
            return f"hash:{h['alg']}:{h['content']}"
    return f"{component.get('type', 'component')}:{component.get('group', '')}/{component.get('name', '')}@{component.get('version', '')}"


def _fill_missing(base: dict, extra: dict) -> None:
    """base 에 없는 키만 extra 에서 채운다. properties/externalReferences 는 합친다."""
    for k, v in extra.items():
        if k not in base:
            base[k] = v
    for list_key, dedupe_key in (("properties", lambda p: (p.get("name"), p.get("value"))),
                                 ("externalReferences", lambda r: (r.get("type"), r.get("url")))):
        if list_key in extra:
            seen = {dedupe_key(x) for x in base.get(list_key, [])}
            merged = list(base.get(list_key, []))
            for x in extra[list_key]:
                if dedupe_key(x) not in seen:
                    merged.append(x)
                    seen.add(dedupe_key(x))
            if merged:
                base[list_key] = merged


def _walk_components(components: Iterable[dict]):
    for c in components:
        yield c
        yield from _walk_components(c.get("components") or [])


def merge(docs: list[dict]) -> dict:
    components: dict[str, dict] = {}
    ref_map: dict[str, str] = {}          # 원래 bom-ref → 병합 키
    dependencies: dict[str, set[str]] = {}
    tools: dict[tuple, dict] = {}
    formulation: list[dict] = []
    services: list[dict] = []

    for doc in docs:
        for comp in _walk_components(doc.get("components") or []):
            comp = dict(comp)
            key = identity(comp)
            old_ref = comp.get("bom-ref")
            if old_ref:
                ref_map[old_ref] = key
            comp.pop("components", None)
            if key in components:
                _fill_missing(components[key], comp)
            else:
                components[key] = comp

        for dep in doc.get("dependencies") or []:
            dependencies.setdefault(dep.get("ref"), set()).update(dep.get("dependsOn") or [])

        for tool in (doc.get("metadata") or {}).get("tools", {}).get("components", []) or []:
            tools.setdefault((tool.get("name"), tool.get("version")), tool)

        formulation.extend(doc.get("formulation") or [])
        services.extend(doc.get("services") or [])

    for key, comp in components.items():
        comp["bom-ref"] = key

    def remap(ref: str) -> str:
        return ref_map.get(ref, ref)

    merged_deps: dict[str, set[str]] = {}
    for ref, targets in dependencies.items():
        r = remap(ref)
        merged_deps.setdefault(r, set()).update(remap(t) for t in targets)

    tools["aibom-cli"] = {"type": "application", "name": "aibom-cli", "version": _version()}

    return {
        "bomFormat": "CycloneDX",
        "specVersion": SPEC_VERSION,
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "tools": {"components": list(tools.values())},
        },
        "components": list(components.values()),
        "services": services,
        "dependencies": [
            {"ref": r, "dependsOn": sorted(t for t in targets if t in components or t in merged_deps)}
            for r, targets in merged_deps.items()
        ],
        "formulation": formulation,
    }


def _version() -> str:
    from . import __version__
    return __version__
