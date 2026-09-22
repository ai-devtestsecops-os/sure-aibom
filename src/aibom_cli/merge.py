"""CycloneDX 문서 여러 개를 하나로 병합한다.

병합 키 (aibom_cli_plan.md §4):
    소프트웨어  purl
    모델        pkg:huggingface/ns/name@rev → 없으면 hashes → 없으면 (type, name, version)
    데이터셋    pkg:huggingface/datasets/… (cdxgen 만 생산)

같은 키의 컴포넌트가 여러 문서에 있으면 먼저 온 것을 기준으로 두고, 없는 필드만 뒤 것에서 채운다.
bom-ref 는 병합 키로 다시 부여하고 dependencies[] 의 참조를 따라 바꾼다.

root=(이름, 종류) 를 주면 metadata.component 를 만든다 (디렉터리 → application, 이미지 → container).
두 도구의 metadata.component 는 버리므로 이것이 SPDX Sbom.rootElement 의 실제 루트가 된다.
각 도구가 자기 metadata.component 를 ref 로 쓴 dependencies 행은 새 루트의 행으로 옮기고, 루트는 그 밖에
아무도(컴포넌트·루트가) 의존하지 않는 컴포넌트에도 의존한다 — 그래프 전체가 루트에서 닿는다.
ref 가 컴포넌트도 루트도 아닌 행(서비스 등)은 그대로 두되(변환기가 경고하고 건너뛴다) 그 대상을 '의존받음'으로 치지 않는다.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Iterable

SPEC_VERSION = "1.7"
ROOT_TYPE_BY_KIND = {"directory": "application", "image": "container"}


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


def root_component(name: str, kind: str) -> dict:
    """스캔 대상 → metadata.component. bom-ref 는 identity 규칙으로 정해 결정적이다."""
    comp = {"type": ROOT_TYPE_BY_KIND.get(kind, "application"), "name": name}
    comp["bom-ref"] = identity(comp)
    return comp


def merge(docs: list[dict], root: tuple[str, str] | None = None) -> dict:
    components: dict[str, dict] = {}
    ref_map: dict[str, str] = {}          # 원래 bom-ref → 병합 키
    dependencies: dict[str, set[str]] = {}
    tools: dict[tuple, dict] = {}
    formulation: list[dict] = []
    services: list[dict] = []
    producer_roots: set[str] = set()      # 각 문서 metadata.component 의 bom-ref (병합 뒤에는 없어진다)

    for doc in docs:
        producer_root = ((doc.get("metadata") or {}).get("component") or {}).get("bom-ref")
        if producer_root:
            producer_roots.add(producer_root)
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

    root_comp = root_component(*root) if root is not None else None
    root_key = root_comp["bom-ref"] if root_comp else None
    if root_key:
        for ref in producer_roots:            # 도구의 루트 행은 새 루트의 행이 된다 (컴포넌트이기도 하면 컴포넌트가 이긴다)
            ref_map.setdefault(ref, root_key)

    def remap(ref: str) -> str:
        return ref_map.get(ref, ref)

    merged_deps: dict[str, set[str]] = {}
    for ref, targets in dependencies.items():
        r = remap(ref)
        merged_deps.setdefault(r, set()).update(remap(t) for t in targets)

    tools["aibom-cli"] = {"type": "application", "name": "aibom-cli", "version": _version()}

    if root_key:
        # 루트는 (해석되는 행에서) 아무도 의존하지 않는 컴포넌트에 의존한다 — 그래프를 루트에서 닿게 한다
        depended = {t for r, targets in merged_deps.items() if r in components or r == root_key for t in targets}
        top = {key for key in components if key not in depended and key != root_key}
        if top or root_key in merged_deps:
            merged_deps.setdefault(root_key, set()).update(top)
            merged_deps = {root_key: merged_deps[root_key], **{r: t for r, t in merged_deps.items() if r != root_key}}

    dependencies_out = [
        {"ref": r, "dependsOn": sorted(t for t in targets if t in components or t in merged_deps)}
        for r, targets in merged_deps.items()
    ]
    metadata: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "tools": {"components": list(tools.values())},
    }
    if root_comp:
        metadata["component"] = root_comp

    return {
        "bomFormat": "CycloneDX",
        "specVersion": SPEC_VERSION,
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": metadata,
        "components": list(components.values()),
        "services": services,
        "dependencies": dependencies_out,
        "formulation": formulation,
    }


def _version() -> str:
    from . import __version__
    return __version__
