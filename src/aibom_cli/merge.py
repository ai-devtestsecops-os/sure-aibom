"""CycloneDX 문서 여러 개를 하나로 병합한다.

병합 키 (aibom_cli_plan.md §4):
    소프트웨어  purl
    모델        pkg:huggingface/ns/name@rev → 없으면 hashes → 없으면 (type, name, version)
    데이터셋    pkg:huggingface/datasets/… (cdxgen 만 생산)
    파일        경로 `file:/<path>` — syft 는 해시, cdxgen 은 purl(`?path=`)·`urn:file:ai:<path>` 로 내므로
                다른 키로는 같은 파일이 두 번 남는다.

같은 키의 컴포넌트가 여러 문서에 있으면 먼저 온 것을 기준으로 두고, 없는 필드만 뒤 것에서 채운다.
bom-ref 는 병합 키로 다시 부여하고 dependencies[] 의 참조를 따라 바꾼다.

root=(이름, 종류) 를 주면 metadata.component 를 만든다 (디렉터리 → application, 이미지 → container).
두 도구의 metadata.component 는 버리고 이것 하나가 문서의 루트가 된다. 이미지면 syft 가 metadata.properties 에 둔 OCI 라벨
(syft:image:labels:org.opencontainers.image.*, OCI image-spec annotations.md 의 미리 정한 키)을 루트의 필드로 옮긴다:
    version → version, description → description, licenses(SPDX 식) → licenses, vendor → supplier, authors → authors,
    source(+ revision) → externalReferences vcs, url → website, documentation → documentation,
    base.name(+ base.digest) → pedigree.ancestors (베이스 이미지)
각 도구가 자기 metadata.component 를 ref 로 쓴 dependencies 행은 새 루트의 행으로 옮기고, 루트는 그 밖에
아무도(컴포넌트·루트가) 의존하지 않는 컴포넌트에도 의존한다 — 그래프 전체가 루트에서 닿는다.
ref 가 컴포넌트도 루트도 아닌 행(서비스 등)은 그대로 두되(변환기가 경고하고 건너뛴다) 그 대상을 '의존받음'으로 치지 않는다.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import unquote, urlsplit

from .licenses import license_entry

SPEC_VERSION = "1.7"
ROOT_TYPE_BY_KIND = {"directory": "application", "image": "container"}


FILE_TYPE = "file"
AI_FILE_REF_PREFIX = "urn:file:ai:"       # cdxgen 이 AI 파일(gguf, Modelfile 등)에 붙이는 bom-ref
IMAGE_LABEL_PREFIX = "syft:image:labels:"
OCI = "org.opencontainers.image."
_SPDX_OPERATOR = (" AND ", " OR ", " WITH ", "(")


def identity(component: dict) -> str:
    """컴포넌트의 병합 키."""
    if component.get("type") == FILE_TYPE:
        path = file_path_of(component)
        if path:
            return f"file:/{path.lstrip('/')}"
    purl = component.get("purl")
    if purl:
        return purl
    hashes = component.get("hashes") or []
    for h in hashes:
        if h.get("alg") in ("SHA-256", "SHA-512", "SHA-1") and h.get("content"):
            return f"hash:{h['alg']}:{h['content']}"
    return f"{component.get('type', 'component')}:{component.get('group', '')}/{component.get('name', '')}@{component.get('version', '')}"


def file_path_of(component: dict) -> str | None:
    """파일 컴포넌트의 경로. cdxgen 이미지 스캔은 purl 의 `path=` 에, cdxgen AI 파일은 bom-ref `urn:file:ai:<path>` 에,
    syft 는 name 에 경로를 둔다 (디렉터리 스캔은 스캔 루트 기준, 이미지는 이미지 안 절대경로)."""
    purl = component.get("purl") or ""
    if "?" in purl:
        for pair in urlsplit(purl).query.split("&"):
            key, _, value = pair.partition("=")
            if key == "path" and value:
                return unquote(value)
    ref = component.get("bom-ref") or ""
    if ref.startswith(AI_FILE_REF_PREFIX) and len(ref) > len(AI_FILE_REF_PREFIX):
        return ref[len(AI_FILE_REF_PREFIX):]
    return component.get("name") or None


def _resolve_dataset_ref(ref: str, model_key: str, components: dict[str, dict], deps: dict[str, set[str]]) -> str | None:
    """끊긴 modelCard datasets[].ref 를 데이터셋 컴포넌트에 잇는다.

    1) ref 의 경로 끝(`datasets/bookcorpus`, `bookcorpus`)이 type=data 컴포넌트의 group/name, data[].name,
       contents.url 과 맞으면 그것. 2) 없으면 그 모델이 dependsOn 하는 data 컴포넌트가 하나뿐일 때 그것.
    """
    path = ref.split("?", 1)[0].split("pkg:huggingface/", 1)[-1].strip("/")
    tails = {path, path.rsplit("/", 1)[-1]}
    datasets = {k: c for k, c in components.items() if c.get("type") == "data"}
    for key, c in datasets.items():
        names = {f"{c.get('group', '')}/{c.get('name', '')}".strip("/"), c.get("name", "")}
        for d in c.get("data") or []:
            names.add(d.get("name", ""))
            url = (d.get("contents") or {}).get("url") or ""
            names.add(url.rstrip("/").rsplit("/datasets/", 1)[-1] if "/datasets/" in url else url)
        if tails & names:
            return key
    linked = [t for t in deps.get(model_key, set()) if t in datasets]
    return linked[0] if len(linked) == 1 else None


def fill_missing(base: dict, extra: dict) -> None:
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


def root_component(name: str, kind: str, labels: dict[str, str] | None = None) -> dict:
    """스캔 대상 → metadata.component. bom-ref 는 identity 규칙으로 정해 결정적이다 (라벨의 version 은 넣지 않는다).
    labels 는 이미지의 OCI 라벨 (키 → 값)."""
    comp = {"type": ROOT_TYPE_BY_KIND.get(kind, "application"), "name": name}
    comp["bom-ref"] = identity(comp)
    if labels:
        _apply_image_labels(comp, labels)
    return comp


def _apply_image_labels(comp: dict, labels: dict[str, str]) -> None:
    def label(key: str) -> str | None:
        value = labels.get(OCI + key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    if label("version"):
        comp["version"] = label("version")
    if label("description"):
        comp["description"] = label("description")
    if label("vendor"):
        comp["supplier"] = {"name": label("vendor")}
    if label("authors"):
        comp["authors"] = [{"name": label("authors")}]
    expression = label("licenses")
    if expression:
        comp["licenses"] = ([{"expression": expression}] if any(op in expression for op in _SPDX_OPERATOR)
                            else [license_entry(expression)])
    refs = []
    if label("source"):
        refs.append({"type": "vcs", "url": label("source"), **({"comment": f"revision: {label('revision')}"} if label("revision") else {})})
    for key, kind in (("url", "website"), ("documentation", "documentation")):
        if label(key):
            refs.append({"type": kind, "url": label(key)})
    if refs:
        comp["externalReferences"] = refs
    base = label("base.name")
    if base:
        ancestor = {"type": "container", "name": base}
        digest = label("base.digest") or ""
        if digest.startswith("sha256:") and len(digest) == 71:
            ancestor["hashes"] = [{"alg": "SHA-256", "content": digest[len("sha256:"):]}]
        comp["pedigree"] = {"ancestors": [ancestor]}


def image_labels(docs: list[dict]) -> dict[str, str]:
    """도구 문서들의 metadata.properties 에서 syft 가 적은 이미지 라벨 (키 → 값). 먼저 나온 값이 이긴다."""
    labels: dict[str, str] = {}
    for doc in docs:
        for p in (doc.get("metadata") or {}).get("properties") or []:
            name, value = p.get("name"), p.get("value")
            if isinstance(name, str) and name.startswith(IMAGE_LABEL_PREFIX) and isinstance(value, str):
                labels.setdefault(name[len(IMAGE_LABEL_PREFIX):], value)
    return labels


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
                fill_missing(components[key], comp)
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

    root_comp = root_component(*root, labels=image_labels(docs)) if root is not None else None
    root_key = root_comp["bom-ref"] if root_comp else None
    if root_key:
        for ref in producer_roots:            # 도구의 루트 행은 새 루트의 행이 된다 (컴포넌트이기도 하면 컴포넌트가 이긴다)
            ref_map.setdefault(ref, root_key)

    def remap(ref: str) -> str:
        return ref_map.get(ref, ref)

    # bom-ref 를 병합 키로 다시 매겼으니, 컴포넌트 안에서 다른 컴포넌트를 가리키는 참조도 따라 바꾼다.
    # 지금은 modelCard.modelParameters.datasets[].ref (모델 → 데이터셋) 하나다.
    # cdxgen 은 이 ref 를 데이터셋 컴포넌트의 bom-ref 가 아닌 purl 문자열로 써서 원본부터 끊겨 있으므로,
    # 재매핑으로 안 풀리면 이름·URL·의존성 엣지로 데이터셋 컴포넌트를 찾아 잇는다.
    merged_deps_preview = {remap(r): {remap(t) for t in ts} for r, ts in dependencies.items()}
    for comp in components.values():
        for entry in ((comp.get("modelCard") or {}).get("modelParameters") or {}).get("datasets") or []:
            if not (isinstance(entry, dict) and entry.get("ref")):
                continue
            ref = remap(entry["ref"])
            if ref not in components:
                ref = _resolve_dataset_ref(entry["ref"], comp["bom-ref"], components, merged_deps_preview) or ref
            entry["ref"] = ref

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
